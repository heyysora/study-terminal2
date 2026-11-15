"""FastAPI entry point. Launches with no configuration, no brokerage, no API keys.

Run (from backend/):  python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
App UI:               http://127.0.0.1:8765/        API docs: http://127.0.0.1:8765/docs
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .ai.assistant import Assistant
from .ai.providers import choose
from .alerts.service import AlertService, Notifier
from .analysis.service import AnalysisService
from .api import routes, routes2, routes_extension, routes_chart_check, routes_data, routes_crypto, routes_datahealth, routes_meme, routes_odds, routes_system, routes_futures, routes_home, routes_journal, routes_mobile, routes_news, routes_trust, routes_visual, ws
from .api.security import LocalOnlyMiddleware
from .backtest.service import BacktestService
from .config import REPO_ROOT, VERSION, Settings, get_settings
from .core.events import Broadcaster
from .core.market_clock import MarketClock
from .db.session import Database
from .education.service import EducationService
from .futures.service import FuturesService
from .journal.service import JournalService
from .news.service import NewsService
from .logging_setup import configure_logging
from .market_data.health import FeedHealthWatcher
from .market_data.providers.base import MarketDataProvider, ProviderError
from .market_data.providers.registry import create_provider
from .market_data.service import MarketMonitor
from .market_data.types import Timeframe
from .ml.model import ModelRegistry
from .paper.service import PaperService
from .scanner.service import ScanFilters, ScannerService
from .screen.service import ScreenService
from .settings.store import SettingsStore
from .signals.service import SignalService

log = logging.getLogger(__name__)
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def create_app(settings: Settings | None = None, provider: MarketDataProvider | None = None,
               clock: MarketClock | None = None, start_loops: bool = True) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        configure_logging(settings.log_level, settings.data_dir / "logs", settings.secret_values())
        from . import datacare
        from .backup import backup_before_upgrade
        from .config import BUILD
        app.state.recovery, app.state.restart_requested = None, False
        managed = not settings.database_url          # recovery and backups look after the default data file only
        if managed:
            done = datacare.apply_pending(settings.data_dir)     # a restore/rescue/fresh start you asked for
            if done:
                log.info("recovery action %s: ok=%s %s", done["action"], done["ok"], done["detail"])
            disk = datacare.check_disk(settings.data_dir)
            problem = datacare.check_database(settings.data_dir / datacare.DB_NAME)
            if not disk["writable"] or problem:
                app.state.recovery = {"kind": "disk" if not disk["writable"] else "database",
                                      "problem": disk["error"] if not disk["writable"] else problem, "disk": disk,
                                      "since": datetime.now().isoformat(timespec="seconds")}
                log.error("starting in recovery mode: %s", app.state.recovery)
                datacare.record_start(settings.data_dir, "recovery", VERSION)
                yield                                 # only the recovery and help-file endpoints work; nothing is opened
                log.info("Study Terminal stopped (recovery mode)")
                return
        backup = backup_before_upgrade(settings.data_dir, BUILD)   # copies existing data before this build opens it
        if backup["made"]:
            log.info("data backed up before first start of %s: %s", BUILD, backup["path"])
        had_data = managed and (settings.data_dir / datacare.DB_NAME).exists()
        db = Database(settings.resolved_database_url)
        db.create_all()
        if had_data:                                  # a brand-new empty data folder needs no backup
            daily = datacare.daily_backup_if_due(settings.data_dir)
            if daily and daily.get("made"):
                log.info("daily backup made: %s", daily["name"])
            elif daily and daily.get("error"):
                log.warning("daily backup skipped: %s", daily["error"])
        db.seed_default_watchlist(settings.default_watchlist)
        broadcaster = Broadcaster()
        prov = provider or create_provider(settings)
        monitor = MarketMonitor(settings=settings, db=db, provider=prov, broadcaster=broadcaster, clock=clock or MarketClock())
        paper = PaperService(settings, db, monitor, broadcaster)
        store = SettingsStore(db)
        analysis = AnalysisService(prov)
        backtests = BacktestService(db, prov, monitor.clock)
        models = ModelRegistry(settings.data_dir / "models")
        models.load()
        alerts = AlertService(db, broadcaster, Notifier(f"http://127.0.0.1:{settings.port}"))
        signals = SignalService(monitor, analysis, paper, alerts, backtests, models, store)
        scanner = ScannerService(monitor, analysis, signals)
        education = EducationService(db, analysis)
        s = app.state
        s.backup = backup
        s.settings, s.db, s.monitor, s.paper, s.settings_store = settings, db, monitor, paper, store
        s.analysis, s.backtests, s.models, s.alerts, s.signals = analysis, backtests, models, alerts, signals
        s.scanner, s.education = scanner, education
        news = NewsService(db, prov, monitor.clock, alerts, symbols_fn=lambda: monitor.monitored_symbols(),
                           enabled=settings.news_enabled)
        signals.news = news
        scanner.news = news
        s.news = news
        journal = JournalService(db, paper, store)
        journal.signals_service = signals
        signals.journal = journal
        s.journal = journal
        futures = FuturesService(settings, db, store, prov, alerts, broadcaster, news)
        s.futures = futures

        async def build_assistant():
            key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
            prov_llm, desc = await choose(store.get("ai.provider", "auto"), key, store.get("ai.model", ""), store.get("ai.ollama_url"))
            s.assistant = Assistant(prov_llm, desc)

        await build_assistant()

        async def build_context(symbol: str | None, tf: Timeframe | None = None, fetch_news: bool = False) -> dict:
            ctx: dict = {"symbol": symbol, "market": signals.market, "known_terms": education.progress()["known_terms"],
                         "scanner": [{k: r.get(k) for k in ("symbol", "action", "rank_score", "change_pct", "rvol")}
                                     for r in scanner.results[:5]]}
            try:
                perf = journal.performance()
                ctx["journal"] = {k: perf.get(k) for k in ("closed_trades", "open_trades", "net_pnl", "win_rate", "avg_r", "total_r",
                                                           "by_strategy", "mistakes", "sample_warning")}
            except Exception:  # noqa: BLE001 - the mentor must still answer without the journal
                log.exception("journal context failed")
            ctx["calibration"] = {k: {f: v.get(f) for f in ("tier", "trades", "avg_r", "expectancy_r", "avg_r_ci95", "win_rate", "note")}
                                  for k, v in backtests.calibration.items()}
            ctx["calendar"] = news.upcoming(7)
            ctx["market_mode"] = store.get("app.market_mode", "equities")
            if ctx["market_mode"] == "futures":
                try:
                    fj = futures.journal("practice")
                    ctx["futures_journal"] = {"summary": fj.get("summary"), "mistakes": fj.get("mistakes", [])[:30],
                                              "automated": fj.get("automated"), "manual": fj.get("manual")}
                    root = store.get("futures.default_root", "MES")
                    ev = futures.evidence.get(root) or {}
                    ctx["futures_research"] = {k: ev.get(k) for k in ("run", "validated", "overall", "holdout_metrics", "registry")} if ev else {}
                except Exception:  # noqa: BLE001
                    log.exception("futures journal context failed")
            if not symbol:
                return ctx
            from .futures.contracts import parse_symbol as _fparse

            if _fparse(symbol) or (store.get("app.market_mode", "equities") == "futures" and _fparse(symbol, allow_bare_root=True)):
                try:
                    fa = await futures.analysis(symbol)
                    fa.pop("chart", None)
                    ctx["futures"] = fa
                    ctx["futures_account"] = {"risk": futures.account()["risk"]}
                    code = fa["contract"]["code"]
                    ctx["futures_decisions"] = [{k: d.get(k) for k in ("id", "outcome", "reason", "evaluated_at", "acted")}
                                                for d in futures.decisions(code, limit=10)]
                    ev = futures.evidence.get(fa["contract"]["root"]) or {}
                    ctx["futures_research"] = {k: ev.get(k) for k in ("run", "validated", "overall", "holdout_metrics", "registry")} if ev else {}
                except Exception as e:  # noqa: BLE001
                    ctx["data_error"] = str(e)
                ctx.pop("calibration", None)
                return ctx
            ctx["signal_log"] = journal.signals(symbol=symbol, limit=15)
            if fetch_news and news.enabled:
                try:
                    ctx["catalysts"] = await asyncio.wait_for(news.catalysts(symbol), timeout=15)
                except Exception:  # noqa: BLE001
                    ctx["catalysts"] = {**news.cached(symbol), "news_error": "Couldn't load news from Yahoo just now."}
            else:
                ctx["catalysts"] = news.cached(symbol)
            tf = tf or signals.timeframes[0]
            try:
                ev, snap, _ = await signals.evaluate_symbol(symbol, tf)
                ctx["analysis"], ctx["signals"] = snap, ev
            except ProviderError as e:
                ctx["data_error"] = str(e)
            pos = next((p for p in paper.positions() if p["symbol"] == symbol), None)
            if pos:
                ctx["position"] = pos
                ctx["position_advice"] = signals.position_advice.get(symbol)
            if screen.fusion and screen.fusion.get("ticker") == symbol:
                ctx["screen"] = {k: v for k, v in screen.fusion.items() if k != "best_signal"}
            ctx["data_label"] = monitor.label(symbol).model_dump(mode="json") if monitor.tracker.latest(symbol) else None
            return ctx

        s.build_context = build_context

        async def screen_ai(obs, fusion, png):
            ctx = await build_context(obs.get("ticker"), Timeframe(obs["timeframe"]) if obs.get("timeframe") else None)
            ctx["screen_observation"] = obs
            return await s.assistant.ask("Explain what's on my chart right now and whether there's a valid setup.", ctx,
                                         image_png=png if s.assistant.provider.supports_vision else None,
                                         level=store.get("learning.level", "beginner"))

        health = FeedHealthWatcher(monitor, alerts, paper.positions)
        s.health = health

        screen = ScreenService(monitor, signals, store, broadcaster, screen_ai)
        from .screen.calibration import CalibrationStore
        screen.calibration = CalibrationStore(settings.data_dir)
        screen.futures = futures
        s.screen = screen
        from .screen.chart_profile import ProfileStore
        from .screen.visual_monitor import VisualMonitor
        visual = VisualMonitor(ProfileStore(settings.data_dir), futures, alerts, broadcaster, store)
        s.visual = visual
        from .watchdog import Watchdog
        watchdog = Watchdog(visual, alerts, settings.data_dir)
        watchdog.started()
        s.watchdog = watchdog
        from .validation.chart_check import ChartCheck
        s.chart_check = ChartCheck(settings.data_dir, visual, watchdog, VERSION)
        from .memecoins.practice import MemeCosts
        from .memecoins.service import MemeService
        meme = MemeService(db, alerts, store.get("memecoins.rpc_url"))
        meme.practice.costs = MemeCosts(start_usd=float(store.get("memecoins.start_usd", 500.0) or 500.0),
                                        fee_pct=float(store.get("memecoins.fee_pct", 1.0) or 1.0),
                                        network_fee_usd=float(store.get("memecoins.network_fee_usd", 0.05) or 0.05),
                                        max_trade_pct=float(store.get("memecoins.max_trade_pct", 10.0) or 10.0))
        s.meme = meme
        from .market_data.exchanges import CryptoMarkets
        s.crypto = CryptoMarkets()
        from .datahealth import probes as dhp
        from .datahealth.chartwatch import ChartWatch
        from .datahealth.engine import DataHealth
        from .safety import SafetyController

        def _open_positions():
            out = [{"market": "futures" if "=" in p["symbol"] or p["symbol"][-1:].isdigit() else SafetyController.market_of(p["symbol"]),
                    "symbol": p["symbol"], "account": "stock practice"} for p in paper.positions()]
            out += [{"market": "memecoins", "symbol": p["token"], "name": p["symbol"], "account": "memecoin practice"} for p in meme.practice.positions()]
            return out

        datahealth = DataHealth(db, [
            dhp.YahooProbe("yahoo_stocks", "Stock prices (Yahoo Finance)", "stocks", monitor, ["SPY", "QQQ"], max_age_s=1200),
            dhp.YahooProbe("yahoo_futures", "Futures prices (Yahoo Finance, delayed)", "futures", monitor, ["NQ=F", "ES=F", "MNQ=F", "MES=F"],
                           max_age_s=1800, pairs=[("NQ=F", "MNQ=F"), ("ES=F", "MES=F")], delayed="10 to 15 minutes"),
            dhp.CryptoProbe(s.crypto), dhp.MemecoinProbe(meme.data, lambda: [p["token"] for p in meme.practice.positions()]),
            dhp.SolanaRpcProbe(meme.data), dhp.pumpfun_probe(), dhp.fomo_probe(),
        ], chartwatch=ChartWatch(db, visual, monitor, real_fn=lambda: getattr(visual, "capture_fn", None) is None), positions_fn=_open_positions)
        s.datahealth = datahealth
        safety = SafetyController(datahealth, stopped_fn=lambda: futures.automation.state.status == "emergency_stopped",
                                  recovery_fn=lambda: bool(getattr(app.state, "recovery", None)))
        s.safety = safety
        monitor.safety = signals.safety = futures.safety = meme.safety = safety

        def apply(changes: dict | None = None):
            v = store.all()
            pc, rc = paper.cfg, paper.risk
            for k, attr in (("paper.slippage_bps", "slippage_bps"), ("paper.slippage_min", "slippage_min"),
                            ("paper.commission_per_share", "commission_per_share"), ("paper.commission_per_order", "commission_per_order"),
                            ("paper.allow_short", "allow_short"), ("paper.margin_multiplier", "margin_multiplier"),
                            ("paper.borrow_fee_annual_pct", "borrow_fee_annual_pct")):
                if v.get(k) is not None:
                    setattr(pc, attr, v[k])
            for k, attr in (("risk.max_per_trade_pct", "max_per_trade_pct"), ("risk.max_daily_loss_pct", "max_daily_loss_pct"),
                            ("risk.max_open_positions", "max_open_positions"), ("risk.min_reward_risk", "min_reward_risk"),
                            ("risk.require_stop", "require_stop"), ("risk.max_consecutive_losses", "max_consecutive_losses"),
                            ("risk.max_exposure_pct", "max_exposure_pct")):
                if v.get(k) is not None:
                    setattr(rc, attr, v[k])
            meme.set_rpc(v.get("memecoins.rpc_url"))
            mc = meme.practice.costs
            mc.start_usd = float(v.get("memecoins.start_usd") or 500.0)
            mc.fee_pct = float(v.get("memecoins.fee_pct") if v.get("memecoins.fee_pct") is not None else 1.0)
            mc.network_fee_usd = float(v.get("memecoins.network_fee_usd") if v.get("memecoins.network_fee_usd") is not None else 0.05)
            mc.max_trade_pct = float(v.get("memecoins.max_trade_pct") or 10.0)
            rc.max_trades_per_day = v.get("risk.max_trades_per_day") or None          # off unless you set them
            rc.warn_trades_per_day = int(v.get("journal.max_trades_per_day") or 3)    # one number for the warning and the journal
            ntime = (v.get("risk.no_new_entries_after") or "").strip()
            rc.no_new_entries_after = ntime if len(ntime) == 5 and ntime[2] == ":" else None
            alerts.prefs.update({"desktop": v["alerts.desktop"], "sound": v["alerts.sound"],
                                 "min_severity_desktop": v["alerts.min_severity_desktop"],
                                 "min_severity_sound": v["alerts.min_severity_sound"], "categories": v["alerts.categories"]})
            scanner.filters = ScanFilters(**v["scanner.filters"]) if v["scanner.filters"] else ScanFilters()
            scanner.interval_s, scanner.enabled = v["scanner.interval_seconds"], v["scanner.enabled"]
            futures.apply(changes)
            if changes and any(k.startswith("ai.") for k in changes):
                import asyncio
                asyncio.ensure_future(build_assistant())

        apply()
        store.listeners.append(apply)

        log.info("Study Terminal starting: provider=%s, AI=%s, paper simulator, no brokerage", prov.info.name, s.assistant.provider_desc)
        await monitor.start()
        await paper.start()
        if start_loops:
            await signals.start()
            await scanner.start()
            await health.start()
            await news.start()
            await futures.start()
            await visual.autostart()
            await meme.start()
            await datahealth.start()

            async def watch():
                n = 0
                while True:
                    await asyncio.sleep(5)
                    n += 1
                    try:
                        watchdog.check()
                    except Exception:  # noqa: BLE001 - the watchdog must never take the app down
                        log.exception("watchdog check failed")
                    if managed and n % 720 == 0:          # hourly: a daily backup if one is due (app left running for days)
                        try:
                            await asyncio.to_thread(datacare.daily_backup_if_due, settings.data_dir)
                        except Exception:  # noqa: BLE001
                            log.exception("daily backup check failed")
            s.watchdog_task = asyncio.create_task(watch())
        if managed:
            datacare.record_start(settings.data_dir, "normal", VERSION)     # everything started: this is the last good start
        try:
            yield
        finally:
            if getattr(s, "watchdog_task", None):
                s.watchdog_task.cancel()
            if screen.state != "off":
                await screen.stop()
            if visual._task:
                visual._task.cancel()
            await health.stop()
            await meme.stop()
            await datahealth.stop()
            await s.crypto.stop()
            await futures.stop()
            await news.stop()
            await scanner.stop()
            await signals.stop()
            await paper.stop()
            await monitor.stop()
            db.dispose()
            watchdog.stopped()                       # clean exit: next start won't report an unexpected close
            log.info("Study Terminal stopped")

    app = FastAPI(title="Study Terminal API", version=VERSION, lifespan=lifespan)
    app.state.boot_settings = settings

    @app.middleware("http")
    async def recovery_guard(request, call_next):
        """In Recovery mode only the data/help endpoints, the desktop shell and the page itself work."""
        rec = getattr(request.app.state, "recovery", None)
        path = request.url.path
        if rec and path.startswith("/api/"):
            if path == "/api/health":
                return JSONResponse({"app": "Study Terminal", "recovery": rec, "database_ok": False, "brokerage_required": False,
                                     "execution": "local paper simulator only", "version": VERSION})
            if not path.startswith(("/api/data/", "/api/desktop/", "/api/system/")):
                return JSONResponse({"detail": "Study Terminal is in Recovery mode.", "recovery": True}, status_code=503)
        return await call_next(request)

    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
                       allow_methods=["GET", "POST", "DELETE", "PUT", "PATCH"],
                       allow_headers=["Content-Type", "X-Study-Terminal", "X-Study-Token"])
    # Outermost: reject DNS-rebinding hosts and cross-site state changes (see api/security.py)
    app.add_middleware(LocalOnlyMiddleware, port=settings.port,
                       extra_hosts=["t", "testserver"] if settings.app_env == "test" else [],
                       mobile_hosts=settings.mobile_allowed_hosts.split(","))
    app.include_router(routes.router)
    app.include_router(routes2.router)
    app.include_router(routes_journal.router)
    app.include_router(routes_news.router)
    app.include_router(routes_extension.router)
    app.include_router(routes_futures.router)
    app.include_router(routes_mobile.router)
    app.include_router(routes_visual.router)
    app.include_router(routes_trust.router)
    app.include_router(routes_home.router)
    app.include_router(routes_chart_check.router)
    app.include_router(routes_data.router)
    app.include_router(routes_system.router)
    app.include_router(routes_odds.router)
    app.include_router(routes_meme.router)
    app.include_router(routes_datahealth.router)
    app.include_router(routes_crypto.router)
    app.include_router(ws.router)
    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")
    return app


app = create_app()

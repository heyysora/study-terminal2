import { useState } from "react";
import { api, dismissToast, money, pct, sign, useHashRoute, useLive, usePoll } from "./lib";
import { Meter } from "./components";
import { ChartPage, Copilot, Dashboard, Paper, Scanner } from "./pages";
import { Alerts, Backtest, Learn, Settings } from "./pages2";
import { Journal } from "./pages3";
import { Futures } from "./pages4";
import { AutomationCenter } from "./pages5";
import { LiveMarket } from "./pages6";

const NAV: [string, string, string?][] = [
  ["dashboard", "Dashboard"], ["chart", "Chart"], ["copilot", "Live copilot"], ["scanner", "Scanner"],
  ["paper", "Paper trading"], ["automation", "Automation Center"], ["live", "Live Market"], ["futures", "Futures (TopstepX)"], ["journal", "Journal"], ["backtest", "Backtest", "Research"], ["learn", "Learn"], ["alerts", "Alerts", "System"], ["settings", "Settings"],
];

function ModeSwitch({ mode, onChange }: { mode: string; onChange: (m: string) => void }) {
  return (
    <div className="cell"><span className="k">Market</span><span className="v row" style={{ gap: 4 }}>
      {[["equities", "Stocks"], ["futures", "Futures"]].map(([m, label]) => <button key={m} className={`small ${mode === m ? "primary" : "ghost"}`} onClick={() => onChange(m)}>{label}</button>)}
    </span></div>
  );
}

function FuturesStrip({ mode, onMode }: { mode: string; onMode: (m: string) => void }) {
  const a = usePoll("/futures/paper", 20000);
  const r = a.data?.risk;
  const m = r?.metrics || {};
  const o = r?.official || {};
  return (
    <div className="strip" role="status">
      <ModeSwitch mode={mode} onChange={onMode} />
      <div className="cell"><span className="k">Futures sim balance</span><span className="v">{a.data ? money(m.balance) : "—"}</span></div>
      <div className="cell"><span className="k">Day P&amp;L</span><span className={`v ${sign(m.day_pnl)}`}>{a.data ? money(m.day_pnl) : "—"}</span></div>
      <div className="cell"><span className="k">Room above max loss</span><span className="v">{o.mll_remaining != null ? money(o.mll_remaining) : "—"}</span></div>
      <div className="cell"><span className="k">Rules</span><span className="v">{o.label || "—"}{o.enabled && !o.confirmed ? <span className="small down"> unconfirmed</span> : null}</span></div>
      <div className="cell"><span className="k">Entries</span><span className={`v ${r?.blocked ? "down" : ""}`}>{r ? (r.blocked ? "Blocked" : "Allowed") : "—"}</span></div>
      <div className="cell grow" />
      <div className="cell"><span className="k">Execution</span><span className="v">Simulator only</span></div>
    </div>
  );
}

function StatusStrip({ mode, onMode }: { mode: string; onMode: (m: string) => void }) {
  const L = useLive();
  const st = L.status;
  const mk = st?.market;
  const acct = L.paper;
  const scr = L.screen;
  const streamOk = st?.stream?.state === "connected";
  const feedStatus = !L.connected ? "unavailable" : !st?.monitoring_enabled ? "unavailable" : streamOk ? "near_realtime" : st?.healthy ? "polling" : "stale";
  const session = mk ? ({ premarket: "Premarket", regular: "Market open", after_hours: "After hours", closed: "Market closed" } as any)[mk.session] : "—";
  return (
    <div className="strip" role="status">
      <ModeSwitch mode={mode} onChange={onMode} />
      <div className="cell"><span className="k">Session</span><span className="v">{session}{mk?.early_close ? ", early close" : ""}</span></div>
      <div className="cell"><span className="k">Market data</span><span className="v"><Meter status={feedStatus} reason={st?.health_reason} />
        {!L.connected ? "App offline" : !st?.monitoring_enabled ? "Paused" : streamOk ? "Stream + polling" : st?.healthy ? "Polling only" : "Problem"}</span></div>
      <div className="cell"><span className="k">Screen</span><span className="v"><span className={`live-dot ${scr?.state === "running" ? "rec" : ""}`} />
        {scr?.state === "running" ? "Watching" : scr?.state === "paused" ? "Paused" : "Off"}</span></div>
      <div className="cell"><span className="k">Paper equity</span><span className="v">{acct ? money(acct.equity) : "—"}</span></div>
      <div className="cell"><span className="k">Day P&amp;L</span><span className={`v ${sign(acct?.day_pnl)}`}>{acct ? money(acct.day_pnl) : "—"}
        {acct?.daily_loss_limit_hit && <span className="down small">limit hit</span>}</span></div>
      <div className="cell"><span className="k">Market bias</span><span className="v">{L.signals?.market?.bias ? `SPY ${L.signals.market.bias}` : "—"}
        {L.signals?.market?.spy_change_pct != null && <span className={sign(L.signals.market.spy_change_pct)}>{pct(L.signals.market.spy_change_pct)}</span>}</span></div>
      <div className="cell grow" />
      <div className="cell"><span className="k">Execution</span><span className="v">Paper only</span></div>
    </div>
  );
}

export default function App() {
  const [route] = useHashRoute();
  const L = useLive();
  const unread = L.alerts.length;
  const settings = usePoll("/settings");
  const [mode, setMode] = useState<string | null>(null);
  const curMode = mode ?? settings.data?.values?.["app.market_mode"] ?? "equities";
  const switchMode = async (m: string) => {
    setMode(m);
    try { await api("/settings", { method: "PUT", json: { "app.market_mode": m } }); } catch { /* the switch still works for this session */ }
    location.hash = m === "futures" ? "#/automation" : "#/dashboard";
  };
  const page = route[0] || (curMode === "futures" ? "automation" : "dashboard");
  const view = (() => {
    switch (page) {
      case "futures": return <Futures symbol={route[1]} />;
      case "automation": return <AutomationCenter />;
      case "live": return <LiveMarket />;
      case "chart": return <ChartPage symbol={route[1]} />;
      case "copilot": return <Copilot />;
      case "scanner": return <Scanner />;
      case "paper": return <Paper />;
      case "journal": return <Journal />;
      case "backtest": return <Backtest />;
      case "learn": return <Learn id={route[1]} />;
      case "alerts": return <Alerts />;
      case "settings": return <Settings />;
      default: return <Dashboard />;
    }
  })();
  return (
    <div className="shell">
      <div className="brand"><span className="brand-mark" />Study Terminal</div>
      {curMode === "futures" || page === "futures" ? <FuturesStrip mode="futures" onMode={switchMode} /> : <StatusStrip mode={curMode} onMode={switchMode} />}
      <nav className="rail" aria-label="Main">
        {NAV.map(([id, label, group]) => (
          <div key={id}>
            {group && <div className="group">{group}</div>}
            <a href={`#/${id}`} className={page === id || (page === "" && id === "dashboard") ? "on" : ""}>
              {label}{id === "alerts" && unread > 0 && <span className="badge">{unread > 99 ? "99+" : unread}</span>}
            </a>
          </div>
        ))}
      </nav>
      <main className="main">{view}</main>
      <div className="toast-stack" aria-live="polite">
        {L.toasts.map((t) => (
          <div key={t.id} className={`toast ${t.severity}`} role="alert">
            <div className="spread"><b>{t.title}</b><button className="ghost" onClick={() => dismissToast(t)} aria-label="Dismiss">✕</button></div>
            <div className="small muted" style={{ whiteSpace: "pre-wrap", maxHeight: 110, overflow: "hidden" }}>{t.body}</div>
            {t.symbol && <a href={`#/chart/${t.symbol}`} className="small">Open chart and full analysis</a>}
          </div>
        ))}
      </div>
    </div>
  );
}

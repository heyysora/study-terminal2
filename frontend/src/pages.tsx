import { useEffect, useMemo, useState } from "react";
import { Action, CandleChart, ChartStamp, Meter, OrderTicket, Panel, QuoteStamp, SignalCard, type Overlay, type PriceLine } from "./components";
import { Catalysts, EconCalendar } from "./pages3";
import { TIMEFRAMES, api, etTime, money, num, pct, sign, tfShort, useLive, usePoll } from "./lib";
import { useUiMode } from "./plain";
import { SimpleStockChart } from "./pagesChart";
import { FuturesPlan } from "./pages4";

// ======================= Dashboard =======================
export function Dashboard() {
  const L = useLive();
  const live = usePoll("/market/live", 15000);
  const sigs = usePoll("/signals", 20000);
  const scan = usePoll("/scanner", 30000);
  const pos = usePoll("/paper/positions", 10000, [L.paper]);
  const [add, setAdd] = useState("");
  const wls = usePoll("/watchlists");
  const syms = live.data?.symbols || [];
  const sigBy: Record<string, any> = {};
  for (const s of (L.signals?.summary || sigs.data?.summary || [])) sigBy[s.symbol] = s;
  const addSym = async () => {
    const wl = wls.data?.[0];
    if (!wl || !add.trim()) return;
    await api(`/watchlists/${wl.id}/symbols`, { method: "POST", json: { symbols: [add.trim().toUpperCase()] } });
    setAdd(""); live.reload();
  };
  const opps = (scan.data?.results || []).slice(0, 8);
  const active = Object.values(sigBy).filter((s: any) => s.action && s.action !== "NO TRADE");
  return (
    <div className="page">
      <div className="cols c-dash">
        <Panel title="Watchlist" sub={`${syms.length} monitored`} flush right={
          <form className="row" onSubmit={(e) => { e.preventDefault(); addSym(); }}>
            <input aria-label="Add symbol" placeholder="Add symbol" value={add} onChange={(e) => setAdd(e.target.value)} style={{ width: 100 }} />
          </form>}>
          {syms.length === 0 ? <div className="empty">Add a symbol to start monitoring it.</div> :
            <table><thead><tr><th>Symbol</th><th className="r">Last</th><th>Data</th><th>Signal</th></tr></thead><tbody>
              {syms.map((s: any) => {
                const lv = L.symbols[s.symbol] || s;
                const last = lv.last || s.last;
                const sg = sigBy[s.symbol];
                return (
                  <tr key={s.symbol} className="click" onClick={() => (location.hash = `#/chart/${s.symbol}`)}>
                    <td className="sym">{s.symbol}</td>
                    <td className="r num">{last ? num(last.price) : "—"}{last?.change_pct != null && <span className={`small ${sign(last.change_pct)}`}> {pct(last.change_pct, 1)}</span>}</td>
                    <td><Meter status={(lv.label || s.label)?.status} reason={(lv.label || s.label)?.reason} /> <QuoteStamp compact label={lv.label || s.label} /></td>
                    <td>{sg ? <Action a={sg.action} /> : <span className="faint small">—</span>}</td>
                  </tr>);
              })}
            </tbody></table>}
        </Panel>

        <div className="stack">
          <Panel title="Live signals" sub={active.length ? `${active.length} active` : "none active"}>
            {active.length === 0 ? (
              <p className="muted" style={{ margin: 0 }}>No setup worth acting on right now. That's a normal and often correct answer: waiting is a position.
                {L.status?.market?.session === "closed" && " The market is closed, so signals pause until the next session."}</p>
            ) : (
              <table><tbody>{active.map((s: any) => (
                <tr key={s.symbol} className="click" onClick={() => (location.hash = `#/chart/${s.symbol}`)}>
                  <td className="sym">{s.symbol}</td><td><Action a={s.action} /></td><td>{s.setup}</td><td className="muted">{s.state}</td>
                  <td className="r num">{s.quality ?? "—"}<span className="faint">/100</span></td></tr>))}
              </tbody></table>)}
          </Panel>
          <Panel title="Top opportunities" sub={scan.data?.last_run ? `scanned ${etTime(scan.data.last_run)} ET` : "scanner runs in premarket and market hours"} flush
            right={<a href="#/scanner" className="small">Scanner</a>}>
            {opps.length === 0 ? <div className="empty">No ranked candidates yet. Run the scanner, or wait for the next automatic scan.</div> :
              <table><thead><tr><th>Symbol</th><th className="r">Chg</th><th className="r">RVOL</th><th>Setup</th><th className="r">Score</th></tr></thead><tbody>
                {opps.map((r: any) => (
                  <tr key={r.symbol} className="click" onClick={() => (location.hash = `#/chart/${r.symbol}`)}>
                    <td className="sym">{r.symbol}</td><td className={`r ${sign(r.change_pct)}`}>{pct(r.change_pct, 1)}</td>
                    <td className="r">{num(r.rvol, 1)}</td><td>{r.best_signal ? <Action a={r.action} /> : r.watch_signal ? <span title="No reliable out-of-sample edge"><Action a={r.watch_signal.action} /> <span className="faint small">watch</span></span> : <span className="faint">none</span>}</td>
                    <td className="r">{r.rank_score}</td></tr>))}
              </tbody></table>}
          </Panel>
        </div>

        <div className="stack">
          <Panel title="Practice account" sub="pretend money">
            {L.paper ? (
              <div className="stack">
                <div className="spread"><span className="muted">Equity</span><span className="num" style={{ fontSize: 20 }}>{money(L.paper.equity)}</span></div>
                <div className="spread small"><span className="muted">Buying power</span><span className="num">{money(L.paper.buying_power)}</span></div>
                <div className="spread small"><span className="muted">Day P&amp;L</span><span className={`num ${sign(L.paper.day_pnl)}`}>{money(L.paper.day_pnl)}</span></div>
                <div className="spread small"><span className="muted">Week P&amp;L</span><span className={`num ${sign(L.paper.week_pnl)}`}>{money(L.paper.week_pnl)}</span></div>
                <div className="spread small"><span className="muted">Daily loss limit</span><span className="num">{money(-L.paper.daily_loss_limit)}</span></div>
                {L.paper.daily_loss_limit_hit && <div className="note bad">Daily loss limit reached. New entries are off for today. This is the moment to stop.</div>}
              </div>) : <div className="muted">Loading…</div>}
          </Panel>
          <Panel title="Positions" flush right={<a href="#/paper" className="small">Practice trading</a>}>
            {!pos.data?.length ? <div className="empty">No open positions.</div> :
              <table><tbody>{pos.data.map((p: any) => {
                const adv = sigs.data?.positions?.[p.symbol];
                return (<tr key={p.symbol} className="click" onClick={() => (location.hash = `#/chart/${p.symbol}`)}>
                  <td className="sym">{p.symbol}</td><td>{p.side} {Math.abs(p.qty)}</td>
                  <td className={`r num ${sign(p.unrealized_pnl)}`}>{money(p.unrealized_pnl)}</td><td>{adv ? <Action a={adv.action} /> : null}</td></tr>);
              })}</tbody></table>}
          </Panel>
          <Panel title="Latest alerts" flush right={<a href="#/alerts" className="small">All alerts</a>}>
            {L.alerts.length === 0 ? <div className="empty">No alerts this session.</div> :
              L.alerts.slice(0, 5).map((a) => (
                <div key={a.id} className={`alert ${a.severity}`}><span className="bar" /><div><div className="t">{a.title}</div>
                  <div className="small faint">{etTime(a.ts)} ET</div></div></div>))}
          </Panel>
          <EconCalendar />
        </div>
      </div>
    </div>
  );
}

// ======================= Chart workspace =======================
export function ChartPage({ symbol }: { symbol?: string }) {
  return useUiMode() === "simple" ? <SimpleStockChart symbol={symbol} /> : <ChartPageAdvanced symbol={symbol} />;
}

function ChartPageAdvanced({ symbol: routeSym }: { symbol?: string }) {
  const L = useLive();
  const [sym, setSym] = useState((routeSym || "SPY").toUpperCase());
  const [input, setInput] = useState(sym);
  const [tf, setTf] = useState("5Min");
  const [prefill, setPrefill] = useState<any>(null);
  const [ext, setExt] = useState(false);
  useEffect(() => { if (routeSym) { setSym(routeSym.toUpperCase()); setInput(routeSym.toUpperCase()); } }, [routeSym]);
  const htf = tf === "1Day" ? "1Day" : tf === "1Hour" || tf === "4Hour" ? "1Day" : "1Hour";
  const an = usePoll(`/analysis/${sym}?timeframes=${tf}${htf !== tf ? "," + htf : ""}&chart=${tf}&extended=${ext}`, 60000, []);
  const sg = usePoll(`/signals/${sym}?timeframe=${tf}`, 30000, []);
  const ex = usePoll(`/ai/explain/${sym}?timeframe=${tf}`, 0, [tf]);
  const snap = an.data?.snapshots?.[tf];
  const best = sg.data?.best || sg.data?.watch || (sg.data?.signals || [])[0];
  const overlays: Overlay[] = useMemo(() => {
    const s = an.data?.chart?.series || {};
    const o: Overlay[] = [];
    if (s.vwap) o.push({ name: "VWAP", data: s.vwap, color: "#e0a43a", width: 2 });
    if (s.ema9) o.push({ name: "EMA 9", data: s.ema9, color: "#7aa2f7" });
    if (s.ema21) o.push({ name: "EMA 21", data: s.ema21, color: "#bb9af7" });
    if (s.ema50) o.push({ name: "EMA 50", data: s.ema50, color: "#5b6778" });
    return o;
  }, [an.data]);
  const lines: PriceLine[] = useMemo(() => {
    const l: PriceLine[] = [];
    const se = snap?.session || {};
    if (se.pdh) l.push({ price: se.pdh, title: "PDH", color: "#5b6778", dashed: true });
    if (se.pdl) l.push({ price: se.pdl, title: "PDL", color: "#5b6778", dashed: true });
    if (se.or_high) l.push({ price: se.or_high, title: "OR high", color: "#4a5568", dashed: true });
    if (se.or_low) l.push({ price: se.or_low, title: "OR low", color: "#4a5568", dashed: true });
    if (best && best.action !== "NO TRADE") {
      l.push({ price: best.trigger, title: "Entry", color: "#e0a43a" });
      l.push({ price: best.stop, title: "Stop", color: "#e5534b" });
      l.push({ price: best.targets.t1, title: "T1", color: "#3fb68b", dashed: true });
      l.push({ price: best.targets.t2, title: "T2", color: "#3fb68b" });
    }
    return l;
  }, [snap, best]);
  const lv = L.symbols[sym];
  const label = lv?.label || an.data?.data_label;
  return (
    <div className="page">
      <div className="spread">
        <form className="row" onSubmit={(e) => { e.preventDefault(); location.hash = `#/chart/${input.trim().toUpperCase()}`; }}>
          <input aria-label="Symbol" value={input} onChange={(e) => setInput(e.target.value)} style={{ width: 110, fontSize: 16, fontWeight: 600 }} />
          <div className="seg" role="group" aria-label="Timeframe">{TIMEFRAMES.map((t) => <button type="button" key={t} className={tf === t ? "on" : ""} onClick={() => setTf(t)}>{tfShort(t)}</button>)}</div>
          <label className="check small"><input type="checkbox" checked={ext} onChange={(e) => setExt(e.target.checked)} />Extended hours</label>
        </form>
        <div className="stack" style={{ gap: 2, alignItems: "flex-end" }}>
          <div className="row"><span className="num" style={{ fontSize: 22, fontWeight: 600 }}>{num(lv?.last?.price ?? snap?.price)}</span><Meter big withText status={label?.status} reason={label?.reason} /></div>
          {lv?.label ? <QuoteStamp label={lv.label} /> : <span className="stamp">Not monitored live: price shown is the last closed bar</span>}
        </div>
      </div>
      {label && label.status !== "near_realtime" && label.status !== "realtime" && <div className="note warn">{label.reason}</div>}
      <div className="cols c-chart">
        <div className="stack">
          <section className="panel">
            {an.error ? <div className="empty">{an.error}</div> : !an.data ? <div className="empty">Loading {sym}…</div> :
              <CandleChart bars={an.data.chart.bars} overlays={overlays} lines={lines} daily={tf === "1Day"} />}
            {an.data && <ChartStamp data={an.data.data} />}
          </section>
          {snap?.notes?.length > 0 && <div className="note small">{snap.notes.slice(0, 3).join(" ")}</div>}
          <Panel title="Explain this chart" sub="plain-language read of the data above">
            {ex.data ? ex.data.sections.map((s: any) => <p key={s.heading}><b>{s.heading}.</b> {s.body}</p>) : <span className="muted">Loading…</span>}
            {ex.data?.ai && <div className="note"><b>AI mentor ({ex.data.ai.engine}).</b><div className="msg">{ex.data.ai.answer}</div></div>}
          </Panel>
          {snap && (
            <Panel title="Indicators" sub={`${tfShort(tf)}, closed bars only`} flush>
              <table><tbody>
                <tr><td className="muted">EMA 9 / 21 / 50 / 200</td><td className="r">{num(snap.moving_averages.ema9)} / {num(snap.moving_averages.ema21)} / {num(snap.moving_averages.ema50)} / {num(snap.moving_averages.ema200)}</td></tr>
                <tr><td className="muted">SMA 20 / 50 / 200</td><td className="r">{num(snap.moving_averages.sma20)} / {num(snap.moving_averages.sma50)} / {num(snap.moving_averages.sma200)}</td></tr>
                <tr><td className="muted">RSI / Stoch K / ROC</td><td className="r">{num(snap.momentum.rsi, 1)} / {num(snap.momentum.stoch_k, 1)} / {pct(snap.momentum.roc)}</td></tr>
                <tr><td className="muted">MACD / signal / hist</td><td className="r">{num(snap.momentum.macd, 3)} / {num(snap.momentum.macd_signal, 3)} / {num(snap.momentum.macd_hist, 3)}</td></tr>
                <tr><td className="muted">VWAP / RVOL / pressure</td><td className="r">{num(snap.session.vwap)} / {num(snap.volume.rvol)}x / {num(snap.volume.pressure)}</td></tr>
                <tr><td className="muted">ATR / ATR% / HV</td><td className="r">{num(snap.volatility.atr)} / {num(snap.volatility.atr_pct)}% / {num(snap.volatility.hv, 1)}%</td></tr>
                <tr><td className="muted">Bollinger upper / lower</td><td className="r">{num(snap.volatility.bb_upper)} / {num(snap.volatility.bb_lower)}</td></tr>
                <tr><td className="muted">Volume profile POC / VAH / VAL</td><td className="r">{snap.volume.profile ? `${num(snap.volume.profile.poc)} / ${num(snap.volume.profile.vah)} / ${num(snap.volume.profile.val)}` : "—"}</td></tr>
                <tr><td className="muted">Prev day high / low / close</td><td className="r">{num(snap.session.pdh)} / {num(snap.session.pdl)} / {num(snap.session.pdc)}</td></tr>
                <tr><td className="muted">Premarket high / low</td><td className="r">{num(snap.session.pm_high)} / {num(snap.session.pm_low)}</td></tr>
                <tr><td className="muted">Opening range</td><td className="r">{num(snap.session.or_low)} – {num(snap.session.or_high)}</td></tr>
                <tr><td className="muted">Structure</td><td className="r">{snap.structure.state}{snap.structure.consolidating ? ", consolidating" : ""}{snap.structure.bull_divergence ? ", bullish divergence" : ""}{snap.structure.bear_divergence ? ", bearish divergence" : ""}</td></tr>
              </tbody></table>
            </Panel>)}
        </div>
        <div className="stack">
          <Panel title="Signal" sub={sg.data ? `${tfShort(tf)}` : ""} right={sg.data && <Action a={sg.data.action} />}>
            {!sg.data ? <span className="muted">{sg.error || "Evaluating…"}</span> :
              best ? <div className="stack">{sg.data.action === "NO TRADE" && sg.data.reasons.map((r: string, i: number) => <p key={i} className="small" style={{ margin: 0 }}>{r}</p>)}
                <SignalCard s={best} onTrade={setPrefill} /></div> :
                <div className="stack"><p style={{ margin: 0 }}>NO TRADE.</p>{sg.data.reasons.map((r: string, i: number) => <p key={i} className="muted small">{r}</p>)}</div>}
            {sg.data?.signals?.length > 1 && <details><summary>Other setups on this chart ({sg.data.signals.length - 1})</summary>
              {sg.data.signals.filter((s: any) => s !== best).map((s: any) => <div key={s.id} className="spread small" style={{ padding: "3px 0" }}><span>{s.setup_name}</span><Action a={s.action} /></div>)}</details>}
          </Panel>
          <Catalysts symbol={sym} />
          {an.data?.mtf && <Panel title="Timeframes" sub={an.data.mtf.aligned ? "aligned" : "mixed"}>
            {an.data.mtf.timeframes.map((t: any) => <div key={t.timeframe} className="spread small"><span>{tfShort(t.timeframe)}</span><span className={t.bias === "bullish" ? "up" : t.bias === "bearish" ? "down" : "muted"}>{t.bias} ({t.score})</span></div>)}
            <p className="small muted" style={{ marginTop: 6 }}>{an.data.mtf.note}</p></Panel>}
          {snap && <Panel title="Evidence" sub={`bias ${snap.bias.label} (${snap.bias.score})`}>
            {snap.factors.map((f: any) => <p key={f.factor} className="small"><span className={f.direction === "bullish" ? "up" : f.direction === "bearish" ? "down" : "muted"}>{f.factor}.</span> {f.why}</p>)}
            {snap.candles.map((c: any, i: number) => <p key={i} className="small muted">{c.meaning}</p>)}</Panel>}
          <Panel title="Practice order"><OrderTicket symbol={sym} prefill={prefill} /></Panel>
        </div>
      </div>
    </div>
  );
}

// ======================= Live copilot (screen + AI) =======================
export function Copilot() {
  const L = useLive();
  const status = usePoll("/screen/status", 5000);
  const targets = usePoll("/screen/targets");
  const plats = usePoll("/screen/platforms");
  const setPlatform = async (id: string) => { await api("/settings", { method: "PUT", json: { [plats.data?.setting_key || "screen.platform"]: id } }); plats.reload(); };
  const ai = usePoll("/ai/status");
  const [sel, setSel] = useState<any>(null);
  const [consent, setConsent] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [chat, setChat] = useState<{ q: string; a: any }[]>([]);
  const [asking, setAsking] = useState(false);
  const [uploaded, setUploaded] = useState<any>(null);
  const s = L.screen || status.data;
  const useUpload = uploaded && s?.state !== "running";
  const obs = useUpload ? uploaded.observation : s?.observation;
  const fu = useUpload ? uploaded.fusion : s?.fusion;
  const start = async () => {
    setErr(null);
    try { await api("/screen/start", { method: "POST", json: { target: sel, consent } }); status.reload(); }
    catch (e: any) { setErr(e.message); }
  };
  const ctl = async (a: string) => { await api(`/screen/${a}`, { method: "POST" }); status.reload(); };
  const ask = async (question: string) => {
    if (!question.trim()) return;
    setAsking(true);
    try {
      const r = await api("/ai/ask", { method: "POST", json: { question, symbol: fu?.ticker || undefined } });
      setChat((c) => [{ q: question, a: r }, ...c]);
    } catch (e: any) { setChat((c) => [{ q: question, a: { answer: e.message, engine: "error" } }, ...c]); }
    finally { setAsking(false); setQ(""); }
  };
  const upload = async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/screen/analyze-image", { method: "POST", body: fd, headers: { "X-Study-Terminal": "1" } });
    const d = await r.json();
    if (!r.ok) { setErr(d.detail || "Could not analyze that image."); return; }
    setUploaded(d);
  };
  const QUICK = ["Should I buy this right now?", "Am I entering too late?", "Is this a fake breakout?", "Where should my stop loss be?",
    "What would invalidate this trade?", "Is there a better opportunity?", "What am I missing?", "Explain the current market conditions."];
  return (
    <div className="page">
      <div className="cols c-side">
        <div className="stack">
          <Panel title="Screen monitoring" sub={s?.state === "running" ? "capturing" : s?.state || "off"}
            right={<span className={`live-dot ${s?.state === "running" ? "rec" : ""}`} aria-hidden />}>
            {s?.state === "running" || s?.state === "paused" ? (
              <div className="stack">
                <div className="note">{s.reason}</div>
                <div className="small muted">Capture method: {s.capture_method || "starting"}. Frames seen {s.frames_seen}, analyzed {s.frames_analyzed}.</div>
                <div className="row">{s.state === "running" ? <button onClick={() => ctl("pause")}>Pause</button> : <button onClick={() => ctl("resume")}>Resume</button>}
                  <button className="danger" onClick={() => ctl("stop")}>Stop</button></div>
              </div>
            ) : (
              <div className="stack">
                <p className="small muted">Pick the trading window to watch. Only that window is captured, frames are never saved, and login screens are skipped.</p>
                <select aria-label="Window to watch" value={sel ? `${sel.kind}:${sel.id}` : ""} onChange={(e) => setSel((targets.data?.targets || []).find((t: any) => `${t.kind}:${t.id}` === e.target.value))}>
                  <option value="">Choose a window or screen…</option>
                  {(targets.data?.targets || []).map((t: any) => <option key={`${t.kind}:${t.id}`} value={`${t.kind}:${t.id}`}>{t.kind === "monitor" ? "Whole screen: " : ""}{t.title}{t.process ? ` (${t.process})` : ""}</option>)}
                </select>
                {targets.data && !targets.data.window_capture_supported && <div className="note warn">Window capture needs Windows. You can still analyze a screenshot below.</div>}
                <label className="check"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />I allow Study Terminal to capture this window while monitoring is on.</label>
                <div className="row"><button className="primary" disabled={!sel || !consent} onClick={start}>Start watching</button>
                  <button onClick={() => targets.reload()}>Refresh list</button></div>
                {err && <div className="note bad">{err}</div>}
              </div>)}
            <label className="f" style={{ marginTop: 10 }}>Platform<select value={plats.data?.selected || "auto"} onChange={(e) => setPlatform(e.target.value)} aria-label="Platform">
              {(plats.data?.platforms || []).map((p: any) => <option key={p.id} value={p.id}>{p.name}{p.asset_class === "futures" ? " (futures)" : ""}</option>)}</select></label>
            <h3>Analyze a screenshot</h3>
            <input type="file" accept="image/*" aria-label="Screenshot" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          </Panel>
          <CalibrationPanel />
          <Panel title="What I see" sub={obs ? `${obs.platform}${obs.asset_class === "futures" ? " · futures" : ""}${obs.platform_source ? ` (${obs.platform_source})` : ""}` : ""}>
            {!obs ? <div className="muted">Nothing analyzed yet.</div> : obs.blocked ? <div className="note bad">{obs.reason}</div> : (
              <table><tbody>
                <tr><td className="muted">Ticker</td><td>{obs.ticker ?? "not readable"} <span className="faint small">{obs.ticker_source}</span></td></tr>
                <tr><td className="muted">Timeframe</td><td>{obs.timeframe ?? "not readable"} {obs.timeframe_note && <span className="faint small">{obs.timeframe_note}</span>}</td></tr>
                <tr><td className="muted">Visible price</td><td className="num">{obs.visible_price != null ? (obs.asset_class === "futures" ? obs.visible_price : money(obs.visible_price)) : "not readable"}</td></tr>
                {obs.futures && <tr><td className="muted">Futures contract</td><td>{obs.futures.contract || `${obs.futures.root} (no month shown)`} {obs.futures.note && <span className="faint small">{obs.futures.note}</span>}</td></tr>}
                <tr><td className="muted">Indicators on screen</td><td>{obs.indicators_visible.join(", ") || "none read"}</td></tr>
                <tr><td className="muted">Your drawn lines</td><td>{obs.drawn_levels.map((d: any) => money(d.price_estimate)).join(", ") || "none"}</td></tr>
                <tr><td className="muted">Last candles</td><td>{obs.recent_candles.join(", ") || "—"}</td></tr>
                {obs.position_on_screen && <tr><td className="muted">Position (unverified)</td><td>{JSON.stringify(obs.position_on_screen)}</td></tr>}
              </tbody></table>)}
            {obs?.could_not_recognize?.length > 0 && <div className="note warn small">Couldn't read: {obs.could_not_recognize.join(", ")}. I won't guess these.</div>}
            {obs && <p className="small faint" style={{ marginTop: 8 }}>{obs.note}</p>}
          </Panel>
        </div>
        <div className="stack">
          <Panel title="Screen + market data" sub={fu?.ticker || ""} right={fu?.action && <Action a={fu.action} />}>
            {!fu ? <div className="muted">Start screen monitoring or analyze a screenshot.</div> : (
              <div className="stack">
                {fu.status && <div className="note warn">{fu.status}</div>}
                {fu.discrepancy && <div className="note bad">{fu.discrepancy}</div>}
                {fu.stale_screen && <div className="note warn">{fu.stale_screen}</div>}
                {fu.market_price != null && <div className="row"><span>Market data {fu.asset_class === "futures" ? fu.market_price : money(fu.market_price)}</span><Meter withText status={fu.market_label?.status} reason={fu.market_label?.reason} /> <QuoteStamp label={fu.market_label} />
                  {fu.visible_price != null && <span className="muted">screen {fu.asset_class === "futures" ? fu.visible_price : money(fu.visible_price)} ({pct(fu.price_diff_pct)}{fu.price_diff_ticks != null ? `, ${fu.price_diff_ticks} ticks` : ""})</span>}</div>}
                {fu.asset_class === "futures" ? <>
                  {fu.checks?.map((c: any, i: number) => <div key={i} className={`small ${c.ok ? "" : "down"}`}>{c.ok ? "✓" : "✗"} {c.check}: {c.detail}</div>)}
                  {fu.reasons && <div className="muted small">{fu.reasons.join(" ")}</div>}
                  {fu.best_signal && <FuturesPlan s={fu.best_signal} />}
                  {fu.developing?.length > 0 && <div className="small muted">{fu.developing.join(" ")}</div>}
                  {fu.position_on_screen && <div className="small faint">Position on screen (unverified): {JSON.stringify(fu.position_on_screen)}</div>}
                  {fu.contract && <a href={`#/futures/${fu.contract}`} className="small">Open the futures dashboard for {fu.contract}</a>}
                  <div className="small faint">{fu.sim_only_note}</div>
                </> : fu.best_signal ? <SignalCard s={fu.best_signal} onTrade={() => (location.hash = `#/chart/${fu.ticker}`)} /> :
                  fu.reasons && <div className="muted">{fu.reasons.join(" ")}</div>}
                {fu.your_drawn_levels?.length > 0 && <div className="small">{fu.your_drawn_levels.map((d: any, i: number) => <div key={i}>Your line near {money(d.price_estimate)}{d.nearest_known_level ? ` sits by ${d.nearest_known_level}` : ""}.</div>)}</div>}
              </div>)}
            {s?.ai_explanation && <div className="note"><b>AI read of the chart.</b><div className="msg">{s.ai_explanation.answer}</div></div>}
          </Panel>
          <Panel title="Ask the mentor" sub={ai.data?.engine}>
            <form className="row" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
              <input style={{ flex: 1, minWidth: 200 }} placeholder={fu?.ticker ? `Ask about ${fu.ticker}…` : "Ask about the chart on screen, or name a symbol…"} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Question" />
              <button className="primary" disabled={asking}>{asking ? "Thinking…" : "Ask"}</button>
            </form>
            <div className="row" style={{ marginTop: 8 }}>{QUICK.map((x) => <button key={x} className="ghost small" onClick={() => ask(x)}>{x}</button>)}</div>
            <div className="chat" style={{ marginTop: 12 }}>
              {chat.map((c, i) => <div key={i}><div className="msg q">{c.q}</div><div className="msg a">{c.a.answer}</div><div className="small faint">{c.a.engine}{c.a.context_symbol ? `, about ${c.a.context_symbol}` : ""}</div></div>)}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

// ======================= Scanner =======================
export function Scanner() {
  const scan = usePoll("/scanner", 30000);
  const [running, setRunning] = useState(false);
  const [f, setF] = useState<any>(null);
  useEffect(() => { if (scan.data && !f) setF(scan.data.filters); }, [scan.data, f]);
  const run = async () => {
    setRunning(true);
    try { scan.setData(await api("/scanner/run", { method: "POST", json: f })); } finally { setRunning(false); }
  };
  const fld = (k: string, label: string, step = "any") => (
    <label className="f">{label}<input type="number" step={step} value={f?.[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value === "" ? null : Number(e.target.value) })} /></label>);
  const d = scan.data;
  return (
    <div className="page">
      <Panel title="Scanner filters" sub="watchlists plus Yahoo market-wide lists" right={<button className="primary" onClick={run} disabled={running || !f}>{running ? "Scanning…" : "Run scan now"}</button>}>
        {f && <div className="stack">
          <div className="form">
            {fld("min_price", "Min price ($)")}{fld("max_price", "Max price ($)")}{fld("abs_change_min", "Min move (abs %)")}
            {fld("min_avg_volume", "Min avg volume")}{fld("min_dollar_volume", "Min dollar volume")}{fld("min_market_cap", "Min market cap")}
            {fld("min_rvol", "Min relative volume")}{fld("min_atr_pct", "Min volatility (ATR %)")}{fld("max_atr_pct", "Max volatility (ATR %)")}
            {fld("min_setup_quality", "Min setup quality", "1")}{fld("deep_scan_limit", "Symbols to analyze", "1")}
            <label className="f">Timeframe<select value={f.timeframe} onChange={(e) => setF({ ...f, timeframe: e.target.value })}>{TIMEFRAMES.map((t) => <option key={t}>{t}</option>)}</select></label>
          </div>
          <div className="row">{["watchlist", "day_gainers", "day_losers", "most_actives", "small_cap_gainers", "aggressive_small_caps"].map((s) =>
            <label key={s} className="check"><input type="checkbox" checked={f.sources.includes(s)} onChange={(e) => setF({ ...f, sources: e.target.checked ? [...f.sources, s] : f.sources.filter((x: string) => x !== s) })} />{s.replace(/_/g, " ")}</label>)}
            <label className="check"><input type="checkbox" checked={f.premarket_active} onChange={(e) => setF({ ...f, premarket_active: e.target.checked })} />Premarket mover (2%+)</label></div>
        </div>}
      </Panel>
      {d?.errors?.length > 0 && <div className="note warn">{d.errors.join(" ")}</div>}
      <Panel title="Ranked opportunities" sub={d?.last_run ? `${d.results.length} results, ${etTime(d.last_run)} ET` : "not run yet"} flush>
        {!d?.results?.length ? <div className="empty">No results yet. Run a scan. Outside market hours there's often little to rank, and that's expected.</div> :
          <table><thead><tr><th>Symbol</th><th className="r">Price</th><th className="r">Change</th><th className="r">RVOL</th><th className="r">ATR %</th><th>Bias</th><th>Signal</th><th className="r">Score</th><th>Why it ranks here</th></tr></thead>
            <tbody>{d.results.map((r: any) => (
              <tr key={r.symbol} className="click" onClick={() => (location.hash = `#/chart/${r.symbol}`)}>
                <td className="sym">{r.symbol}</td><td className="r">{num(r.price)}</td><td className={`r ${sign(r.change_pct)}`}>{pct(r.change_pct, 1)}</td>
                <td className="r">{num(r.rvol, 1)}</td><td className="r">{num(r.atr_pct)}</td><td>{r.bias}</td>
                <td>{r.best_signal ? <span className="row"><Action a={r.action} /><span className="small muted">{r.best_signal.setup_name}</span></span> :
                  r.watch_signal ? <span className="row" title="Watch only: no reliable out-of-sample edge"><Action a={r.watch_signal.action} /><span className="small muted">{r.watch_signal.setup_name}, watch</span></span> :
                  <span className="faint">no setup</span>}{r.catalyst && <div className="small" title={(r.catalyst.headlines || []).map((h: any) => h.headline).join("\n")}>Catalyst: {r.catalyst.text}</div>}</td>
                <td className="r">{r.rank_score}</td>
                <td className="small muted">{Object.entries(r.rank_components).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(", ")}</td></tr>))}
            </tbody></table>}
      </Panel>
      {d?.rejected?.length > 0 && <Panel title="Filtered out" sub={`${d.rejected.length}`} flush>
        <details style={{ padding: "4px 12px" }}><summary>Show why each symbol was excluded</summary>
          <table><tbody>{d.rejected.map((r: any, i: number) => <tr key={i}><td className="sym">{r.symbol}</td><td className="muted">{r.rejected_because}</td></tr>)}</tbody></table>
        </details></Panel>}
      <p className="small muted">{d?.note}</p>
    </div>
  );
}

// ======================= Paper trading =======================
export function Paper() {
  const L = useLive();
  const acct = usePoll("/paper/account", 10000, [L.paper]);
  const pos = usePoll("/paper/positions", 8000, [L.paper]);
  const orders = usePoll("/paper/orders?limit=100", 8000, [L.paper]);
  const fills = usePoll("/paper/fills?limit=100", 15000, [L.paper]);
  const sigs = usePoll("/signals", 20000);
  const [sym, setSym] = useState("SPY");
  const a = acct.data;
  const cancel = async (id: string) => { await api(`/paper/orders/${id}`, { method: "DELETE" }); orders.reload(); };
  const close = async (s: string) => {
    if (!confirm(`Close your ${s} paper position at market?`)) return;
    try { await api(`/paper/positions/${s}/close?confirm=true`, { method: "POST" }); } catch (e: any) { alert(e.message); }
    pos.reload(); orders.reload();
  };
  const reset = async () => {
    const cash = prompt("Reset the practice account? All positions, orders and history will be erased. Starting cash:", "25000");
    if (!cash) return;
    await api("/paper/reset", { method: "POST", json: { confirm: true, starting_cash: Number(cash) } });
    acct.reload(); pos.reload(); orders.reload(); fills.reload();
  };
  return (
    <div className="page">
      {a && <section className="panel"><div className="strip" style={{ borderBottom: 0 }}>
        {[["Equity", money(a.equity)], ["Cash", money(a.cash)], ["Buying power", money(a.buying_power)], ["Exposure", `${a.exposure_pct ?? 0}%`],
          ["Unrealized", money(a.unrealized_pnl)], ["Realized", money(a.realized_pnl)], ["Day P&L", money(a.day_pnl)], ["Week P&L", money(a.week_pnl)],
          ["Total P&L", money(a.total_pnl)], ["Commissions", money(a.commissions)], ["Losses in a row", `${a.consecutive_losses_today} of ${a.max_consecutive_losses}`]]
          .map(([k, v]) => <div key={k} className="cell" style={{ padding: "8px 14px" }}><span className="k">{k}</span><span className="v">{v}</span></div>)}
        <div className="cell grow" /><div className="cell"><button className="ghost" onClick={reset}>Reset account</button></div>
      </div></section>}
      {a?.daily_loss_limit_hit && <div className="note bad">Daily loss limit reached ({money(a.day_pnl)}). New entries are blocked until tomorrow.</div>}
      <div className="cols c-chart">
        <div className="stack">
          <Panel title="Open positions" flush>
            {!pos.data?.length ? <div className="empty">No open positions. Use the ticket to place a practice trade.</div> :
              <table><thead><tr><th>Symbol</th><th>Side</th><th className="r">Qty</th><th className="r">Avg</th><th className="r">Mark</th><th>Data</th><th className="r">Unrealized</th><th className="r">Stop</th><th className="r">Target</th><th>Advice</th><th /></tr></thead>
                <tbody>{pos.data.map((p: any) => {
                  const adv = sigs.data?.positions?.[p.symbol];
                  return (<tr key={p.symbol}>
                    <td className="sym"><a href={`#/chart/${p.symbol}`}>{p.symbol}</a></td><td>{p.side}</td><td className="r">{Math.abs(p.qty)}</td>
                    <td className="r">{num(p.avg_price)}</td><td className="r">{num(p.mark)}</td><td><Meter status={p.mark_label?.status} reason={p.mark_label?.reason} /> <QuoteStamp compact label={p.mark_label} /></td>
                    <td className={`r ${sign(p.unrealized_pnl)}`}>{money(p.unrealized_pnl)}</td><td className="r">{num(p.stop_loss)}</td><td className="r">{num(p.take_profit)}</td>
                    <td title={adv?.reasons?.join(" ")}>{adv ? <Action a={adv.action} /> : <span className="faint small">—</span>}</td>
                    <td><button className="ghost" onClick={() => close(p.symbol)}>Close</button></td></tr>);
                })}</tbody></table>}
          </Panel>
          <Panel title="Orders" flush>
            {!orders.data?.length ? <div className="empty">No orders yet.</div> :
              <table><thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Type</th><th>Role</th><th className="r">Qty</th><th className="r">Price</th><th>Status</th><th /></tr></thead>
                <tbody>{orders.data.map((o: any) => (
                  <tr key={o.id}><td>{etTime(o.created_at)}</td><td className="sym">{o.symbol}</td><td>{o.side}</td><td>{o.type.replace("_", " ")}</td><td className="muted">{o.role.replace("_", " ")}</td>
                    <td className="r">{o.qty}</td><td className="r">{o.fill_price ? num(o.fill_price) : num(o.limit_price ?? o.stop_price)}</td>
                    <td title={o.reject_reason || ""} className={o.status === "rejected" ? "down" : o.status === "filled" ? "up" : ""}>{o.status}</td>
                    <td>{o.status === "open" && <button className="ghost" onClick={() => cancel(o.id)}>Cancel</button>}</td></tr>))}</tbody></table>}
          </Panel>
          <Panel title="Fills" flush>
            {!fills.data?.length ? <div className="empty">No fills yet.</div> :
              <table><thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th className="r">Qty</th><th className="r">Price</th><th className="r">Slippage</th><th className="r">Realized</th><th>Price basis</th></tr></thead>
                <tbody>{fills.data.map((f: any) => (<tr key={f.id}><td>{etTime(f.ts)}</td><td className="sym">{f.symbol}</td><td>{f.side}</td><td className="r">{f.qty}</td><td className="r">{num(f.price)}</td>
                  <td className="r">{money(f.slippage_cost)}</td><td className={`r ${sign(f.realized_pnl)}`}>{f.role === "entry" ? "—" : money(f.realized_pnl)}</td><td className="muted">{f.price_basis}</td></tr>))}</tbody></table>}
          </Panel>
        </div>
        <div className="stack">
          <Panel title="Order ticket" right={<input aria-label="Ticket symbol" value={sym} onChange={(e) => setSym(e.target.value.toUpperCase())} style={{ width: 90 }} />}>
            <OrderTicket symbol={sym} onDone={() => { orders.reload(); pos.reload(); }} />
          </Panel>
          <SizeCalc />
        </div>
      </div>
    </div>
  );
}

function SizeCalc() {
  const [e, setE] = useState(""), [s, setS] = useState("");
  const [r, setR] = useState<any>(null);
  useEffect(() => {
    if (!e || !s) { setR(null); return; }
    api(`/paper/size?entry=${e}&stop=${s}`).then(setR).catch(() => setR(null));
  }, [e, s]);
  return (
    <Panel title="Position size calculator">
      <div className="form"><label className="f">Entry<input type="number" step="0.01" value={e} onChange={(x) => setE(x.target.value)} /></label>
        <label className="f">Stop<input type="number" step="0.01" value={s} onChange={(x) => setS(x.target.value)} /></label></div>
      {r && <p style={{ marginTop: 10 }}>Risking {money(r.risk_dollars)} ({r.risk_pct}% of {money(r.equity, 0)}) with {money(r.risk_per_share)} per share at risk: <b>{r.shares} shares</b> ({money(r.notional, 0)} of stock).</p>}
    </Panel>
  );
}


function CalibrationPanel() {
  const cal = usePoll("/screen/calibration", 0);
  const profs = usePoll("/visual/profiles", 0);
  const [f, setF] = useState<any>({ ticker: "", timeframe: "", price: "", tolerance_ticks: 2, platform: "topstepx", synthetic: false, keep_image: false, keep_result: true,
    profile_id: "", last_open: "", last_high: "", last_low: "", last_close: "", vwap: "", ema9: "", ema20: "", ema50: "", ema200: "" });
  const [file, setFile] = useState<File | null>(null);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const submit = async () => {
    if (!file) return;
    setErr(null);
    const fd = new FormData();
    fd.append("file", file);
    Object.entries(f).forEach(([k, v]) => fd.append(k, String(v)));
    const r = await fetch("/api/screen/calibration/sample", { method: "POST", body: fd, headers: { "X-Study-Terminal": "1" } });
    const d = await r.json();
    if (!r.ok) { setErr(d.detail || "Could not score that image."); return; }
    setRes(d); cal.reload();
  };
  const del = async (id: string) => { await api(`/screen/calibration/${id}`, { method: "DELETE" }); cal.reload(); };
  const rescore = async () => { await api("/screen/calibration/rescore", { method: "POST" }); cal.reload(); };
  const rep = cal.data?.report;
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  return (
    <Panel title="Calibrate screen reading" sub={rep ? `${rep.real_samples} real sample(s)` : ""}
      right={<button onClick={() => setOpen(!open)}>{open ? "Hide" : "Open"}</button>}>
      {!open ? <p className="small muted">Measure how well the copilot reads your own charts: upload a screenshot and type what's really on it.</p> : <div className="stack">
        <p className="small muted">The screenshot is analyzed in memory and dropped unless you tick "keep". Only the labels you type and the scores are saved,
          so the report can add up. Don't upload screens showing passwords or account numbers; login screens are refused.</p>
        <input type="file" accept="image/*" aria-label="Calibration screenshot" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        <div className="row">
          <label className="f">Contract / ticker<input value={f.ticker} onChange={set("ticker")} placeholder="MNQZ26" /></label>
          <label className="f">Timeframe<input value={f.timeframe} onChange={set("timeframe")} placeholder="5m" /></label>
          <label className="f">Last price<input value={f.price} onChange={set("price")} placeholder="21012.25" /></label>
          <label className="f">Tolerance (ticks)<input type="number" min={0} value={f.tolerance_ticks} onChange={set("tolerance_ticks")} /></label>
          <label className="f">Platform<select value={f.platform} onChange={set("platform")}><option value="topstepx">TopstepX</option>
            <option value="tradingview">TradingView</option><option value="generic">Other</option><option value="auto">Detect</option></select></label>
        </div>
        <label className="f small">Read it with Live Visual Monitor profile (needed for the Trust &amp; Validation dashboard)
          <select value={f.profile_id} onChange={set("profile_id")}><option value="">— screen copilot reader —</option>
            {(profs.data?.profiles || []).map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        {f.profile_id && <>
          <div className="small muted">Last COMPLETED candle (the one left of the forming candle), as TopstepX shows it when you hover it:</div>
          <div className="row">{["open", "high", "low", "close"].map((k) => <label key={k} className="f">{k}<input value={f[`last_${k}`]} onChange={set(`last_${k}`)} style={{ width: 100 }} /></label>)}</div>
          <div className="small muted">Indicator values on the newest candle (only lines whose colors your profile assigns):</div>
          <div className="row">{[["vwap", "VWAP"], ["ema9", "EMA 9"], ["ema20", "EMA 20"], ["ema50", "EMA 50"], ["ema200", "EMA 200"]].map(([k, l]) =>
            <label key={k} className="f">{l}<input value={f[k]} onChange={set(k)} style={{ width: 100 }} /></label>)}</div>
        </>}
        <label className="check"><input type="checkbox" checked={f.keep_image} onChange={set("keep_image")} />Keep this screenshot on this computer (lets me re-score it after updates)</label>
        <label className="check"><input type="checkbox" checked={f.keep_result} onChange={set("keep_result")} />Count it in the accuracy report</label>
        <label className="check"><input type="checkbox" checked={f.synthetic} onChange={set("synthetic")} />This is a generated test chart (scored, but never counted as accuracy)</label>
        <div className="row"><button className="primary" disabled={!file} onClick={submit}>Score it</button>
          <button onClick={rescore} disabled={!rep?.images_kept}>Re-score kept screenshots</button></div>
        {err && <div className="note bad">{err}</div>}
        {res && (res.result?.blocked ? <div className="note bad">{res.result.reason}</div> :
          <table><tbody>{Object.entries(res.result || {}).map(([k, v]: any) => <tr key={k}><td className="muted">{k.replace("_", " ")}</td>
            <td className={v.ok ? "pos" : "neg"}>{v.ok ? "correct" : "wrong"}</td>
            <td className="small">read {v.read == null ? "nothing" : typeof v.read === "object" ? `${v.read.points} axis labels` : String(v.read)}{v.truth != null ? `, actual ${v.truth}` : ""}</td></tr>)}</tbody></table>)}
        {rep && <>
          <h3>Accuracy by platform</h3>
          {!Object.keys(rep.platforms).length ? <div className="muted small">No real samples yet.</div> :
            Object.entries(rep.platforms).map(([p, fields]: any) => <div key={p}><b>{p}</b>
              <table><thead><tr><th>Field</th><th>Samples</th><th>Accuracy</th><th>95% range</th><th></th></tr></thead><tbody>
                {Object.entries(fields).filter(([, c]: any) => c.samples).map(([k, c]: any) => <tr key={k}><td>{k.replace("_", " ")}</td><td>{c.samples}</td>
                  <td>{c.accuracy_pct}%</td><td className="small">{c.ci95 ? `${c.ci95[0]}–${c.ci95[1]}%` : "-"}</td>
                  <td className="small faint">{c.note || (k === "ticker" && c.avg_confidence_when_wrong != null ? `confidence when wrong ${c.avg_confidence_when_wrong}` : "")}</td></tr>)}
              </tbody></table></div>)}
          <div className="small faint">{rep.synthetic_note} {rep.synthetic_samples} synthetic sample(s) excluded. {rep.images_kept} screenshot(s) kept.</div>
          {(cal.data?.samples || []).length > 0 && <details><summary className="small">Samples and failures</summary>
            <table><tbody>{cal.data.samples.slice(0, 50).map((r: any) => <tr key={r.id}><td className="small">{r.at.slice(0, 16).replace("T", " ")}</td>
              <td className="small">{r.platform}{r.synthetic ? " (synthetic)" : ""}</td>
              <td className="small">{Object.entries(r.result || {}).filter(([, v]: any) => !v.ok).map(([k]) => k).join(", ") || "all correct"}</td>
              <td className="small">{r.image_kept ? <a href={`/api/screen/calibration/${r.id}/image`} target="_blank" rel="noreferrer">image</a> : "no image"}</td>
              <td><button className="small" onClick={() => del(r.id)}>Delete</button></td></tr>)}</tbody></table>
            <button className="danger small" onClick={() => del("all")}>Delete all calibration data</button></details>}
        </>}
      </div>}
    </Panel>
  );
}

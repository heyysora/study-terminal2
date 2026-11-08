import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries, ColorType, HistogramSeries, IChartApi, ISeriesApi, LineSeries, LineStyle, createChart,
} from "lightweight-charts";
import { SOURCE_TEXT, STATUS_LEVEL, STATUS_TEXT, actionClass, ago, api, etDate, etTimeSec, money, num, pct } from "./lib";

/** Signal meter: how live the data is. 5 = real-time ... 0 = unavailable. */
export function Meter({ status, big, withText, reason }: { status?: string; big?: boolean; withText?: boolean; reason?: string }) {
  const lvl = status ? STATUS_LEVEL[status] ?? 0 : 0;
  const text = status ? STATUS_TEXT[status] || status : "No data";
  return (
    <span className="row" style={{ gap: 6, display: "inline-flex" }} title={reason || text}>
      <span className={`meter l${lvl}${big ? " big" : ""}`} aria-label={`Data: ${text}`}><i /><i /><i /><i /><i /></span>
      {withText && <span className="small muted">{text}</span>}
    </span>
  );
}

/** Where a quote came from and when: "Yahoo stream, 14:32:05 ET, 3s ago". Shown next to live prices. */
export function QuoteStamp({ label, compact }: { label?: any; compact?: boolean }) {
  if (!label) return <span className="stamp">No quote yet</span>;
  const src = SOURCE_TEXT[label.source] || label.source || label.provider;
  const t = label.data_time ? etTimeSec(label.data_time) : null;
  if (compact) return <span className="stamp" title={`${src}. ${label.reason}`}>{t ?? "—"}</span>;
  return (
    <span className="stamp" title={label.reason}>
      {src}{t && <>, price time {t} ET</>}{label.age_seconds != null && <>, {ago(label.age_seconds)} old</>}
    </span>
  );
}

/** Provenance of a chart's bars: source, fetch time, newest closed bar, validation result. */
export function ChartStamp({ data }: { data?: any }) {
  if (!data) return null;
  const q = data.quality;
  const bad = data.status === "cached" || (q && !q.ok);
  return (
    <div className={`stamp-row${bad ? " warn" : ""}`}>
      <span><span className="k">Bars</span> {SOURCE_TEXT[data.source] || data.source || data.provider}</span>
      <span><span className="k">Status</span> {STATUS_TEXT[data.status] || data.status}</span>
      {data.fetched_at && <span><span className="k">Fetched</span> {etTimeSec(data.fetched_at)} ET ({ago(data.fetched_age_seconds)} ago)</span>}
      {data.last_closed_bar && <span><span className="k">Newest closed bar</span> {etDate(data.last_closed_bar)} {etTimeSec(data.last_closed_bar).slice(0, 5)} ET</span>}
      <span><span className="k">Checks</span> {q ? q.summary : "not run"}</span>
      {data.status === "cached" && <span className="down">{data.reason}</span>}
    </div>
  );
}

export function Action({ a }: { a?: string }) {
  return <span className={actionClass(a)}>{a || "NO TRADE"}</span>;
}

export function Panel({ title, sub, right, children, flush }: { title: string; sub?: React.ReactNode; right?: React.ReactNode; children: React.ReactNode; flush?: boolean }) {
  return (
    <section className="panel">
      <header><div className="row" style={{ alignItems: "baseline" }}><h2>{title}</h2>{sub && <span className="sub">{sub}</span>}</div>{right}</header>
      <div className={flush ? "body flush" : "body"}>{children}</div>
    </section>
  );
}

const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const etTick = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false });
const etDayFmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" });

export type Overlay = { name: string; data: { time: number; value: number }[]; color: string; width?: number };
export type PriceLine = { price: number; title: string; color: string; dashed?: boolean };

/** Candles + volume + overlays + horizontal price lines, with times shown in New York time. */
export function CandleChart({ bars, overlays = [], lines = [], height, daily }: {
  bars: any[]; overlays?: Overlay[]; lines?: PriceLine[]; height?: number; daily?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<{ c?: ISeriesApi<"Candlestick">; v?: ISeriesApi<"Histogram">; o: ISeriesApi<"Line">[] }>({ o: [] });
  useEffect(() => {
    if (!box.current) return;
    const ch = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: css("--panel") }, textColor: css("--muted"), fontFamily: css("--data"), fontSize: 12 },
      grid: { vertLines: { color: "#1c232e" }, horzLines: { color: "#1c232e" } },
      rightPriceScale: { borderColor: css("--rule") },
      timeScale: { borderColor: css("--rule"), timeVisible: !daily, secondsVisible: false,
        tickMarkFormatter: (t: number) => (daily ? etDayFmt.format(new Date(t * 1000)) : etTick.format(new Date(t * 1000))) },
      localization: { timeFormatter: (t: number) => `${etDayFmt.format(new Date(t * 1000))} ${etTick.format(new Date(t * 1000))} ET` },
      crosshair: { mode: 1 },
    });
    chart.current = ch;
    return () => { ch.remove(); chart.current = null; series.current = { o: [] }; };
  }, [daily]);
  useEffect(() => {
    const ch = chart.current;
    if (!ch) return;
    const s = series.current;
    if (s.c) ch.removeSeries(s.c);
    if (s.v) ch.removeSeries(s.v);
    s.o.forEach((x) => ch.removeSeries(x));
    const up = css("--up"), down = css("--down");
    const c = ch.addSeries(CandlestickSeries, { upColor: up, downColor: down, borderVisible: false, wickUpColor: up, wickDownColor: down });
    c.setData(bars.map((b) => ({ time: b.time as any, open: b.open, high: b.high, low: b.low, close: b.close })));
    const v = ch.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
    v.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    v.setData(bars.map((b) => ({ time: b.time as any, value: b.volume, color: b.close >= b.open ? "rgba(63,182,139,.35)" : "rgba(229,83,75,.35)" })));
    s.c = c; s.v = v; s.o = [];
    for (const ov of overlays) {
      const l = ch.addSeries(LineSeries, { color: ov.color, lineWidth: (ov.width || 1) as any, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
      l.setData(ov.data.map((p) => ({ time: p.time as any, value: p.value })));
      s.o.push(l);
    }
    for (const ln of lines) {
      c.createPriceLine({ price: ln.price, color: ln.color, lineWidth: 1, lineStyle: ln.dashed ? LineStyle.Dashed : LineStyle.Solid, axisLabelVisible: true, title: ln.title });
    }
    ch.timeScale().fitContent();
  }, [bars, overlays, lines]);
  return (
    <div className={`chart-box${height && height < 400 ? " small" : ""}`} style={height ? { height } : undefined} ref={box}>
      {overlays.length > 0 && <div className="chart-legend">{overlays.map((o) => <span key={o.name} style={{ color: o.color }}>{o.name}</span>)}</div>}
    </div>
  );
}

export function LineChart({ points, height = 220, color }: { points: [string, number][]; height?: number; color?: string }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!box.current || !points.length) return;
    const ch = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: css("--panel") }, textColor: css("--muted"), fontFamily: css("--data") },
      grid: { vertLines: { visible: false }, horzLines: { color: "#1c232e" } },
      rightPriceScale: { borderColor: css("--rule") }, timeScale: { borderColor: css("--rule") },
    });
    const l = ch.addSeries(LineSeries, { color: color || css("--brass"), lineWidth: 2 });
    const seen = new Set<number>();
    const data = points.map(([t, v]) => ({ time: Math.floor(new Date(t).getTime() / 1000), value: v }))
      .filter((p) => (seen.has(p.time) ? false : (seen.add(p.time), true)));
    l.setData(data as any);
    ch.timeScale().fitContent();
    return () => ch.remove();
  }, [points, color]);
  return <div style={{ height }} ref={box} />;
}

/** Full signal: plan, confidence (three kinds, kept separate), risks, and the beginner explanation. */
export function SignalCard({ s, onTrade }: { s: any; onTrade?: (s: any) => void }) {
  const q = s.confidence.setup_quality;
  const hist = s.confidence.historical;
  const model = s.confidence.model_probability;
  return (
    <div className="stack">
      <div className="spread">
        <div className="row"><Action a={s.action} /><b>{s.setup_name}</b><span className="muted small">{s.timeframe}, {s.direction}</span></div>
        <span className="small muted">{s.state}</span>
      </div>
      <p className="small muted" style={{ margin: 0 }}>{s.state_reason}</p>
      <div className="levels">
        <div><div className="k">Entry range</div><div className="v">{num(s.entry_range[0])}–{num(s.entry_range[1])}</div></div>
        <div><div className="k">Stop</div><div className="v down">{num(s.stop)}</div></div>
        <div><div className="k">Targets</div><div className="v up">{num(s.targets.t1)} / {num(s.targets.t2)}</div></div>
        <div><div className="k">Size</div><div className="v">{s.position_size.shares} sh</div></div>
      </div>
      <div className="small muted">Risk {money(s.position_size.risk_dollars)} ({s.position_size.risk_pct}% of {money(s.position_size.equity, 0)}), reward:risk {s.reward_risk}:1, third target {num(s.targets.t3)}, invalidation {num(s.invalidation)}</div>
      <div>
        <div className="spread small"><span>Setup quality {q.score}/100</span><span className="faint">a checklist, not a win probability</span></div>
        <div className="qbar"><i style={{ width: `${q.score}%` }} /></div>
      </div>
      <div className="small">
        <div><span className="muted">Out-of-sample history: </span>{hist.available ? hist.note : hist.note}</div>
        <div><span className="muted">Model estimate: </span>{model && model.probability_of_profit !== undefined ? `${Math.round(model.probability_of_profit * 100)}% chance of profit (model ${model.model_version})` : (model?.note || "No model deployed.")}</div>
        <div className="faint">{s.confidence.certainty}</div>
      </div>
      {s.risks.length > 0 && <div className="note warn">{s.risks.map((r: string, i: number) => <div key={i}>{r}</div>)}</div>}
      <div className="note"><b>Confirmation needed.</b> {s.confirmation}</div>
      <details>
        <summary>Why this setup exists</summary>
        <p>{s.education.what} {s.education.why}</p>
        <p className="muted">{s.education.money}</p>
        <p><b>How it fails.</b> {s.education.how_it_fails}</p>
        <p className="small muted">{Object.values(s.education.terms).join(" ")}</p>
      </details>
      <details>
        <summary>Evidence ({s.supporting_indicators.length} supporting factors, {q.checks.filter((c: any) => c.passed).length}/{q.checks.length} checks)</summary>
        <ul className="checks">{q.checks.map((c: any) => <li key={c.check} className={c.passed ? "" : "no"}><span className="m">{c.passed ? "✓" : "–"}</span><span>{c.check} <span className="faint">{c.detail}</span></span></li>)}</ul>
        {s.supporting_indicators.map((f: any) => <p key={f.factor} className="small"><b>{f.factor}.</b> {f.why}</p>)}
        <p className="small muted">Volume: RVOL {num(s.volume.rvol)}x, signal bar {num(s.volume.signal_bar_vol_ratio)}x average. Market: SPY {s.market.bias}{s.market.spy_change_pct !== null ? `, ${pct(s.market.spy_change_pct)}` : ""}.</p>
      </details>
      {onTrade && s.action !== "NO TRADE" && <div className="row"><button onClick={() => onTrade(s)}>Load into paper order ticket</button></div>}
    </div>
  );
}

/** Paper order ticket: preview first, then an explicit confirm. */
export function OrderTicket({ symbol, prefill, onDone }: { symbol: string; prefill?: any; onDone?: () => void }) {
  const [f, setF] = useState<any>({ side: "buy", qty: 10, type: "limit", limit_price: "", stop_price: "", stop_loss: "", take_profit: "", tif: "day", extended_hours: false });
  const [pv, setPv] = useState<any>(null);
  const [msg, setMsg] = useState<{ kind: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!prefill) return;
    const long = prefill.direction === "long";
    setF((x: any) => ({ ...x, side: long ? "buy" : "sell", type: "stop", stop_price: prefill.trigger, limit_price: "",
      stop_loss: prefill.stop, take_profit: prefill.targets.t2, qty: prefill.position_size.shares || 1, tif: "day" }));
    setPv(null);
  }, [prefill]);
  useEffect(() => { setPv(null); setMsg(null); }, [symbol]);
  const body = () => {
    const n = (v: any) => (v === "" || v === null || v === undefined ? null : Number(v));
    return { symbol, side: f.side, qty: Number(f.qty), type: f.type, tif: f.tif, extended_hours: f.extended_hours,
      limit_price: ["limit", "stop_limit"].includes(f.type) ? n(f.limit_price) : null,
      stop_price: ["stop", "stop_limit"].includes(f.type) ? n(f.stop_price) : null,
      stop_loss: n(f.stop_loss), take_profit: n(f.take_profit) };
  };
  const preview = async () => {
    setBusy(true); setMsg(null);
    try { setPv(await api("/paper/orders/preview", { method: "POST", json: body() })); }
    catch (e: any) { setMsg({ kind: "bad", text: e.message }); }
    finally { setBusy(false); }
  };
  const place = async () => {
    setBusy(true);
    try {
      const r = await api("/paper/orders", { method: "POST", json: { ...body(), confirm: true } });
      setMsg({ kind: "", text: `Order ${r.order.status}${r.order.fill_price ? ` at ${money(r.order.fill_price)}` : ""}.` });
      setPv(null); onDone?.();
    } catch (e: any) { setMsg({ kind: "bad", text: e.message }); }
    finally { setBusy(false); }
  };
  const set = (k: string) => (e: any) => { setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }); setPv(null); };
  const p = pv?.preview;
  return (
    <div className="stack">
      <div className="row">
        <div className="seg">{["buy", "sell"].map((s) => <button key={s} className={f.side === s ? "on" : ""} onClick={() => { setF({ ...f, side: s }); setPv(null); }}>{s === "buy" ? "Buy" : "Sell / short"}</button>)}</div>
        <span className="sym">{symbol}</span>
      </div>
      <div className="form">
        <label className="f">Shares<input type="number" min={1} value={f.qty} onChange={set("qty")} /></label>
        <label className="f">Order type<select value={f.type} onChange={set("type")}><option value="market">Market</option><option value="limit">Limit</option><option value="stop">Stop (breakout entry)</option><option value="stop_limit">Stop limit</option></select></label>
        {["limit", "stop_limit"].includes(f.type) && <label className="f">Limit price<input type="number" step="0.01" value={f.limit_price} onChange={set("limit_price")} /></label>}
        {["stop", "stop_limit"].includes(f.type) && <label className="f">Trigger price<input type="number" step="0.01" value={f.stop_price} onChange={set("stop_price")} /></label>}
        <label className="f">Stop loss<input type="number" step="0.01" value={f.stop_loss} onChange={set("stop_loss")} /></label>
        <label className="f">Take profit<input type="number" step="0.01" value={f.take_profit} onChange={set("take_profit")} /></label>
        <label className="f">Time in force<select value={f.tif} onChange={set("tif")}><option value="day">Day</option><option value="gtc">Good till canceled</option></select></label>
      </div>
      {f.type === "limit" && <label className="check"><input type="checkbox" checked={f.extended_hours} onChange={set("extended_hours")} />Allow premarket / after-hours fills</label>}
      <div className="row"><button onClick={preview} disabled={busy}>Preview order</button>
        {p?.ok && <button className="primary" onClick={place} disabled={busy}>Place paper order</button>}</div>
      {p && (
        <div className="stack small">
          <div className="muted">Price used: {pv.price ? `${money(pv.price.price)} (${pv.price.status})` : "none available"} · est. fill {money(p.est_fill_price)} · notional {money(p.est_notional)} · buying power {money(p.buying_power)}</div>
          {p.risk_dollars !== null && <div>Risk {money(p.risk_dollars)} of {money(p.max_risk_dollars)} allowed{p.reward_risk ? `, reward:risk ${p.reward_risk}:1` : ""}{p.suggested_qty !== null ? `, suggested size ${p.suggested_qty} sh` : ""}</div>}
          {p.errors.map((e: string, i: number) => <div key={i} className="note bad">{e}</div>)}
          {p.warnings.map((e: string, i: number) => <div key={i} className="note warn">{e}</div>)}
          {p.ok && <div className="note">Paper order only - nothing goes to a broker. Review, then place it.</div>}
        </div>
      )}
      {msg && <div className={`note ${msg.kind}`}>{msg.text}</div>}
    </div>
  );
}

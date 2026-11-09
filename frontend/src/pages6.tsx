import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries, ColorType, HistogramSeries, LineSeries, LineStyle, createChart, createSeriesMarkers,
  type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type SeriesMarker, type Time,
} from "lightweight-charts";
import { Panel } from "./components";
import { STATUS_TEXT, api, ensureLive, etTimeSec, onLiveMessage } from "./lib";

const ROOTS = ["NQ", "MNQ", "ES", "MES"];
const TFS: [string, string, number][] = [["1Min", "1m", 60], ["5Min", "5m", 300], ["15Min", "15m", 900], ["30Min", "30m", 1800],
  ["1Hour", "1h", 3600], ["4Hour", "4h", 14400], ["1Day", "D", 86400]];
const EMA_COLORS: Record<string, string> = { "9": "#e8b04a", "20": "#5aa9e6", "50": "#b48ead", "200": "#e5e5e5" };
const LEVEL_STYLE: Record<string, [string, string, string]> = {          // key -> [toggle group, label, color]
  prev_day_high: ["pd", "PDH", "#9aa4b2"], prev_day_low: ["pd", "PDL", "#9aa4b2"],
  overnight_high: ["on", "ONH", "#7c8ba1"], overnight_low: ["on", "ONL", "#7c8ba1"],
  session_open: ["open", "Globex open", "#c9a227"], rth_open: ["open", "RTH open", "#c9a227"],
  opening_range_high: ["or", "OR high", "#4f9d69"], opening_range_low: ["or", "OR low", "#4f9d69"],
  ib_high: ["ib", "IB high", "#6c7bd1"], ib_low: ["ib", "IB low", "#6c7bd1"],
};
const TOGGLES: [string, string][] = [["ema9", "EMA 9"], ["ema20", "EMA 20"], ["ema50", "EMA 50"], ["ema200", "EMA 200"], ["vwap", "VWAP"],
  ["volume", "Volume"], ["pd", "Prev day H/L"], ["on", "Overnight H/L"], ["open", "Session open"], ["or", "Opening range"], ["ib", "Initial balance"],
  ["structure", "BOS / CHoCH"], ["swings", "Swings"], ["fvg", "Fair value gaps"], ["sweeps", "Sweeps"], ["sr", "Support / resistance"], ["profile", "Volume profile"]];
const DEFAULT_ON = new Set(["ema9", "ema20", "ema50", "ema200", "vwap", "volume", "pd", "on", "open", "or", "ib", "structure", "fvg", "profile"]);

function css(v: string) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim() || "#888"; }
const ctTick = new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", hour: "2-digit", minute: "2-digit", hour12: false });
const ctDay = new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", month: "short", day: "numeric" });
const utcDay = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "short", day: "numeric" });

function loadToggles(): Set<string> {
  try { const v = localStorage.getItem("live.toggles"); if (v) return new Set(JSON.parse(v)); } catch { /* storage unavailable */ }
  return new Set(DEFAULT_ON);
}
function saveToggles(s: Set<string>) { try { localStorage.setItem("live.toggles", JSON.stringify([...s])); } catch { /* ignore */ } }

type Quote = { status: string; price?: number; bid?: number; ask?: number; exchange_ts?: string; received_at?: string; contract?: string; source?: string };

export function LiveMarket() {
  const [root, setRoot] = useState(() => { try { return localStorage.getItem("live.root") || "MNQ"; } catch { return "MNQ"; } });
  const [tf, setTf] = useState(() => { try { return localStorage.getItem("live.tf") || "5Min"; } catch { return "5Min"; } });
  const [on, setOn] = useState<Set<string>>(loadToggles);
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [streamState, setStreamState] = useState<any>(null);
  const [updates, setUpdates] = useState(0);
  const tfSec = TFS.find((t) => t[0] === tf)![2];
  const chartRef = useRef<LiveChartHandle | null>(null);
  const reqId = useRef(0);

  const load = useCallback(async () => {
    const id = ++reqId.current;
    try {
      const d = await api(`/futures/live/chart?root=${root}&timeframe=${tf}`);
      if (id !== reqId.current) return;                      // a newer request superseded this one
      setData(d); setErr(null);
      setQuote((q) => (q && q.contract === d.contract.code ? q : { status: d.data.status, price: d.data.price, bid: d.data.bid, ask: d.data.ask,
        exchange_ts: d.data.exchange_ts, received_at: d.data.received_at, contract: d.contract.code, source: d.data.provider }));
    } catch (e: any) { if (id === reqId.current) setErr(e.message); }
  }, [root, tf]);

  useEffect(() => { setData(null); setQuote(null); load(); }, [load]);
  useEffect(() => { try { localStorage.setItem("live.root", root); localStorage.setItem("live.tf", tf); } catch { /* ignore */ } }, [root, tf]);
  // Without a stream nothing is pushed: refresh on a timer so delayed/historical charts still move (never labelled live).
  useEffect(() => {
    const live = data?.stream?.state && data.stream.state !== "off";
    const t = setInterval(load, live ? 120000 : (tfSec <= 300 ? 30000 : 60000));
    return () => clearInterval(t);
  }, [load, data?.stream?.state, tfSec]);

  useEffect(() => {
    ensureLive();
    return onLiveMessage((m) => {
      if (m.type === "futures_stream") { setStreamState(m.data); return; }
      if (m.data?.root !== root) return;
      if (m.type === "futures_live") {
        const d = m.data;
        setQuote({ status: d.status, price: d.price, bid: d.bid, ask: d.ask, exchange_ts: d.exchange_ts, received_at: d.received_at, contract: d.contract, source: d.source });
        if (d.status === "realtime" && d.bar) { chartRef.current?.liveMinute(d.bar); setUpdates((n) => n + 1); }
      } else if (m.type === "futures_bar_closed") {
        // refetch indicators/overlays from the server when a bar of THIS timeframe closes
        const end = Date.parse(m.data.ts) / 1000 + 60;
        if (tfSec <= 3600 ? end % tfSec === 0 : true) setTimeout(load, 1500);
      }
    });
  }, [root, tfSec, load]);

  const status = quote?.status || data?.data?.status;
  const live = status === "realtime";
  const toggle = (k: string) => { const s = new Set(on); if (s.has(k)) s.delete(k); else s.add(k); setOn(s); saveToggles(s); };
  const dec = data?.spec?.decimals ?? 2;
  const fmt = (v: any) => (typeof v === "number" ? v.toFixed(dec) : "—");

  return (
    <div className="page">
      <div className="spread">
        <div className="row">{ROOTS.map((r) => <button key={r} className={root === r ? "primary" : ""} onClick={() => setRoot(r)}>{r}</button>)}</div>
        <div className="row">{TFS.map(([v, l]) => <button key={v} className={tf === v ? "primary" : "ghost"} onClick={() => setTf(v)}>{l}</button>)}</div>
      </div>
      <div className={`strip-lite row live-status ${live ? "is-live" : "not-live"}`}>
        <b>{data?.contract?.code || root}</b>
        <span className={`badge ${live ? "pos" : "neg"}`} aria-live="polite">{STATUS_TEXT[status] || status || "…"}</span>
        <span>Last {fmt(quote?.price ?? data?.candles?.at(-1)?.close)}</span>
        <span className="small">Bid {fmt(quote?.bid)} · Ask {fmt(quote?.ask)}</span>
        <span className="small muted">Source: {quote?.source || data?.data?.provider || "—"}</span>
        <span className="small muted">Exchange time: {quote?.exchange_ts ? etTimeSec(quote.exchange_ts) + " ET" : "—"}</span>
        <span className="small muted">Received: {quote?.received_at ? etTimeSec(quote.received_at) + " ET" : "—"}</span>
        {live && <span className="small faint">{updates} live updates</span>}
      </div>
      {!live && data && <div className={`note ${status === "disconnected" || status === "stale" ? "bad" : "warn"}`}>
        <b>{status === "disconnected" ? "DISCONNECTED." : status === "stale" ? "STALE." : status === "delayed" ? "DELAYED, not live." :
          status === "cached" ? "CACHED copy, not live." : "Not live."}</b> {data.data.reason} {data.stream?.state === "off" && data.stream.reason}
        {" "}The chart shows the last data received and is greyed out. No live signals or simulated fills are generated from it.
      </div>}
      {err && <div className="note bad">{err}</div>}
      <div className="cols c-main">
        <div className="stack">
          <div className={live ? "" : "chart-not-live"}>
            {data ? <LiveChart ref={chartRef} data={data} on={on} tfSec={tfSec} /> : <div className="chart-box"><div className="empty">Loading…</div></div>}
          </div>
          <div className="small faint">{data?.indicators_note} Times on the axis are exchange time (CT). Structure markers sit at the bar where they
            were calculated; hover a marker for its price. {data?.notes?.join(" ")}</div>
        </div>
        <div className="stack">
          <Panel title="Indicators & overlays">
            <div className="toggle-grid">{TOGGLES.map(([k, l]) => <label key={k} className="check small">
              <input type="checkbox" checked={on.has(k)} onChange={() => toggle(k)} />{l}</label>)}</div>
          </Panel>
          <Panel title="Data integrity">
            <table className="small"><tbody>
              <tr><td className="muted">Status</td><td>{STATUS_TEXT[status] || status}</td></tr>
              <tr><td className="muted">Source</td><td>{quote?.source || data?.data?.provider}</td></tr>
              <tr><td className="muted">Contract</td><td>{data?.contract?.code} {data?.contract?.in_roll_window ? "(past roll date)" : ""}</td></tr>
              <tr><td className="muted">Exchange time</td><td>{quote?.exchange_ts || data?.data?.data_time || "—"}</td></tr>
              <tr><td className="muted">Received</td><td>{quote?.received_at || data?.data?.fetched_at || "—"}</td></tr>
              <tr><td className="muted">Stream</td><td>{streamState?.state || data?.stream?.state} {data?.stream?.reconnects ? `· ${data.stream.reconnects} reconnects` : ""}</td></tr>
              <tr><td className="muted">Checks</td><td>{data?.data?.validation?.summary || "—"}</td></tr>
              <tr><td className="muted">Tick</td><td>{data?.spec?.tick_size} = ${data?.spec?.tick_value}</td></tr>
            </tbody></table>
            {(data?.stream?.gaps || []).slice(0, 3).map((g: any, i: number) => <div key={i} className="small faint">Gap {g.seconds}s ({g.contract}):
              backfilled {g.backfill?.added ?? 0} new, {g.backfill?.replaced ?? 0} corrected minutes{g.backfill?.error ? `, error: ${g.backfill.error}` : ""}.</div>)}
          </Panel>
          <LevelsList data={data} fmt={fmt} on={on} />
        </div>
      </div>
    </div>
  );
}

function LevelsList({ data, fmt, on }: { data: any; fmt: (v: any) => string; on: Set<string> }) {
  if (!data) return null;
  const ov = data.overlays || {};
  return (
    <Panel title="Levels and structure" sub={ov.structure_state ? `structure (5m): ${ov.structure_state.trend}` : ""}>
      <table className="small"><tbody>
        {Object.entries(data.levels || {}).filter(([k]) => k !== "vwap").map(([k, v]: any) => <tr key={k}><td className="muted">{LEVEL_STYLE[k]?.[1] || k}</td><td className="num">{fmt(v.price)}</td></tr>)}
        {on.has("sr") && (ov.support_resistance || []).map((s: any) => <tr key={s.name}><td className="muted">{s.side}: {s.name.replace(/_/g, " ")}</td><td className="num">{fmt(s.price)}</td></tr>)}
      </tbody></table>
      {(ov.structure || []).slice(-4).reverse().map((m: any) => <div key={m.time + m.kind} className="small">{m.kind} {m.direction} through {fmt(m.level)} at {ctTick.format(new Date(m.time * 1000))} CT</div>)}
      {(ov.sweeps || []).slice(-3).map((s: any, i: number) => <div key={i} className="small faint">{s.text} ({ctTick.format(new Date(s.time * 1000))} CT)</div>)}
      {(ov.fvgs || []).slice(0, 3).map((g: any) => <div key={g.formed + g.kind} className="small faint">Unfilled {g.kind} FVG {fmt(g.low)}–{fmt(g.high)}</div>)}
    </Panel>
  );
}

// ---------------- chart ----------------

type LiveChartHandle = { liveMinute: (bar: any) => void };

const LiveChart = forwardRef<LiveChartHandle, { data: any; on: Set<string>; tfSec: number }>(function LiveChart({ data, on, tfSec }, ref) {
  const box = useRef<HTMLDivElement>(null);
  const prof = useRef<HTMLDivElement>(null);
  const ch = useRef<IChartApi | null>(null);
  const s = useRef<{ c?: ISeriesApi<"Candlestick">; v?: ISeriesApi<"Histogram">; ema: Record<string, ISeriesApi<"Line">>; vwap?: ISeriesApi<"Line">;
    lines: IPriceLine[]; markers?: ISeriesMarkersPluginApi<Time> }>({ ema: {}, lines: [] });
  // live state for the forming candle
  const st = useRef<{ last?: any; base?: number; minutes: Map<number, number>; emaPrev: Record<string, number | undefined> }>({ minutes: new Map(), emaPrev: {} });
  const daily = tfSec >= 86400;

  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: css("--panel") }, textColor: css("--muted"), fontFamily: css("--data"), fontSize: 12 },
      grid: { vertLines: { color: "#1c232e" }, horzLines: { color: "#1c232e" } },
      rightPriceScale: { borderColor: css("--rule") },
      timeScale: { borderColor: css("--rule"), timeVisible: !daily, secondsVisible: false,
        tickMarkFormatter: (t: number) => (daily ? utcDay.format(new Date(t * 1000)) : ctTick.format(new Date(t * 1000))) },
      localization: { timeFormatter: (t: number) => (daily ? utcDay.format(new Date(t * 1000)) : `${ctDay.format(new Date(t * 1000))} ${ctTick.format(new Date(t * 1000))} CT`) },
      crosshair: { mode: 1 },
    });
    ch.current = c;
    const up = css("--up"), down = css("--down");
    s.current.c = c.addSeries(CandlestickSeries, { upColor: up, downColor: down, borderVisible: false, wickUpColor: up, wickDownColor: down,
      priceFormat: { type: "price", precision: data.spec?.decimals ?? 2, minMove: Number(data.spec?.tick_size) || 0.25 } });
    s.current.v = c.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
    s.current.v.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    for (const n of ["9", "20", "50", "200"]) s.current.ema[n] = c.addSeries(LineSeries, { color: EMA_COLORS[n], lineWidth: 1, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    s.current.vwap = c.addSeries(LineSeries, { color: "#e07a5f", lineWidth: 2, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    s.current.markers = createSeriesMarkers(s.current.c, []);
    const redraw = () => requestAnimationFrame(drawProfile);
    c.timeScale().subscribeVisibleLogicalRangeChange(redraw);
    const ro = new ResizeObserver(redraw);
    ro.observe(box.current);
    return () => { ro.disconnect(); c.remove(); ch.current = null; s.current = { ema: {}, lines: [] }; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [daily, data.spec?.tick_size]);

  const volColor = (b: any) => (b.close >= b.open ? "rgba(63,182,139,.35)" : "rgba(229,83,75,.35)");

  // full data (initial load and on each bar close refetch)
  useEffect(() => {
    const c = ch.current, x = s.current;
    if (!c || !x.c || !x.v) return;
    const candles = data.candles || [];
    x.c.setData(candles.map((b: any) => ({ time: b.time as Time, open: b.open, high: b.high, low: b.low, close: b.close })));
    x.v.setData(on.has("volume") ? candles.map((b: any) => ({ time: b.time as Time, value: b.volume, color: volColor(b) })) : []);
    for (const n of ["9", "20", "50", "200"]) x.ema[n].setData(on.has(`ema${n}`) ? (data.ema?.[n] || []).map((p: any) => ({ time: p.time as Time, value: p.value })) : []);
    // VWAP resets each session: the segment joining two sessions is drawn transparent
    let prevTd: string | null = null;
    const vw = (data.vwap || []).map((p: any) => { const brk = prevTd !== null && p.trade_date !== prevTd; prevTd = p.trade_date;
      return { time: p.time as Time, value: p.value, ...(brk ? { color: "rgba(0,0,0,0)" } : {}) }; });
    x.vwap!.setData(on.has("vwap") ? vw : []);
    // price lines: levels, FVG edges, S/R
    x.lines.forEach((l) => x.c!.removePriceLine(l));
    x.lines = [];
    const add = (price: number, color: string, title: string, dashed = true) => x.lines.push(x.c!.createPriceLine({ price, color, lineWidth: 1, lineStyle: dashed ? LineStyle.Dashed : LineStyle.Solid, axisLabelVisible: true, title }));
    for (const [k, v] of Object.entries<any>(data.levels || {})) { const st_ = LEVEL_STYLE[k]; if (st_ && on.has(st_[0])) add(v.price, st_[2], st_[1]); }
    if (on.has("fvg")) for (const g of (data.overlays?.fvgs || []).slice(0, 3)) { const col = g.kind === "bullish" ? "rgba(63,182,139,.8)" : "rgba(229,83,75,.8)"; add(g.high, col, `FVG ${g.kind === "bullish" ? "↑" : "↓"} top`); add(g.low, col, `FVG ${g.kind === "bullish" ? "↑" : "↓"} bottom`); }
    if (on.has("sr")) for (const r of data.overlays?.support_resistance || []) add(r.price, r.side === "support" ? "#3fb68b" : "#e5534b", r.name.replace(/_/g, " "), false);
    // markers: structure, swings, sweeps (each at its calculated bar)
    const mk: SeriesMarker<Time>[] = [];
    const times = new Set(candles.map((b: any) => b.time));
    if (on.has("structure")) for (const m of data.overlays?.structure || []) if (times.has(m.time)) mk.push({ time: m.time as Time, position: m.direction === "up" ? "belowBar" : "aboveBar", color: m.kind === "CHoCH" ? "#e8b04a" : m.direction === "up" ? "#3fb68b" : "#e5534b", shape: m.direction === "up" ? "arrowUp" : "arrowDown", text: `${m.kind} ${m.level.toFixed(data.spec?.decimals ?? 2)}` });
    if (on.has("swings")) for (const w of data.overlays?.swings || []) if (times.has(w.time)) mk.push({ time: w.time as Time, position: w.kind === "high" ? "aboveBar" : "belowBar", color: "#8892a0", shape: "circle", text: w.kind === "high" ? "SH" : "SL" });
    if (on.has("sweeps")) for (const w of data.overlays?.sweeps || []) if (times.has(w.time)) mk.push({ time: w.time as Time, position: w.side === "above" ? "aboveBar" : "belowBar", color: "#c678dd", shape: "square", text: `sweep ${w.level}` });
    mk.sort((a, b) => (a.time as number) - (b.time as number));
    x.markers?.setMarkers(mk);
    // live-update baseline for the forming candle
    const last = candles.at(-1);
    const lm = data.last_minute;
    st.current = { last: last ? { ...last } : undefined, minutes: new Map(), emaPrev: {},
      base: last ? last.volume - (lm && lm.time >= last.time && lm.time < last.time + tfSec ? lm.volume : 0) : 0 };
    if (lm && last && lm.time >= last.time && lm.time < last.time + tfSec) st.current.minutes.set(lm.time, lm.volume);
    for (const n of ["9", "20", "50", "200"]) { const arr = data.ema?.[n] || []; const prev = arr.length > 1 && arr.at(-1).time === last?.time ? arr.at(-2).value : arr.at(-1)?.value; st.current.emaPrev[n] = prev; }
    requestAnimationFrame(drawProfile);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, on]);

  // incremental update from a streamed 1-minute bar (no redraw of the whole chart)
  useImperativeHandle(ref, () => ({
    liveMinute(bar: any) {
      const x = s.current, L = st.current;
      if (!x.c || !L.last) return;
      const m = bar.ts as number;
      if (m < L.last.time) return;                                       // older than the forming candle: the next refetch has it
      if (m >= L.last.time + tfSec) {
        if (tfSec > 3600) return;                                         // 4h/daily: new buckets come from the server refetch
        const start = Math.floor(m / tfSec) * tfSec;                      // ≤1h buckets align with the 17:00 CT session open
        for (const n of Object.keys(L.emaPrev)) { const k = 2 / (Number(n) + 1); const p = L.emaPrev[n]; L.emaPrev[n] = p === undefined ? undefined : p + k * (L.last.close - p); }
        L.last = { time: start, open: bar.open, high: bar.high, low: bar.low, close: bar.close, volume: 0 };
        L.base = 0; L.minutes = new Map();
      }
      L.minutes.set(m, bar.volume);
      const c = L.last;
      c.high = Math.max(c.high, bar.high); c.low = Math.min(c.low, bar.low); c.close = bar.close;
      c.volume = (L.base || 0) + [...L.minutes.values()].reduce((a, b) => a + b, 0);
      x.c.update({ time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close });
      if (on.has("volume")) x.v?.update({ time: c.time as Time, value: c.volume, color: volColor(c) });
      for (const n of ["9", "20", "50", "200"]) {
        const p = L.emaPrev[n];
        if (p !== undefined && on.has(`ema${n}`)) x.ema[n].update({ time: c.time as Time, value: p + (2 / (Number(n) + 1)) * (c.close - p) });
      }
    },
  }), [tfSec, on]);

  function drawProfile() {
    const el = prof.current, x = s.current;
    if (!el || !x.c) return;
    const p = data.overlays?.volume_profile?.previous_rth;
    if (!on.has("profile") || !p?.bins?.length) { el.innerHTML = ""; return; }
    const max = Math.max(...p.bins.map((b: any) => b[1]));
    const step = Number(data.spec?.tick_size || 0.25) * (p.bin_ticks || 1);
    let html = "";
    for (const [price, vol] of p.bins) {
      const y1 = x.c.priceToCoordinate(price + step / 2), y2 = x.c.priceToCoordinate(price - step / 2);
      if (y1 == null || y2 == null) continue;
      const w = Math.round((vol / max) * 120);
      const inVa = price >= p.val && price <= p.vah;
      html += `<div style="position:absolute;right:62px;top:${Math.min(y1, y2)}px;height:${Math.max(1, Math.abs(y2 - y1) - 1)}px;width:${w}px;background:${price === p.poc ? "rgba(232,176,74,.55)" : inVa ? "rgba(90,169,230,.28)" : "rgba(140,150,165,.18)"}"></div>`;
    }
    el.innerHTML = html;
  }

  const legend = useMemo(() => [["9", "EMA 9"], ["20", "EMA 20"], ["50", "EMA 50"], ["200", "EMA 200"]].filter(([n]) => on.has(`ema${n}`)), [on]);
  return (
    <div className="chart-box live-chart" style={{ height: 560, position: "relative" }} ref={box}>
      <div ref={prof} className="vp-layer" title="Previous RTH volume profile (approximate, from bar volume)" />
      <div className="chart-legend">{legend.map(([n, l]) => <span key={n} style={{ color: EMA_COLORS[n] }}>{l}</span>)}
        {on.has("vwap") && data.vwap?.length > 0 && <span style={{ color: "#e07a5f" }}>VWAP</span>}</div>
    </div>
  );
});

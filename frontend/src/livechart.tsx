// Live price header + chart, fed by the prices read from your TopstepX chart (GET /api/visual/live, plus instant pushes).
// The line only ever shows accepted reads; breaks in the line are times the chart couldn't be read. Nothing is filled in.
import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries, ColorType, IChartApi, ISeriesApi, LineSeries, LineStyle, LineType, createChart,
} from "lightweight-charts";
import { api, onLiveMessage } from "./lib";
import { explain } from "./plain";
import { Countdown, futuresHoursSymbol, useMarketState } from "./markethours";

const RANGES: [string, string][] = [["live", "5 min"], ["1h", "1 hour"], ["4h", "4 hours"], ["day", "Today"]];
const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fmt = (v: number | null | undefined, d = 2) => (v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
const clock = (t: number | string | null | undefined, secs = false) => {
  if (t == null) return "";
  const d = typeof t === "number" ? new Date(t * 1000) : new Date(t);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", ...(secs ? { second: "2-digit" } : {}) });
};

type Live = any;

/** Shared live state for one chart profile: polled every 3 s, with instant updates pushed in between. */
function useLivePrice(pid: string | null, range: string) {
  const [d, setD] = useState<Live | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const path = pid ? `/visual/live/${pid}?range=${range}` : `/visual/live?range=${range}`;
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try { const x = await api(path); if (alive) { setD(x); setErr(null); } }
      catch (e: any) { if (alive) setErr(e.message); }
    };
    load();
    const t = setInterval(load, 3000);
    const off = onLiveMessage((m) => {
      if (m.type !== "visual_price") return;
      setD((cur: Live | null) => {
        if (!cur?.profile || m.data.profile !== cur.profile.id) return cur;
        const pt: [number, number | null] = [m.data.t, m.data.price];
        const series = [...(cur.series || []), pt].slice(-4000);
        if (m.data.price == null) return { ...cur, series, live: false, status: m.data.status };
        const ref = cur.reference?.price;
        return { ...cur, series, price: m.data.price, at: new Date(m.data.t * 1000).toISOString(), age_seconds: 0, method: m.data.method,
          live: true, status: "screen_capture", status_word: "Working",
          change: ref != null ? m.data.price - ref : cur.change, change_pct: ref ? ((m.data.price - ref) / ref) * 100 : cur.change_pct };
      });
    });
    return () => { alive = false; clearInterval(t); off(); };
  }, [path]);
  return { d, err };
}

export function LineChart({ series, reference, trend, candles, mode, onHover, dateTicks }: {
  series: [number, number | null][]; reference: number | null; trend: "up" | "down" | "flat"; candles: any[]; mode: "line" | "candles";
  onHover: (p: { price: number; t: number } | null) => void; dateTicks?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const line = useRef<ISeriesApi<"Line"> | null>(null);
  const cs = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const hover = useRef(onHover);
  hover.current = onHover;
  useEffect(() => {
    if (!box.current) return;
    const ch = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: css("--faint"), fontFamily: css("--ui"), fontSize: 11, attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.08 } },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: true, rightOffset: 4,
        tickMarkFormatter: (t: number, kind: number) => (kind < 3 || dateTicks ? new Date(t * 1000).toLocaleDateString([], { month: "short", day: "numeric" })
          : clock(t, kind === 4)) },   // 0-2 = day boundaries (show the date); 4 = inside a minute (show seconds)
      localization: { timeFormatter: (t: number) => (dateTicks ? new Date(t * 1000).toLocaleDateString([], { month: "short", day: "numeric" }) : clock(t, true)) },
      crosshair: { mode: 1, vertLine: { color: css("--faint"), width: 1, style: LineStyle.Solid, labelVisible: false },
        horzLine: { visible: false, labelVisible: false } },
      handleScale: false, handleScroll: false,
    });
    chart.current = ch;
    ch.subscribeCrosshairMove((p) => {
      const s = line.current;
      if (!p.time || !s || !p.seriesData.get(s)) { hover.current(null); return; }
      const v: any = p.seriesData.get(s);
      hover.current(v?.value != null ? { price: v.value, t: Number(p.time) } : null);
    });
    return () => { ch.remove(); chart.current = null; line.current = null; cs.current = null; };
  }, []);
  useEffect(() => {
    const ch = chart.current;
    if (!ch) return;
    if (line.current) { ch.removeSeries(line.current); line.current = null; }
    if (cs.current) { ch.removeSeries(cs.current); cs.current = null; }
    const color = trend === "down" ? css("--down") : css("--up");
    if (mode === "candles") {
      const up = css("--up"), dn = css("--down");
      const c = ch.addSeries(CandlestickSeries, { upColor: up, downColor: dn, borderVisible: false, wickUpColor: up, wickDownColor: dn, priceLineVisible: false });
      c.setData(candles.map((b) => ({ time: b.time as any, open: b.open, high: b.high, low: b.low, close: b.close })));
      cs.current = c;
    }
    // whitespace points (no value) break the line where the chart couldn't be read
    const data: any[] = [];
    let lastT = -1;
    for (const [t, p] of series) {
      const tt = Math.floor(t);
      if (tt <= lastT) { if (p != null && data.length && data[data.length - 1].value != null) data[data.length - 1] = { time: tt, value: p }; continue; }
      data.push(p == null ? { time: tt } : { time: tt, value: p });
      lastT = tt;
    }
    if (mode === "line" || !candles.length) {
      const l = ch.addSeries(LineSeries, { color, lineWidth: 2, lineType: LineType.Simple, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerRadius: 4, crosshairMarkerBorderColor: css("--panel"), crosshairMarkerBackgroundColor: color, pointMarkersVisible: false });
      l.setData(data);
      if (reference != null) l.createPriceLine({ price: reference, color: css("--faint"), lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" });
      line.current = l;
    }
    ch.timeScale().fitContent();
  }, [series, reference, trend, candles, mode]);
  return <div className="live-chart" ref={box} />;
}

/** Robinhood-style header: contract, big price, change since the session began, and a clean live line chart. */
export function LivePrice({ pid = null, compact = false }: { pid?: string | null; compact?: boolean }) {
  const [range, setRange] = useState("day");
  const [mode, setMode] = useState<"line" | "candles">("line");
  const [hover, setHover] = useState<{ price: number; t: number } | null>(null);
  const { d, err } = useLivePrice(pid, range);
  const ms = useMarketState(futuresHoursSymbol(d?.contract));
  const closed = ms.data && ms.data.open === false;
  const [flash, setFlash] = useState<"" | "up" | "down">("");
  const prev = useRef<number | null>(null);
  useEffect(() => {
    if (d?.price == null) return;
    if (prev.current != null && d.price !== prev.current) {
      setFlash(d.price > prev.current ? "up" : "down");
      const t = setTimeout(() => setFlash(""), 600);
      prev.current = d.price;
      return () => clearTimeout(t);
    }
    prev.current = d.price;
  }, [d?.price]);
  const trend: "up" | "down" | "flat" = d?.change == null ? "flat" : d.change > 0 ? "up" : d.change < 0 ? "down" : "flat";
  useEffect(() => {
    document.documentElement.dataset.trend = trend === "down" ? "down" : "up";
    return () => { delete document.documentElement.dataset.trend; };
  }, [trend]);
  const series = useMemo(() => d?.series || [], [d?.series]);
  const candles = useMemo(() => d?.candles || [], [d?.candles]);

  if (err && !d) return <div className="hero empty"><p className="muted">Couldn't load the live price: {err}</p></div>;
  if (!d) return <div className="hero empty"><p className="muted">Loading…</p></div>;
  if (!d.profile) {
    return (
      <div className="hero empty">
        <div className="hero-name">Live price</div>
        <p>Connect your TopstepX chart and Study Terminal will show its price here, updating about twice a second.</p>
        <a className="btn primary pill" href="#/visual/setup">Connect my chart</a>
      </div>
    );
  }
  const shown = hover ? hover.price : d.price;
  const ref = d.reference?.price ?? null;
  const ch = shown != null && ref != null ? shown - ref : null;
  const chPct = ch != null && ref ? (ch / ref) * 100 : null;
  const since = d.reference ? (d.reference.from_session_open ? "since the session opened at 6:00 PM" : `since ${clock(d.reference.at)}, when watching started`) : "";
  const why = !d.live && d.reason ? explain(d.reason.original || d.reason.headline) : null;
  return (
    <section className={`hero${compact ? " compact" : ""}${d.live ? "" : " not-live"}`} aria-label="Live price">
      <div className="hero-top">
        <div>
          <div className="hero-name">{d.contract}<span className="muted"> · {d.profile.name}</span></div>
          <div className={`hero-price flash-${flash}`} aria-live="off">{fmt(shown)}</div>
          <div className={`hero-change ${ch == null ? "" : ch > 0 ? "up" : ch < 0 ? "down" : ""}`}>
            {ch == null ? <span className="muted">Change shows after the first readable price this session</span>
              : <>{ch > 0 ? "+" : ch < 0 ? "−" : ""}{fmt(Math.abs(ch))} ({ch > 0 ? "+" : ch < 0 ? "−" : ""}{fmt(Math.abs(chPct ?? 0))}%)
                <span className="muted"> {hover ? `at ${clock(hover.t, true)}` : since}</span></>}
          </div>
        </div>
        <div className="hero-status">
          {closed && !d.live
            ? <><span className="pill-status off"><i />Futures {ms.data.label.toLowerCase()}</span>
                <div className="small">{ms.data.opens_text} · <Countdown to={ms.data.next_open} /></div>
                <div className="small muted">{d.at ? <>Last price read at {clock(d.at, true)}. </> : null}Prices move again when futures reopen.</div></>
            : <><span className={`pill-status ${d.live ? "on" : "off"}`}><i />{d.live ? "Live" : d.status_word}</span>
                <div className="small muted">{d.live
                  ? <>Read from your chart {d.age_seconds != null && d.age_seconds < 2 ? "just now" : `${Math.round(d.age_seconds ?? 0)} s ago`}</>
                  : d.at ? <>Last price read at {clock(d.at, true)}</> : <>No price read yet</>}</div></>}
        </div>
      </div>
      {why && <div className="hero-warn"><b>{why.headline}</b> {why.do}</div>}
      <LineChart series={series} reference={ref} trend={trend} candles={candles} mode={mode} onHover={setHover} />
      <div className="hero-foot">
        <div className="pills" role="tablist" aria-label="Time range">
          {RANGES.map(([k, l]) => <button key={k} role="tab" aria-selected={range === k} className={range === k ? "on" : ""} onClick={() => setRange(k)}>{l}</button>)}
          <span className="sep" />
          <button className={mode === "candles" ? "on" : ""} aria-pressed={mode === "candles"} onClick={() => setMode(mode === "line" ? "candles" : "line")}
            title="Candles are worked out from the picture of your chart, so they're estimates">Candles</button>
        </div>
        <details className="small muted"><summary>How accurate is this?</summary>
          <p>{d.source} {d.checks.rule} So far today: {d.checks.accepted.toLocaleString()} prices accepted, {d.checks.rejected.toLocaleString()} rejected
            {d.checks.last_reject ? ` (last: ${d.checks.last_reject})` : ""}. Gaps in the line are times the chart couldn't be read; nothing is filled in.
            {mode === "candles" ? ` ${d.candles_note}` : ""}</p>
        </details>
      </div>
    </section>
  );
}

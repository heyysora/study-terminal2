// Simple-mode stock chart: big price, today's change, a clean line chart, and plain cards. Advanced mode keeps the full page.
import { useEffect, useMemo, useState } from "react";
import { OrderTicket } from "./components";
import { LineChart } from "./livechart";
import { api, money, num, useLive, usePoll } from "./lib";
import { Countdown, OpenNowChips, useMarketState, useNow } from "./markethours";
import { Catalysts } from "./pages3";
import { actionWord, explain, statusWord } from "./plain";
import { ActionWord, Term, WhyBlock } from "./simple";
import { OddsCheck } from "./odds";
import { CandleRead } from "./packet";

const RANGES: Record<string, { tf: string; days?: number; bars?: number; label: string }> = {
  "1D": { tf: "5Min", days: 1, label: "Today" }, "5D": { tf: "15Min", days: 5, label: "5 days" }, "1M": { tf: "1Hour", days: 22, label: "1 month" },
  "3M": { tf: "1Day", bars: 63, label: "3 months" }, "1Y": { tf: "1Day", bars: 252, label: "1 year" },
};
const etDay = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" });
const clock = (t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const day = (t: number) => new Date(t * 1000).toLocaleDateString([], { month: "short", day: "numeric" });

export function SimpleStockChart({ symbol: routeSym }: { symbol?: string }) {
  const L = useLive();
  const [sym, setSym] = useState((routeSym || "SPY").toUpperCase());
  const [input, setInput] = useState(sym);
  const [range, setRange] = useState("1D");
  const [mode, setMode] = useState<"line" | "candles">("line");
  const [hover, setHover] = useState<{ price: number; t: number } | null>(null);
  const [ticket, setTicket] = useState<any>(null);
  useEffect(() => { if (routeSym) { setSym(routeSym.toUpperCase()); setInput(routeSym.toUpperCase()); } }, [routeSym]);
  const R = RANGES[range];
  const ms = useMarketState(sym);
  const st = ms.data;
  const crypto = st?.kind === "crypto" || /-(USD|USDT|USDC|EUR|GBP)$/.test(sym);
  const ext = crypto ? "true" : "false";              // crypto trades around the clock: keep every hour, not just stock hours
  const an = usePoll(`/analysis/${sym}?timeframes=${R.tf}&chart=${R.tf}&extended=${ext}`, 30000, [ext]);
  const day5 = usePoll(R.tf === "5Min" ? null : `/analysis/${sym}?timeframes=5Min&chart=5Min&extended=${ext}`, 60000, [ext]);
  // Follow this symbol live (stream + polling) while it's on screen, even if it isn't on a watchlist.
  useEffect(() => {
    const ping = () => { api(`/market/view/${encodeURIComponent(sym)}`, { method: "POST" }).catch(() => { /* the chart still loads */ }); };
    ping();
    const t = setInterval(ping, 60000);
    return () => clearInterval(t);
  }, [sym]);
  const now = useNow(1000);
  const sg = usePoll(`/signals/${sym}?timeframe=5Min`, 30000, []);
  const ex = usePoll(`/ai/explain/${sym}?timeframe=5Min`, 120000, [sym]);
  const wls = usePoll("/watchlists");
  const watch: string[] = wls.data?.[0]?.symbols || [];

  const bars: any[] = useMemo(() => {
    const all: any[] = an.data?.chart?.bars || [];
    if (R.bars) return all.slice(-R.bars);
    if (crypto && all.length) {                       // no "trading day" for crypto: 1D = the last 24 hours, 5D = the last 5 days
      const end = all[all.length - 1].time;
      return all.filter((b) => b.time > end - (R.days || 1) * 86400);
    }
    const days = [...new Set(all.map((b) => etDay.format(new Date(b.time * 1000))))];
    const keep = new Set(days.slice(-(R.days || 1)));
    return all.filter((b) => keep.has(etDay.format(new Date(b.time * 1000))));
  }, [an.data, R, crypto]);
  const snap5 = (R.tf === "5Min" ? an.data : day5.data)?.snapshots?.["5Min"];
  const prevClose: number | null = snap5?.session?.pdc ?? null;
  const live = L.symbols[sym];
  const lastBar = bars[bars.length - 1];
  const closedNow = !!(st && st.open === false);
  // official daily closes (the closing auction can differ a little from the last 5-minute bar)
  const daily = usePoll(closedNow && !crypto ? `/market/bars/${encodeURIComponent(sym)}?timeframe=1Day&days=12` : null, 600000, [closedNow, crypto]);
  const dBars: any[] = (daily.data?.bars || []).filter((b: any) => b.close);
  const officialClose: number | null = dBars.length ? dBars[dBars.length - 1].close : null;
  const officialPrev: number | null = dBars.length > 1 ? dBars[dBars.length - 2].close : null;
  // When the market is closed the big price is the last real close of the session; a later after-hours trade is shown on its own line.
  const closeNow: number | null = officialClose ?? lastBar?.close ?? null;
  const price: number | null = closedNow && !crypto && closeNow != null ? closeNow : live?.last?.price ?? lastBar?.close ?? null;
  const afterHours: number | null = closedNow && !crypto && closeNow != null && live?.last?.price != null && Math.abs(live.last.price - closeNow) > 0.005 ? live.last.price : null;
  const ref: number | null = range === "1D" && !crypto ? ((closedNow ? officialPrev : null) ?? prevClose ?? bars[0]?.open ?? null) : bars[0]?.open ?? null;
  const closed = st && !st.open;
  const lastDay = lastBar ? new Date(lastBar.time * 1000).toLocaleDateString([], { weekday: "long" }) : "";
  const shown = hover ? hover.price : price;
  const ch = shown != null && ref != null ? shown - ref : null;
  const chPct = ch != null && ref ? (ch / ref) * 100 : null;
  const trend: "up" | "down" | "flat" = ch == null ? "flat" : ch > 0 ? "up" : ch < 0 ? "down" : "flat";
  useEffect(() => { document.documentElement.dataset.trend = trend === "down" ? "down" : "up"; return () => { delete document.documentElement.dataset.trend; }; }, [trend]);
  const livePx: number | null = live?.last?.price ?? null;
  const liveT: number | null = live?.last?.ts ? Math.floor(new Date(live.last.ts).getTime() / 1000) : null;
  const series = useMemo(() => {
    const out = bars.map((b) => [b.time, b.close] as [number, number]);
    // the newest live price extends the line between chart refreshes (only while the market is open and on the short ranges)
    if (livePx != null && liveT != null && out.length && !closed && (range === "1D" || range === "5D") && liveT > out[out.length - 1][0]) out.push([liveT, livePx]);
    return out;
  }, [bars, livePx, liveT, closed, range]);
  const label = live?.label || an.data?.data_label;
  const sw = label ? statusWord(label.status) : null;
  const age = label?.age_seconds;

  // practice or wait (day-trading view: the 5-minute chart)
  const best = sg.data?.best || sg.data?.watch;
  const act = sg.data?.action || "NO TRADE";
  const isIdea = actionWord(act).tone === "idea" && best;
  const why = explain(sg.data?.reasons?.[0] || (isIdea ? `${best.setup_name} passed every check.` : "No setup"));
  const today = bars.length && range === "1D" ? { hi: Math.max(...bars.map((b) => b.high)), lo: Math.min(...bars.map((b) => b.low)) } : null;
  const se = snap5?.session || {};

  return (
    <div className="page stock">
      <form className="symbar" onSubmit={(e) => { e.preventDefault(); const s = input.trim().toUpperCase(); if (s) location.hash = `#/chart/${s}`; }}>
        <input aria-label="Look up a stock" placeholder="Look up a stock (AAPL) or crypto (BTC-USD)" value={input} onChange={(e) => setInput(e.target.value)} />
        <div className="pills">{watch.map((w) => <a key={w} className={`chip${w === sym ? " on" : ""}`} href={`#/chart/${w}`}>{w}</a>)}</div>
        <OpenNowChips current={sym} />
      </form>

      <section className={`hero${sw && sw.level !== "ok" ? " not-live" : ""}`} aria-label={`${sym} price`}>
        <div className="hero-top">
          <div>
            <div className="hero-name">{sym}</div>
            <div className="hero-price">{shown != null ? money(shown) : "—"}</div>
            <div className={`hero-change ${trend === "up" ? "up" : trend === "down" ? "down" : ""}`}>
              {ch == null ? <span className="muted">Loading…</span> : <>{ch > 0 ? "+" : ch < 0 ? "−" : ""}{money(Math.abs(ch))} ({ch > 0 ? "+" : ch < 0 ? "−" : ""}{num(Math.abs(chPct ?? 0))}%)
                <span className="muted"> {hover ? (range === "1D" || range === "5D" ? `at ${clock(hover.t)}` : `on ${day(hover.t)}`)
                  : range === "1D" ? (crypto ? "past 24 hours" : closed ? `on ${lastDay}` : prevClose != null ? "today" : "since the open") : `past ${R.label}`}</span></>}
            </div>
            {afterHours != null && closeNow != null && !hover && <div className="small muted">After hours: {money(afterHours)} ({afterHours >= closeNow ? "+" : "−"}{num(Math.abs(((afterHours - closeNow) / closeNow) * 100))}% from the close)</div>}
          </div>
          <div className="hero-status">
            {closed
              ? <><span className="pill-status off"><i />{st.label}</span>
                  <div className="small">{st.opens_text} · <Countdown to={st.next_open} /></div>
                  <div className="small muted">Showing the last real price{lastBar ? ` (${lastDay})` : ""}. It starts moving again when the market opens.</div></>
              : <>{sw && <span className={`pill-status ${sw.level === "ok" ? "on" : "off"}`}><i />{sw.level === "ok" ? "Updating" : sw.word}</span>}
                  <div className="small muted">{crypto ? "Trades 24/7. " : ""}Free prices from Yahoo Finance{live?.last?.received_at
                    ? `, last update ${Math.max(0, Math.round((now - new Date(live.last.received_at).getTime()) / 1000))} s ago`
                    : age != null ? `, ${age < 90 ? "about a minute" : `${Math.round(age / 60)} min`} behind` : ", can be a little behind"}</div></>}
          </div>
        </div>
        {an.error ? <div className="hero-warn">{an.error}</div> : !bars.length ? <div className="live-chart empty muted">Loading the chart…</div> :
          <LineChart series={series} reference={range === "1D" ? ref : null} trend={trend} candles={bars} mode={mode} onHover={setHover} dateTicks={!(range === "1D" || range === "5D")} />}
        <div className="hero-foot">
          <div className="pills" role="tablist" aria-label="Time range">
            {Object.entries(RANGES).map(([k, r]) => <button key={k} role="tab" aria-selected={range === k} className={range === k ? "on" : ""} onClick={() => setRange(k)} title={r.label}>{k}</button>)}
            <span className="sep" />
            <button className={mode === "candles" ? "on" : ""} aria-pressed={mode === "candles"} onClick={() => setMode(mode === "line" ? "candles" : "line")}>Candles</button>
          </div>
          {range === "1D" && !crypto && prevClose != null && <span className="small muted">Dotted line: the previous close ({money(prevClose)})</span>}
        </div>
      </section>

      <div className="home-grid">
        <CandleRead symbol={sym} />
        <section className="qa" aria-label="Practice a trade or wait?">
          <div className="q"><h2>Should I practice a trade or wait?</h2></div>
          <div className="a">
            <div className="verdict"><ActionWord a={act} big /><span className="muted">5-minute chart</span></div>
            <WhyBlock why={why} />
            {!crypto && isIdea && <div className="plan"><div className="plan-title">The practice plan</div>
              <dl>
                <div><dt><Term k="entry" /></dt><dd>{money(best.trigger)}</dd></div>
                <div><dt><Term k="stop" /></dt><dd>{money(best.stop)}</dd></div>
                <div><dt><Term k="target" /></dt><dd>{money(best.targets?.t1)}</dd></div>
              </dl>
              <button className="primary" onClick={() => setTicket(best)}>Practice this trade</button>
              {best.targets?.t1 != null && <OddsCheck symbol={sym} direction={best.direction} entry={best.trigger} stop={best.stop} target={best.targets.t1} />}
            </div>}
            {!crypto && !isIdea && <button onClick={() => setTicket({})}>Practice a trade anyway</button>}
            {ticket && <div className="plan"><OrderTicket symbol={sym} prefill={ticket.trigger ? ticket : null} /></div>}
          </div>
        </section>
        {!crypto && <section className="qa" aria-label="Key prices">
          <div className="q"><h2>Key prices</h2></div>
          <div className="a">
            <dl className="facts">
              <div><dt>Yesterday's close</dt><dd>{money(prevClose)}</dd></div>
              {today && <div><dt>Today's high</dt><dd>{money(today.hi)}</dd></div>}
              {today && <div><dt>Today's low</dt><dd>{money(today.lo)}</dd></div>}
              {se.vwap != null && <div><dt><Term k="vwap" /></dt><dd>{money(se.vwap)}</dd></div>}
              {se.or_high != null && <div><dt title="High and low of the first 15 minutes after 9:30">First 15 minutes</dt><dd>{money(se.or_low)} – {money(se.or_high)}</dd></div>}
              {se.pdh != null && <div><dt>Yesterday's high / low</dt><dd>{money(se.pdh)} / {money(se.pdl)}</dd></div>}
            </dl>
          </div>
        </section>}
      </div>

      <section className="qa" aria-label="What's happening">
        <div className="q"><h2>What's happening</h2></div>
        <div className="a">
          {!ex.data ? <span className="muted">Loading…</span> : <>
            {ex.data.sections.slice(0, 2).map((s: any) => <p key={s.heading} style={{ margin: 0, maxWidth: "none" }}><b>{s.heading}.</b> {s.body}</p>)}
            {ex.data.sections.length > 2 && <details><summary className="small">More</summary>
              {ex.data.sections.slice(2).map((s: any) => <p key={s.heading} className="small" style={{ maxWidth: "none" }}><b>{s.heading}.</b> {s.body}</p>)}</details>}
          </>}
        </div>
      </section>
      <Catalysts symbol={sym} />
      <p className="small muted">Want every indicator, setup and timeframe? Switch to Advanced at the top.</p>
    </div>
  );
}

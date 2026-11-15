// "Last closed candle": a plain read of the newest finished candle, and the same data as JSON to paste into any AI.
import { useState } from "react";
import { usePoll } from "./lib";

const REGIME: Record<string, string> = { TREND_UP: "Trending up", TREND_DOWN: "Trending down", RANGE: "Going sideways", HIGH_VOLATILITY: "Unusually jumpy" };
const NAMES: Record<string, string> = { trend: "Trend (moving averages)", momentum: "Momentum (RSI and MACD)", strength: "Trend strength (ADX)", volume: "Volume above normal", higher_timeframe: "Bigger timeframe agrees" };
const pretty = (s: string) => s.replace(/_/g, " ");

export function CandleRead({ symbol, timeframe = "5Min" }: { symbol: string; timeframe?: string }) {
  const p = usePoll(`/packet/${encodeURIComponent(symbol)}?timeframe=${timeframe}`, 60000, [symbol, timeframe]);
  const [copied, setCopied] = useState<string | null>(null);
  const d = p.data;
  if (!d) return p.error ? null : <section className="qa"><div className="q"><h2>Last closed candle</h2></div><div className="a muted">Loading…</div></section>;
  const copy = async () => {
    try { await navigator.clipboard.writeText(JSON.stringify(d, null, 1)); setCopied("Copied. Paste it into Claude or any AI and ask what it sees."); }
    catch { setCopied("Couldn't copy here. Use the JSON from the API: /api/packet/" + symbol); }
    setTimeout(() => setCopied(null), 5000);
  };
  const L = d.agreement.long, S = d.agreement.short;
  return (
    <section className="qa" aria-label="Last closed candle">
      <div className="q"><h2>Last closed candle</h2><span className="small muted">{timeframe.replace("Min", "-minute")} · {new Date(d.candle.time).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}</span></div>
      <div className="a stack">
        <div>{d.candle_in_words}{d.candle.patterns.length ? ` Pattern: ${d.candle.patterns.map(pretty).join(", ")}.` : ""}</div>
        <div>Market mood: <b>{REGIME[d.regime] || d.regime}</b>{d.trend.higher_timeframe ? ` · bigger timeframe leans ${d.trend.higher_timeframe.bias}` : ""}</div>
        <div className="small">Checks pointing up: <b className="up">{L.score / 20} of 5</b> · pointing down: <b className="down">{S.score / 20} of 5</b></div>
        <details><summary className="small">Which checks</summary>
          <ul className="small" style={{ margin: "4px 0", paddingLeft: 18 }}>{Object.keys(NAMES).map((k) => <li key={k}>{NAMES[k]}: {L.checks[k] ? "up" : S.checks[k] ? "down" : "neither"}</li>)}</ul>
          <div className="small faint">{d.agreement.meaning}</div></details>
        <div className="row"><button onClick={copy}>Copy for an AI</button></div>
        {copied && <div className="note">{copied}</div>}
        <div className="small faint">Closed candles only, so it never changes after the fact. Data: {d.data.status || "unknown"}.</div>
      </div>
    </section>
  );
}

// Market hours on screen: is this market open, and if not, a live countdown to when it opens.
// Stocks follow the stock exchange, futures follow CME Globex (Sunday 6 PM to Friday 5 PM ET), crypto is open 24/7.
import { useEffect, useState } from "react";
import { usePoll } from "./lib";

export function useNow(everyMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), everyMs); return () => clearInterval(t); }, [everyMs]);
  return now;
}

export function untilText(iso: string | null | undefined, now: number) {
  if (!iso) return "";
  let s = Math.max(0, Math.round((new Date(iso).getTime() - now) / 1000));
  const d = Math.floor(s / 86400); s -= d * 86400;
  const h = Math.floor(s / 3600); s -= h * 3600;
  const m = Math.floor(s / 60); s -= m * 60;
  if (d) return `${d}d ${h}h ${m}m`;
  if (h) return `${h}h ${m}m ${String(s).padStart(2, "0")}s`;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

export function Countdown({ to }: { to?: string | null }) {
  const now = useNow(1000);
  if (!to) return null;
  return <span className="countdown">{new Date(to).getTime() <= now ? "opening now" : `in ${untilText(to, now)}`}</span>;
}

// The symbol's market (stocks, futures or crypto): open or closed, and when it opens.
export function useMarketState(symbol: string | null | undefined) {
  return usePoll(symbol ? `/market/state/${encodeURIComponent(symbol)}` : null, 60000, [symbol]);
}

// "Trades 24/7" chips: markets that are actually moving at the weekend.
export function OpenNowChips({ current }: { current?: string }) {
  const list = [{ symbol: "BTC-USD", name: "Bitcoin" }, { symbol: "ETH-USD", name: "Ethereum" }];
  return (
    <span className="pills open-now" title="Crypto trades around the clock, weekends included">
      <span className="small muted">Open 24/7:</span>
      {list.map((m) => <a key={m.symbol} className={`chip${m.symbol === current ? " on" : ""}`} href={`#/chart/${m.symbol}`}>{m.name}</a>)}
    </span>
  );
}

// Futures contract on a TopstepX chart (MNQZ26) -> the free data symbol whose hours apply (MNQ=F).
export function futuresHoursSymbol(contract?: string | null) {
  const m = /^([A-Z0-9]{1,4}?)([FGHJKMNQUVXZ])(\d{1,2})$/.exec((contract || "").toUpperCase());
  return m ? `${m[1]}=F` : "NQ=F";
}

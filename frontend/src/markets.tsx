// Market cards beside the chart: live crypto from public exchange prices (watch only) and your stock list.
import { money, num, usePoll } from "./lib";

const px = (v: number | null | undefined) => v == null ? "—" : v >= 1 ? money(v) : `$${Number(v).toPrecision(4)}`;

function Spark({ data, up }: { data: number[] | null; up: boolean }) {
  if (!data || data.length < 3) return null;
  const lo = Math.min(...data), hi = Math.max(...data), w = 56, h = 18;
  const pts = data.map((v, i) => `${((i / (data.length - 1)) * w).toFixed(1)},${(h - 1 - ((v - lo) / (hi - lo || 1)) * (h - 2)).toFixed(1)}`).join(" ");
  return <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true"><polyline points={pts} fill="none" stroke={up ? "var(--chart-up)" : "var(--chart-down)"} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" /></svg>;
}

/** Exchange price for one crypto symbol (BTC-USD). Null for anything else, or when no exchange answers. */
export function useCryptoPrice(symbol: string, on: boolean) {
  const r = usePoll(on ? `/crypto/price/${encodeURIComponent(symbol)}` : null, 5000, [symbol, on]);
  return on && r.data && !r.error ? r.data : null;
}

export function MarketCards({ current, stocks }: { current: string; stocks: string[] }) {
  const m = usePoll("/crypto/markets", 8000);
  const d = m.data;
  return (
    <aside className="markets" aria-label="Markets">
      <h2 className="markets-title">Markets</h2>
      <div className="markets-head"><span className="chip on">Crypto</span><span className="small muted">{d?.ok ? `${d.source} · live` : "24/7"}</span></div>
      {!d ? <div className="small muted">Loading live prices…</div> : !d.ok ? <div className="note warn small">{d.error} {d.note}</div> :
        <div className="mkt-grid">
          {d.rows.map((r: any) => {
            const up = (r.change_24h_pct ?? 0) >= 0;
            return (
              <a key={r.symbol} className={`mkt${r.symbol === current ? " on" : ""}`} href={`#/chart/${r.symbol}`} title={`${r.name}: open the chart`}>
                <div className="mkt-top">
                  <div className="mkt-pair"><b>{r.coin}</b>/USD</div>
                  <div className="mkt-row"><span className="mkt-px">{px(r.price)}</span>
                    <span className={`mkt-ch ${r.change_24h_pct == null ? "muted" : up ? "up" : "down"}`}>{r.change_24h_pct == null ? "…" : `${up ? "+" : "−"}${num(Math.abs(r.change_24h_pct))}%`}<Spark data={r.spark} up={up} /></span></div>
                </div>
                <dl className="mkt-hl"><div><dt>24H High</dt><dd>{px(r.high_24h)}</dd></div><div><dt>24H Low</dt><dd>{px(r.low_24h)}</dd></div></dl>
              </a>
            );
          })}
        </div>}
      {d?.ok && <div className="small faint">{d.stale ? "These prices are old: the exchange hasn't answered for a while. " : ""}{d.note}</div>}
      {stocks.length > 0 && <>
        <div className="markets-head" style={{ marginTop: 6 }}><span className="chip on">Stocks</span><span className="small muted">your list</span></div>
        <div className="mkt-stocks">{stocks.map((s) => <a key={s} className={`chip${s === current ? " on" : ""}`} href={`#/chart/${s}`}>{s}</a>)}</div>
      </>}
    </aside>
  );
}

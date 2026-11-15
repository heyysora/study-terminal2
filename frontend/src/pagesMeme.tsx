// Memecoins: watch with live prices, rug-risk checks in plain words, and a PRACTICE account. Nothing here touches a wallet.
import { useState } from "react";
import { api, money, usePoll } from "./lib";

const fmtPx = (v: number | null | undefined) => v == null ? "—" : v >= 1 ? money(v) : `$${Number(v).toPrecision(4)}`;
const big = (v: number | null | undefined) => v == null ? "—" : v >= 1e6 ? `$${(v / 1e6).toFixed(2)}M` : v >= 1e3 ? `$${(v / 1e3).toFixed(1)}K` : `$${v.toFixed(0)}`;
const pct = (v: any) => v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(1)}%`;
const age = (h: number | null) => h == null ? "—" : h < 1 ? `${Math.round(h * 60)} min` : h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} d`;
const when = (iso: string) => new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const held = (m: number) => m < 90 ? `${m} min` : m < 2880 ? `${Math.round(m / 60)} h` : `${Math.round(m / 1440)} d`;
const LV: Record<string, string> = { ok: "up", caution: "warn-link", danger: "down", unknown: "muted" };

function Rows({ rows, onPick }: { rows: any[]; onPick: (t: string) => void }) {
  if (!rows.length) return <p className="muted">Nothing to show right now.</p>;
  return (
    <div className="sheet">
      {rows.map((r) => (
        <section key={r.token} className="qa" style={{ cursor: "pointer" }} onClick={() => onPick(r.token)}>
          <div className="spread">
            <div><b>{r.symbol}</b> <span className="small muted">{r.name}</span>
              {r.stage && <span className="badge" style={{ marginLeft: 8 }} title={r.stage.text}>{r.stage.label}</span>}
              {r.flags.length > 0 && <div className="small down">{r.flags.join(" · ")}</div>}</div>
            <div style={{ textAlign: "right" }}><b>{fmtPx(r.price_usd)}</b>
              <div className={`small ${(r.change?.h1 ?? 0) >= 0 ? "up" : "down"}`}>{pct(r.change?.h1)} 1h</div></div>
          </div>
          <div className="small muted">Pool {big(r.liquidity_usd)} · volume 1h {big(r.volume_h1)} · age {age(r.age_hours)} · {r.buys_h1 ?? "—"} buys / {r.sells_h1 ?? "—"} sells 1h</div>
        </section>
      ))}
    </div>
  );
}

function Practice({ token, symbol, onDone }: { token: string; symbol: string; onDone: () => void }) {
  const [usd, setUsd] = useState("25");
  const [stop, setStop] = useState("30");
  const [target, setTarget] = useState("");
  const [take, setTake] = useState("100");
  const [trail, setTrail] = useState("");
  const [pv, setPv] = useState<any>(null);
  const [msg, setMsg] = useState<{ t: string; bad?: boolean } | null>(null);
  const body = (confirm = false) => ({ token, usd: Number(usd), stop_pct: Number(stop), target_pct: target ? Number(target) : null,
    take_fraction: target ? Number(take) / 100 : 1, trail_pct: trail ? Number(trail) : null, confirm });
  const preview = async () => { setMsg(null); try { setPv(await api("/meme/practice/preview", { method: "POST", json: body() })); } catch (e: any) { setMsg({ t: e.message, bad: true }); } };
  const buy = async () => { try { await api("/meme/practice/buy", { method: "POST", json: body(true) }); setMsg({ t: `Bought ${symbol} in practice.` }); setPv(null); onDone(); } catch (e: any) { setMsg({ t: e.message, bad: true }); } };
  return (
    <div className="stack">
      <div className="form">
        <label className="f">Practice amount ($)<input type="number" min="1" value={usd} onChange={(e) => { setUsd(e.target.value); setPv(null); }} /></label>
        <label className="f">Stop: sell if it drops (%)<input type="number" min="5" max="90" value={stop} onChange={(e) => { setStop(e.target.value); setPv(null); }} /></label>
        <label className="f">Take profit at (+%, optional)<input type="number" min="1" value={target} onChange={(e) => { setTarget(e.target.value); setPv(null); }} /></label>
        {target && <label className="f">At that profit, sell<select value={take} onChange={(e) => { setTake(e.target.value); setPv(null); }}>
          <option value="100">all of it</option><option value="75">three quarters</option><option value="50">half, keep half</option><option value="25">a quarter</option></select></label>}
        <label className="f" title="The stop follows the price up and never moves down">Trailing stop (% under the highest price, optional)<input type="number" min="5" max="90" value={trail} onChange={(e) => { setTrail(e.target.value); setPv(null); }} /></label>
      </div>
      <div className="row"><button onClick={preview}>Preview</button>{pv?.ok && <button className="primary" onClick={buy}>Buy in practice</button>}</div>
      {pv && <div className="stack small">
        <div>Fill about {fmtPx(pv.fill_price)} (price impact {pv.impact_pct}%), fees about {money(pv.fee_usd)}. If the stop is hit you'd lose about <b className="down">{money(pv.loss_at_stop_usd)}</b>.</div>
        {pv.ok && pv.plan_text && <div><b>Your exit plan:</b> {pv.plan_text}</div>}
        {pv.errors.map((e: string) => <div key={e} className="note bad">{e}</div>)}
        {pv.warnings.map((e: string) => <div key={e} className="note warn">{e}</div>)}
        <div className="faint">{pv.note}</div>
      </div>}
      {msg && <div className={`note ${msg.bad ? "bad" : ""}`}>{msg.t}</div>}
    </div>
  );
}

function Token({ address, onClose, onTraded }: { address: string; onClose: () => void; onTraded: () => void }) {
  const t = usePoll(`/meme/token/${address}`, 15000, [address]);
  const d = t.data;
  if (!d) return <section className="guide">{t.error ? <div className="note bad">{t.error}</div> : "Loading…"}</section>;
  const p = d.pair, c = d.checks;
  return (
    <section className="guide stack">
      <div className="spread"><h2 style={{ margin: 0 }}>{p ? `${p.symbol} · ${p.name}` : "Token"}</h2><button className="ghost" onClick={onClose}>Close</button></div>
      {p ? <>
        <div className="hero-price" style={{ fontSize: 34 }}>{fmtPx(p.price_usd)}</div>
        <div className="small">5m {pct(p.change?.m5)} · 1h {pct(p.change?.h1)} · 24h {pct(p.change?.h24)} · pool {big(p.liquidity_usd)} · market cap {big(p.market_cap)} · age {age(p.age_hours)}
          {p.url && <> · <a href={p.url} target="_blank" rel="noreferrer">DexScreener</a></>}</div>
        {p.stage && <div className="small"><span className="badge">{p.stage.label}</span> {p.stage.text}</div>}
        <div className="small faint">Updates every 15 seconds from DexScreener (free; can lag a little).</div>
      </> : <div className="note warn">This token has no trading pool on DexScreener right now.</div>}
      <h3 style={{ marginBottom: 0 }}>Rug-risk check: <span className={LV[c.tone] || ""}>{c.verdict}</span></h3>
      <div>{c.say}</div>
      <ul style={{ margin: 0, paddingLeft: 18 }}>{c.items.map((i: any) => <li key={i.key}><b className={LV[i.level]}>{i.name}:</b> {i.text}</li>)}</ul>
      <div className="small faint">{c.note}</div>
      {p && <><h3 style={{ marginBottom: 0 }}>Practice a trade</h3><Practice token={address} symbol={p.symbol} onDone={onTraded} /></>}
      <div className="small faint">{d.real_trading}</div>
    </section>
  );
}

function useHide(): [boolean, () => void] {
  const [hide, setHide] = useState(() => { try { return localStorage.getItem("st.meme.hide") === "1"; } catch { return false; } });
  return [hide, () => setHide((h) => { try { localStorage.setItem("st.meme.hide", h ? "0" : "1"); } catch { /* fine */ } return !h; })];
}

function NoteBox({ token, field, value, label, onSaved }: { token: string; field: "why" | "lesson"; value: string | null; label: string; onSaved: () => void }) {
  const [edit, setEdit] = useState(false);
  const [text, setText] = useState(value || "");
  const save = async () => { await api("/meme/journal/note", { method: "POST", json: { token, [field]: text } }); setEdit(false); onSaved(); };
  if (!edit) return <div className="small"><span className="muted">{label}:</span> {value ? value : <i className="faint">not written</i>} <button className="ghost small" onClick={() => { setText(value || ""); setEdit(true); }}>{value ? "Edit" : "Write it"}</button></div>;
  return <div className="row"><input style={{ flex: 1 }} maxLength={600} autoFocus aria-label={label} placeholder={label} value={text} onChange={(e) => setText(e.target.value)} /><button className="small primary" onClick={save}>Save</button><button className="small ghost" onClick={() => setEdit(false)}>Cancel</button></div>;
}

function Account({ a, reload, onPick, hide, toggleHide }: { a: any; reload: () => void; onPick: (t: string) => void; hide: boolean; toggleHide: () => void }) {
  const [msg, setMsg] = useState<string | null>(null);
  const sell = async (token: string, fraction: number) => { try { const r = await api("/meme/practice/sell", { method: "POST", json: { token, fraction } }); setMsg(`Sold for ${money(r.received_usd)} (${r.pnl_usd >= 0 ? "+" : ""}${money(r.pnl_usd)}).`); reload(); } catch (e: any) { setMsg(e.message); } };
  if (!a) return null;
  const $ = (v: number | null | undefined) => v == null ? "—" : hide ? "•••" : money(v);
  const pc = (pnl: number | null, cost: number) => pnl == null || !cost ? "" : `${pnl >= 0 ? "+" : "−"}${Math.abs((pnl / cost) * 100).toFixed(1)}%`;
  return (
    <section className="guide stack">
      <div className="spread"><h2 style={{ margin: 0 }}>Memecoin practice account</h2>
        <span className="row"><button className="small ghost" onClick={toggleHide} title="Hide dollar amounts (for sharing your screen). Percentages stay.">{hide ? "Show amounts" : "Hide amounts"}</button><span className="pill-status off"><i />PRACTICE · pretend money</span></span></div>
      <div>Cash {$(a.cash_usd)} · worth now {$(a.equity_usd)} · <b className={a.pnl_usd >= 0 ? "up" : "down"}>{hide ? pc(a.pnl_usd, a.start_usd) : `${a.pnl_usd >= 0 ? "+" : ""}${money(a.pnl_usd)}`}</b> since you started{hide ? "" : ` with ${money(a.start_usd)}`}</div>
      {a.positions.length > 0 && <div className="sheet">{a.positions.map((p: any) => (
        <section key={p.token} className="qa"><div className="spread">
          <div><b style={{ cursor: "pointer" }} onClick={() => onPick(p.token)}>{p.symbol}</b> <span className="small muted">paid {$(p.cost_usd)}</span></div>
          <div style={{ textAlign: "right" }}>{$(p.if_sold_now_usd)} <span className={(p.pnl_usd ?? 0) >= 0 ? "up" : "down"}>{p.pnl_usd != null ? (hide ? pc(p.pnl_usd, p.cost_usd) : `${p.pnl_usd >= 0 ? "+" : ""}${money(p.pnl_usd)} (${pc(p.pnl_usd, p.cost_usd)})`) : ""}</span>
            <div className="row" style={{ justifyContent: "flex-end" }}><button className="small" onClick={() => sell(p.token, 0.5)}>Sell half</button><button className="small" onClick={() => sell(p.token, 1)}>Sell all</button></div></div>
        </div>
        <div className="small"><span className="muted">Exit plan:</span> stop at {fmtPx(p.active_stop)}{p.active_stop > p.stop_price ? " (trailing, moved up)" : p.took_profit ? " (moved up to your buy price)" : ""}
          {p.target_price ? ` · at ${fmtPx(p.target_price)} sell ${p.take_fraction < 1 ? `${Math.round(p.take_fraction * 100)}%` : "all"}` : p.took_profit ? " · part already sold at the target" : ""}
          {p.trail_pct ? ` · trailing ${p.trail_pct}% under the high (${fmtPx(p.high_price)})` : ""}</div>
        <NoteBox token={p.token} field="why" value={p.why || null} label="Why I bought" onSaved={reload} />
        <div className="small faint">"If sold now" includes the estimated price impact and fees. Stops and targets are checked about every 20 seconds.</div></section>
      ))}</div>}
      {msg && <div className="note">{msg}</div>}
      <div className="small faint">{a.note}</div>
    </section>
  );
}

function Journal({ hide, tick }: { hide: boolean; tick: number }) {
  const j = usePoll("/meme/journal", 30000, [tick]);
  const d = j.data;
  if (!d) return null;
  const $ = (v: number) => hide ? "•••" : money(v);
  return (
    <section className="guide stack">
      <div className="spread"><h2 style={{ margin: 0 }}>Memecoin practice journal</h2><span className="small muted">{d.count} finished · {d.wins} won · {d.losses} lost{hide ? "" : ` · ${d.total_pnl_usd >= 0 ? "+" : ""}${money(d.total_pnl_usd)}`}</span></div>
      {d.count === 0 ? <div className="muted">Finished practice trades show up here. Write down why you bought while the trade is open; it's the part people skip.</div> : <>
        {d.no_reason_written > 0 && <div className="note warn small">{d.no_reason_written} of {d.count} finished trades have no reason written. Trades without a reason are hard to learn from.</div>}
        {Object.keys(d.by_exit).length > 0 && <div className="small">How they ended: {Object.entries(d.by_exit).map(([k, v]: any) => `${k === "you" ? "sold by hand" : k} ${v.trades}${hide ? "" : ` (${v.pnl_usd >= 0 ? "+" : ""}${money(v.pnl_usd)})`}`).join(" · ")}</div>}
        <div className="sheet">{d.trades.slice(0, 30).map((t: any) => (
          <section key={t.token + t.closed} className="qa">
            <div className="spread"><div><b>{t.symbol}</b> <span className="small muted">{when(t.closed)} · held {held(t.minutes_held)} · ended by {t.exits[t.exits.length - 1] === "you" ? "selling by hand" : t.exits[t.exits.length - 1]}</span></div>
              <b className={t.pnl_usd >= 0 ? "up" : "down"}>{hide ? "" : `${t.pnl_usd >= 0 ? "+" : ""}${$(t.pnl_usd)} `}{t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct}%</b></div>
            <NoteBox token={t.token} field="why" value={t.why} label="Why I bought" onSaved={j.reload} />
            <NoteBox token={t.token} field="lesson" value={t.lesson} label="What I learned" onSaved={j.reload} />
          </section>))}</div>
      </>}
      <div className="small faint">{d.note}</div>
    </section>
  );
}

export function Memecoins() {
  const [kind, setKind] = useState("profiles");
  const [q, setQ] = useState("");
  const [pick, setPick] = useState<string | null>(null);
  const [results, setResults] = useState<any[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const feed = usePoll(`/meme/feed?kind=${kind}`, 30000, [kind]);
  const acct = usePoll("/meme/practice", 15000);
  const [hide, toggleHide] = useHide();
  const [tick, setTick] = useState(0);
  const reload = () => { acct.reload(); setTick((t) => t + 1); };
  const find = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null); setResults(null);
    const s = q.trim(); if (!s) return;
    try { const r = await api(`/meme/search?q=${encodeURIComponent(s)}`); if (r.address) setPick(r.address); else setResults(r.rows); } catch (x: any) { setErr(x.message); }
  };
  return (
    <div className="page home">
      <section className="guide">
        <h2 style={{ margin: 0 }}>Memecoins (Solana)</h2>
        <p style={{ margin: 0 }}>Watch new memecoins with live prices, check them for common rug-pull signs, and practise with pretend money. Most new memecoins lose most of their value; practise until you've seen that happen.</p>
        <form className="symbar" onSubmit={find}><input aria-label="Find a memecoin" placeholder="Paste a token address, or search a name" value={q} onChange={(e) => setQ(e.target.value)} /><button>Find</button></form>
        {err && <div className="note bad">{err}</div>}
      </section>
      {pick && <Token address={pick} onClose={() => setPick(null)} onTraded={reload} />}
      <Account a={acct.data} reload={reload} onPick={setPick} hide={hide} toggleHide={toggleHide} />
      <Journal hide={hide} tick={tick} />
      {results && <section className="guide"><div className="spread"><h3 style={{ margin: 0 }}>Search results</h3><button className="ghost" onClick={() => setResults(null)}>Clear</button></div><Rows rows={results} onPick={setPick} /></section>}
      <section className="guide stack">
        <div className="pills">{[["profiles", "Newest with a profile"], ["boosts", "Most promoted"]].map(([k, l]) => <button key={k} className={kind === k ? "on" : ""} onClick={() => setKind(k)}>{l}</button>)}</div>
        <div className="small muted">{feed.data?.label} Tap one for its rug-risk check.</div>
        {feed.error ? <div className="note bad">{feed.error}</div> : <Rows rows={feed.data?.rows || []} onPick={setPick} />}
        <div className="small faint">{feed.data?.source}</div>
      </section>
      <section className="guide small">
        <b>Real memecoin trading</b> happens outside Study Terminal, so your wallet's keys never touch this app. The guide (docs/MEMECOIN_REAL_TRADING.md) walks through pumpfun-cli: a separate small wallet, always a dry run first, small amounts.
      </section>
    </div>
  );
}

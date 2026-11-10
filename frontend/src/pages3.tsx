import { useState } from "react";
import { Action, LineChart, Panel, TIER_TEXT } from "./components";
import { api, etDate, etTime, money, num, sign, usePoll } from "./lib";

// ======================= shared: evidence + diagnostics (Backtest page) =======================

export function Evidence({ ev, title = "Statistical evidence" }: { ev?: any; title?: string }) {
  if (!ev) return null;
  const ci = ev.avg_r_ci95;
  return (
    <Panel title={title} sub="95% intervals; trades on the same day are resampled together">
      <div className="stack">
        <div className="row"><span className={`tier t-${ev.tier}`}>{TIER_TEXT[ev.tier] || ev.tier}</span><span className="small">{ev.tier_text}</span></div>
        {ev.trades > 0 && <div className="levels">
          <div><div className="k">Trades / days</div><div className="v">{ev.trades} / {ev.days}</div></div>
          <div><div className="k">Average R</div><div className={`v ${sign(ev.avg_r)}`}>{num(ev.avg_r, 3)}</div></div>
          <div><div className="k">95% interval</div><div className="v">{ci ? `${num(ci[0], 3)} to ${num(ci[1], 3)}` : "—"}</div></div>
          <div><div className="k">Win rate (interval)</div><div className="v">{num(ev.win_rate, 1)}% {ev.win_rate_ci95 ? <span className="small faint">{ev.win_rate_ci95[0]}–{ev.win_rate_ci95[1]}</span> : null}</div></div>
        </div>}
        {ev.folds_positive && <div className="small muted">Positive in {ev.folds_positive} walk-forward test windows.</div>}
        <div className="small faint">Only "Reliable" evidence lets a setup produce BUY or SHORT. Anything less stays watch-only, and setups that clearly lost become NO TRADE.</div>
      </div>
    </Panel>
  );
}

export function Diagnostics({ d, setupNames = {} }: { d?: any; setupNames?: Record<string, string> }) {
  const [dim, setDim] = useState("setup_direction");
  if (!d) return null;
  const m = d.mechanics || {};
  const sl = d.slices || {};
  const cur = sl[dim];
  return (
    <div className="stack">
      <Panel title="Why the trades won or lost" sub="measured on the trades above">
        <div className="stack">
          <div className="note warn small">{d.caveat}</div>
          {d.findings?.map((f: any, i: number) => (
            <div key={i} className="finding"><div className="spread"><b>{f.title}</b><span className={`small ${f.strength === "clear" ? "" : "faint"}`}>{f.strength}</span></div>
              <div className="small">{f.text}</div></div>))}
        </div>
      </Panel>
      {m.trades > 0 && <Panel title="Entry, stop and target mechanics" flush>
        <table><tbody>
          <tr><td>How trades ended</td><td className="r">{Object.entries(m.exit_mix_pct || {}).map(([k, v]) => `${k} ${v}%`).join(", ")}</td></tr>
          <tr><td>Win rate vs break-even win rate</td><td className="r">{m.win_rate_pct}% vs {m.breakeven_win_rate_pct}%</td></tr>
          <tr><td>Average winner / loser</td><td className="r">{num(m.avg_winner_r, 2)}R / {num(m.avg_loser_r, 2)}R</td></tr>
          <tr><td>Share of trades that ever reached +0.5R / +1R / +2R / +3R</td><td className="r">{["0.5R", "1.0R", "2.0R", "3.0R"].map((k) => `${m.mfe_reach_pct?.[k]}%`).join(" / ")}</td></tr>
          <tr><td>Median best / worst point during the trade</td><td className="r">+{m.median_mfe_r}R / −{m.median_mae_r}R</td></tr>
          <tr><td>Stopped within 2 bars of entry (false breakouts)</td><td className="r">{m.stopped_within_2_bars_pct}%</td></tr>
          <tr><td>Losers that were up +1R first (gave back)</td><td className="r">{m.losers_that_were_up_1r_pct}%</td></tr>
          <tr><td>Stopped, then hit the target later that day</td><td className="r">{m.stopped_then_hit_target_same_day_pct}%</td></tr>
          <tr><td>Cost per trade (slippage + commission)</td><td className="r">{num(m.avg_cost_r, 3)}R ({num(m.avg_r_before_costs, 3)}R before, {num(m.avg_r_after_costs, 3)}R after)</td></tr>
        </tbody></table>
      </Panel>}
      <Panel title="Results by…" right={<select value={dim} onChange={(e) => setDim(e.target.value)} aria-label="Slice">
        {Object.entries(sl).map(([k, v]: any) => <option key={k} value={k}>{v.label}</option>)}</select>} flush>
        {cur && <table><thead><tr><th>{cur.label}</th><th className="r">Trades</th><th className="r">Share</th><th className="r">Win %</th><th className="r">Avg R</th><th className="r">95% interval</th><th>Evidence</th></tr></thead>
          <tbody>{cur.rows.map((r: any) => <tr key={r.bucket}><td>{setupNames[r.bucket] || r.bucket}</td><td className="r">{r.trades}</td><td className="r">{r.share_pct}%</td>
            <td className="r">{num(r.win_rate, 1)}</td><td className={`r ${sign(r.avg_r)}`}>{num(r.avg_r, 3)}</td>
            <td className="r small">{r.avg_r_ci95 ? `${num(r.avg_r_ci95[0], 2)} to ${num(r.avg_r_ci95[1], 2)}` : "—"}</td>
            <td><span className={`tier t-${r.tier}`}>{TIER_TEXT[r.tier] || r.tier}</span></td></tr>)}</tbody></table>}
      </Panel>
    </div>
  );
}

// ======================= Journal =======================

const MISTAKE_TEXT: Record<string, string> = {
  late_entry: "Entered late", chasing: "Chased an extended move", early_exit: "Exited a winner early", held_loser: "Held a loser past the plan",
  ignored_stop: "No stop / removed the stop", bad_conditions: "Traded in unfavorable conditions", overtrading: "Too many trades",
  poor_setup: "Used a poorly performing setup",
};

function qs(f: Record<string, any>) {
  const p = new URLSearchParams();
  Object.entries(f).forEach(([k, v]) => { if (v !== "" && v !== null && v !== undefined) p.set(k, String(v)); });
  const s = p.toString();
  return s ? `?${s}` : "";
}

function Stat({ k, v, cls }: { k: string; v: any; cls?: string }) {
  return <div className="cell" style={{ padding: "8px 14px" }}><span className="k">{k}</span><span className={`v ${cls || ""}`}>{v}</span></div>;
}

function Breakdown({ title, rows }: { title: string; rows?: any[] }) {
  if (!rows?.length) return null;
  return (
    <Panel title={title} flush>
      <table><thead><tr><th /><th className="r">Trades</th><th className="r">Win %</th><th className="r">Avg R</th><th className="r">Net</th></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.bucket}><td>{r.bucket}</td><td className="r">{r.trades}</td><td className="r">{num(r.win_rate, 1)}</td>
          <td className={`r ${sign(r.avg_r)}`}>{num(r.avg_r, 2)}</td><td className={`r ${sign(r.net_pnl)}`}>{money(r.net_pnl, 0)}</td></tr>)}</tbody></table>
    </Panel>
  );
}

function TradeDetail({ t, onChange }: { t: any; onChange: () => void }) {
  const [note, setNote] = useState("");
  const [tags, setTags] = useState((t.tags || []).join(", "));
  const [err, setErr] = useState<string | null>(null);
  const add = async () => {
    try { await api(`/journal/trades/${t.key}/notes`, { method: "POST", json: { text: note } }); setNote(""); onChange(); }
    catch (e: any) { setErr(e.message); }
  };
  const meta = async (body: any) => { try { await api(`/journal/trades/${t.key}`, { method: "PATCH", json: body }); onChange(); } catch (e: any) { setErr(e.message); } };
  const del = async (id: number) => { await api(`/journal/notes/${id}`, { method: "DELETE" }); onChange(); };
  const sig = t.signal;
  const ctx = t.context || {};
  return (
    <div className="trade-detail">
      <div className="cols c-2">
        <div className="stack">
          <div className="levels">
            <div><div className="k">Entry</div><div className="v">{num(t.avg_entry)}</div></div>
            <div><div className="k">Exit</div><div className="v">{t.open ? `${num(t.mark)} (mark)` : num(t.avg_exit)}</div></div>
            <div><div className="k">Stop / target</div><div className="v">{num(t.stop)} / {num(t.target)}</div></div>
            <div><div className="k">Risked</div><div className="v">{t.risk_dollars != null ? money(t.risk_dollars, 0) : "unknown"}</div></div>
          </div>
          <div className="small muted">{t.qty} shares, held {num(t.hold_minutes, 0)} min, commissions {money(t.commissions)}, slippage {money(t.slippage)}.
            {t.open ? ` Unrealized ${money(t.unrealized_pnl)}.` : ""} Realized {money(t.realized_pnl)}.</div>
          <div>
            <div className="spread"><b className="small">Did it follow the plan?</b>
              <span className="row small">
                <span className={t.followed_plan ? "up" : "down"}>{t.followed_plan ? "Yes" : "No"}</span>
                <span className="faint">{t.followed_plan_user !== null && t.followed_plan_user !== undefined ? "(your verdict)" : "(automatic)"}</span>
                <button className="ghost small" onClick={() => meta({ followed_plan: true })}>Mark followed</button>
                <button className="ghost small" onClick={() => meta({ followed_plan: false })}>Mark broken</button>
                {t.followed_plan_user !== null && t.followed_plan_user !== undefined && <button className="ghost small" onClick={() => meta({ clear_followed_plan: true })}>Use automatic</button>}
              </span></div>
            <ul className="checks">{t.plan_checks.map((c: any) => <li key={c.check} className={c.passed === false ? "no" : ""}>
              <span className="m">{c.passed === null ? "·" : c.passed ? "✓" : "✗"}</span><span>{c.check} <span className="faint">{c.detail}</span></span></li>)}</ul>
          </div>
          {t.mistakes?.length > 0 && <div className="note warn">{t.mistakes.map((m: any, i: number) => <div key={i}><b>{m.label}.</b> {m.evidence}</div>)}</div>}
        </div>
        <div className="stack">
          <div className="small">
            <div><span className="muted">Strategy: </span>{t.strategy_name}{sig ? <> from a <Action a={sig.action} /> signal ({sig.state}), {sig.timeframe}</> : ""}</div>
            {sig && <div><span className="muted">Plan: </span>entry {num(sig.entry_range?.[0])}–{num(sig.entry_range?.[1])}, stop {num(sig.stop)}, targets {num(sig.targets?.t1)} / {num(sig.targets?.t2)}</div>}
            {sig && <div><span className="muted">Confidence then: </span>checklist {sig.confidence?.setup_quality ?? "—"}/100; evidence <span className={`tier t-${sig.evidence_tier}`}>{TIER_TEXT[sig.evidence_tier] || sig.evidence_tier}</span>{sig.confidence?.model_probability?.probability_of_profit != null ? `; model ${Math.round(sig.confidence.model_probability.probability_of_profit * 100)}%` : ""}</div>}
            <div><span className="muted">Conditions at entry: </span>regime {t.regime}{ctx.trend ? `, trend ${ctx.trend}` : ""}{ctx.trend_alignment ? ` (${ctx.trend_alignment})` : ""}
              {ctx.market?.bias ? `, SPY ${ctx.market.bias}` : ""}{ctx.market?.high_risk ? ", high-risk market" : ""}
              {ctx.data_label?.status ? `, data ${ctx.data_label.status}` : ""}{ctx.ext_from_ema9_atr != null ? `, ${ctx.ext_from_ema9_atr} ATR from 9 EMA` : ""}</div>
            <div><span className="muted">Time: </span>{etDate(t.opened_at)} {etTime(t.opened_at)} ET{t.closed_at ? ` to ${etTime(t.closed_at)} ET` : " (open)"}, {t.time_of_day}</div>
          </div>
          <label className="f">Tags<input value={tags} onChange={(e) => setTags(e.target.value)} onBlur={() => meta({ tags: tags.split(",").map((x: string) => x.trim()).filter(Boolean) })} placeholder="A+, patience, FOMO" /></label>
          <div className="stack" style={{ gap: 6 }}>
            {t.notes?.map((n: any) => <div key={n.id} className="journal-note"><div className="spread"><span className="small faint">{etDate(n.ts)} {etTime(n.ts)} ET</span>
              <button className="ghost small" onClick={() => del(n.id)} aria-label="Delete note">✕</button></div><div className="small" style={{ whiteSpace: "pre-wrap" }}>{n.text}</div></div>)}
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="What did you see? What would you do differently?" />
            <div className="row"><button onClick={add} disabled={!note.trim()}>Add note</button>{err && <span className="down small">{err}</span>}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function Journal() {
  const [f, setF] = useState<any>({ start: "", end: "", symbol: "", strategy: "", direction: "", mistake: "", followed: "" });
  const [tab, setTab] = useState("trades");
  const [open, setOpen] = useState<string | null>(null);
  const q = qs(f);
  const perf = usePoll(`/journal/performance${q}`, 30000, [q]);
  const trades = usePoll(`/journal/trades${q}`, 30000, [q]);
  const sigs = usePoll(tab === "signals" ? `/journal/signals${qs({ symbol: f.symbol, setup: f.strategy, start: f.start, end: f.end })}` : null, 30000, [tab, q]);
  const p = perf.data;
  const list: any[] = trades.data || [];
  const strategies = Array.from(new Set(list.map((t) => t.strategy))).sort();
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  const reload = () => { trades.reload(); perf.reload(); };
  return (
    <div className="page">
      <Panel title="Trading journal" sub="every practice trade and signal, recorded automatically">
        <div className="form">
          <label className="f">From<input type="date" value={f.start} onChange={set("start")} /></label>
          <label className="f">To<input type="date" value={f.end} onChange={set("end")} /></label>
          <label className="f">Ticker<input value={f.symbol} onChange={(e) => setF({ ...f, symbol: e.target.value.toUpperCase() })} placeholder="all" /></label>
          <label className="f">Strategy<select value={f.strategy} onChange={set("strategy")}><option value="">All</option>{strategies.map((s) => <option key={s}>{s}</option>)}</select></label>
          <label className="f">Direction<select value={f.direction} onChange={set("direction")}><option value="">Both</option><option value="long">Long</option><option value="short">Short</option></select></label>
          <label className="f">Mistake<select value={f.mistake} onChange={set("mistake")}><option value="">Any</option>{Object.entries(MISTAKE_TEXT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className="f">Plan<select value={f.followed} onChange={set("followed")}><option value="">Any</option><option value="true">Followed</option><option value="false">Broken</option></select></label>
        </div>
      </Panel>

      {p && p.closed_trades > 0 ? <>
        <section className="panel"><div className="strip" style={{ borderBottom: 0, flexWrap: "wrap" }}>
          <Stat k="Closed trades" v={p.closed_trades} /><Stat k="Win rate" v={`${p.win_rate}%`} />
          <Stat k="Avg winner" v={money(p.avg_winner)} cls="up" /><Stat k="Avg loser" v={money(p.avg_loser)} cls="down" />
          <Stat k="Profit factor" v={num(p.profit_factor)} /><Stat k="Expectancy" v={money(p.expectancy)} cls={sign(p.expectancy)} />
          <Stat k="Max drawdown" v={money(p.max_drawdown)} cls="down" /><Stat k="Total R" v={num(p.total_r, 2)} cls={sign(p.total_r)} />
          <Stat k="Avg R" v={num(p.avg_r, 3)} cls={sign(p.avg_r)} /><Stat k="Net P&L" v={money(p.net_pnl)} cls={sign(p.net_pnl)} />
        </div></section>
        {p.sample_warning && <div className="note warn">{p.sample_warning}</div>}
        {p.trades_without_risk > 0 && <div className="note">{p.trades_without_risk} trade(s) had no stop, so their R can't be measured and they're left out of the R figures.</div>}
        <div className="cols c-2">
          {p.equity_curve?.length > 1 && <Panel title="Cumulative P&L" sub="closed trades"><LineChart points={p.equity_curve.map((x: any) => [x.t, x.pnl])} height={200} /></Panel>}
          <Panel title="Mistakes you're making" sub="what each costs vs your clean trades" flush>
            {!p.mistakes?.length ? <div className="empty">No recurring mistakes detected in this selection.</div> :
              <table><thead><tr><th>Mistake</th><th className="r">Trades</th><th className="r">Net</th><th className="r">Avg R</th><th className="r">Clean trades avg R</th></tr></thead>
                <tbody>{p.mistakes.map((m: any) => <tr key={m.code} className="click" onClick={() => setF({ ...f, mistake: m.code })}><td>{m.label}</td><td className="r">{m.count} ({m.share_pct}%)</td>
                  <td className={`r ${sign(m.net_pnl)}`}>{money(m.net_pnl, 0)}</td><td className={`r ${sign(m.avg_r)}`}>{num(m.avg_r, 2)}</td><td className="r">{num(m.avg_r_clean_trades, 2)}</td></tr>)}</tbody></table>}
          </Panel>
          {p.best_strategy && <div className="note">Best strategy so far: <b>{p.best_strategy.bucket}</b> ({p.best_strategy.trades} trades, {money(p.best_strategy.net_pnl, 0)}).
            {p.worst_strategy && <> Worst: <b>{p.worst_strategy.bucket}</b> ({p.worst_strategy.trades} trades, {money(p.worst_strategy.net_pnl, 0)}).</>} Small samples: treat as hints.</div>}
        </div>
        <div className="cols c-2">
          <Breakdown title="By strategy" rows={p.by_strategy} /><Breakdown title="By ticker" rows={p.by_symbol} />
          <Breakdown title="By time of day" rows={p.by_time_of_day} /><Breakdown title="By market regime" rows={p.by_regime} />
          <Breakdown title="Long vs short" rows={p.by_direction} /><Breakdown title="Plan followed vs broken" rows={p.by_plan} />
        </div>
      </> : <div className="note">{p?.note || "Loading…"} Trades appear here automatically when you paper trade. Load a signal into the order ticket to link the trade to its plan.</div>}

      <Panel title={tab === "trades" ? "Trades" : "Signal log"} right={<div className="seg"><button className={tab === "trades" ? "on" : ""} onClick={() => setTab("trades")}>Trades</button>
        <button className={tab === "signals" ? "on" : ""} onClick={() => setTab("signals")}>Signals</button></div>} flush>
        {tab === "trades" ? (!list.length ? <div className="empty">No trades in this selection.</div> :
          <table><thead><tr><th>Opened</th><th>Ticker</th><th>Side</th><th>Strategy</th><th className="r">P&L</th><th className="r">R</th><th>Exit</th><th>Plan</th><th>Mistakes</th></tr></thead>
            <tbody>{list.map((t) => [
              <tr key={t.key} className="click" onClick={() => setOpen(open === t.key ? null : t.key)}>
                <td>{etDate(t.opened_at)} {etTime(t.opened_at)}</td><td className="sym">{t.symbol}</td><td>{t.direction}</td><td>{t.strategy_name}</td>
                <td className={`r ${sign(t.pnl)}`}>{money(t.pnl)}{t.open && <span className="small faint"> open</span>}</td>
                <td className={`r ${sign(t.r_multiple)}`}>{t.r_multiple != null ? num(t.r_multiple, 2) : "—"}</td><td>{t.exit_type}</td>
                <td className={t.followed_plan ? "up" : "down"}>{t.followed_plan ? "followed" : "broken"}</td>
                <td className="small">{t.mistakes?.map((m: any) => m.label).join(", ") || <span className="faint">none</span>}{t.notes?.length ? <span className="faint"> · {t.notes.length} note(s)</span> : ""}</td></tr>,
              open === t.key && <tr key={t.key + "-d"}><td colSpan={9} style={{ padding: 0 }}><TradeDetail t={t} onChange={reload} /></td></tr>,
            ])}</tbody></table>) :
          (!sigs.data?.length ? <div className="empty">No signals logged yet. Every setup the signal engine generates is logged here, with each change of state.</div> :
            <table><thead><tr><th>Time</th><th>Ticker</th><th>Setup</th><th>Action</th><th>State</th><th>Evidence</th><th className="r">Trigger / stop</th><th>Traded?</th></tr></thead>
              <tbody>{sigs.data.map((s: any) => <tr key={s.id} title={s.detail?.state_reason}><td>{etDate(s.ts)} {etTime(s.ts)}</td><td className="sym">{s.symbol}</td>
                <td>{s.detail?.setup_name || s.setup} <span className="faint small">{s.timeframe}</span></td><td><Action a={s.action} /></td><td>{s.state}</td>
                <td><span className={`tier t-${s.evidence_tier}`}>{TIER_TEXT[s.evidence_tier] || s.evidence_tier}</span></td>
                <td className="r">{num(s.detail?.trigger)} / {num(s.detail?.stop)}</td><td>{s.acted_on ? "yes" : ""}</td></tr>)}</tbody></table>)}
      </Panel>
    </div>
  );
}

// ======================= News & catalysts =======================

const CERT_TEXT: Record<string, string> = { confirmed: "Reported", speculative: "Unconfirmed", opinion: "Opinion", unclear: "Unclear" };

function NewsRow({ n }: { n: any }) {
  return (
    <div className={`news-row rel-${n.relevance}`}>
      <div className="spread small"><span className="faint">{n.published ? `${etDate(n.published)} ${etTime(n.published)} ET` : "time unknown"}, {n.source}</span>
        <span className="row" style={{ gap: 6 }}><span className={`cert c-${n.certainty}`} title={n.certainty_label}>{CERT_TEXT[n.certainty] || n.certainty}</span>
          <span className="faint">{n.category_label}</span></span></div>
      <div>{n.url ? <a href={n.url} target="_blank" rel="noreferrer noopener">{n.headline}</a> : n.headline}</div>
      {n.publisher_summary && <details><summary className="small">Publisher's summary (their words)</summary><p className="small muted">{n.publisher_summary}</p></details>}
      <div className="small faint">App's read (keyword rules, not AI): {n.relevance} relevance, {n.relevance_reason.toLowerCase()}.</div>
    </div>
  );
}

export function Catalysts({ symbol }: { symbol: string }) {
  const c = usePoll(`/news/${symbol}`, 600000, [symbol]);
  const [all, setAll] = useState(false);
  const d = c.data;
  const news: any[] = d?.news || [];
  const shown = all ? news : news.filter((n) => n.relevance !== "low");
  const e = d?.earnings;
  return (
    <Panel title="Catalysts" sub="Yahoo Finance news, earnings, analyst actions" right={<button className="ghost small" onClick={() => c.reload()}>Refresh</button>}>
      {!d ? <span className="muted small">{c.error || "Loading…"}</span> : <div className="stack">
        {d.events?.notes?.map((n: any, i: number) => <div key={i} className={`note ${d.events.gate ? "warn" : ""} small`}>{n.text} <span className="faint">({n.source})</span></div>)}
        {e?.next ? <div className="small"><b>Next earnings:</b> {e.next.date}{e.next.when ? `, ${e.next.when}` : ""} ({e.next.days_away} days). <span className="faint">{e.next.status}.</span>
          {e.next.eps_estimate != null && <> EPS estimate {num(e.next.eps_estimate)} (range {num(e.next.eps_range?.[0])}–{num(e.next.eps_range?.[1])}).</>}</div>
          : d.earnings && <div className="small muted">No upcoming earnings date listed by Yahoo.</div>}
        {e?.history?.length > 0 && <div className="small muted">Last reports: {e.history.slice(0, 4).map((h: any) => `${h.date} EPS ${h.eps_reported} vs ${h.eps_estimate} (${h.surprise_pct != null ? (h.surprise_pct > 0 ? "+" : "") + h.surprise_pct + "%" : "—"})`).join("; ")}.</div>}
        {d.analyst?.length > 0 && <details><summary className="small">Analyst actions, last 45 days ({d.analyst.length})</summary>
          {d.analyst.map((a: any) => <div key={a.id} className="small" style={{ padding: "2px 0" }}><span className="faint">{etDate(a.published)}</span> {a.headline}</div>)}</details>}
        {d.news_error && <div className="note warn small">{d.news_error}</div>}
        {d.news_note && <div className="small muted">{d.news_note}</div>}
        {shown.map((n) => <NewsRow key={n.id} n={n} />)}
        {news.length > shown.length && <button className="ghost small" onClick={() => setAll(true)}>Show {news.length - shown.length} low-relevance item(s) (opinion pieces, other tickers)</button>}
        {news.length > 0 && !shown.length && !all && <div className="small muted">Only low-relevance items right now (opinion pieces or stories mainly about other tickers).</div>}
        <div className="small faint">Headlines are not buy or sell signals. Positive news can sell off and negative news can rally.</div>
      </div>}
    </Panel>
  );
}

export function EconCalendar() {
  const c = usePoll("/calendar?days=14", 3600000);
  const d = c.data;
  return (
    <Panel title="Economic calendar" sub="next 14 days, ET" flush>
      {!d ? <div className="empty">{c.error || "Loading…"}</div> : <>
        {d.now?.notes?.map((n: any, i: number) => <div key={i} className={`note ${d.now.gate ? "warn" : ""} small`} style={{ margin: "8px 12px" }}>{n.text}</div>)}
        {!d.events.length ? <div className="empty">No scheduled high-impact releases in the next 14 days.</div> :
          <table><thead><tr><th>When (ET)</th><th>Release</th><th>Relevance</th><th>Last published (actual / previous)</th><th>Forecast</th></tr></thead>
            <tbody>{d.events.map((e: any, i: number) => <tr key={i}><td>{e.date.slice(5)} {e.time_et}</td>
            <td><a href={e.url} target="_blank" rel="noreferrer noopener">{e.event}</a><div className="small faint">{e.source}</div></td>
            <td className="small">{e.market_relevance || "-"}</td>
            <td className="small">{(e.published_values || []).length ? e.published_values.map((v: any) =>
              <div key={v.series_id}>{v.name}: <b>{v.actual}</b> {v.unit} ({v.period}{v.preliminary ? ", preliminary" : ""}) / {v.previous} ({v.previous_period})</div>)
              : <span className="faint">{e.kind?.startsWith("bls_") ? "not loaded" : "not tracked"}</span>}</td>
            <td className="small faint">not available</td></tr>)}</tbody></table>}
        {d.published_values && <div className="small faint" style={{ padding: "6px 12px" }}>
          Actual/previous from the BLS public data API{d.published_values.fetched_at ? `, fetched ${d.published_values.fetched_at.slice(0, 16).replace("T", " ")} UTC` : ""}.
          {d.published_values.error ? ` Last refresh failed (${d.published_values.error}); showing the last good copy if any.` : ""} Forecasts aren't shown: no official free source publishes them.
          The new figure appears here after BLS releases it (refreshed every 6 hours).</div>}
        {Object.keys(d.errors || {}).length > 0 && <div className="note warn small" style={{ margin: "8px 12px" }}>Couldn't refresh: {Object.keys(d.errors).join(", ")}. Showing the last good copy.</div>}
        {d.bls && <div className="small faint" style={{ padding: "6px 12px" }}>BLS dates bundled {d.bls.retrieved}, through {d.bls.last_date}. Signals go watch-only 15 min either side of major releases.</div>}
      </>}
    </Panel>
  );
}

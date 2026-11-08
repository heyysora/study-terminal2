// Futures (TopstepX) pages: dashboard, order ticket, prop-firm risk, replay, evidence, settings.
import { useEffect, useMemo, useState } from "react";
import { Action, CandleChart, Meter, Panel, PriceLine, TIER_TEXT } from "./components";
import { STATUS_TEXT, api, etDate, etTime, money, num, sign, usePoll } from "./lib";

const ctTime = new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", hour: "2-digit", minute: "2-digit", hour12: false });
const ct = (iso?: string) => (iso ? `${ctTime.format(new Date(iso))} CT` : "—");
const px = (v: any, d = 2) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));

export function FuturesPlan({ s, decimals = 2, onUse }: { s: any; decimals?: number; onUse?: (s: any) => void }) {
  if (!s) return null;
  const ev = s.evidence || {};
  return (
    <div className="sigcard">
      <div className="spread"><b>{s.setup?.replace(/_/g, " ")} · {s.direction}</b><span className={`tier t-${ev.tier || "none"}`}>{TIER_TEXT[ev.tier] || ev.tier || "untested"}</span></div>
      {s.label && <div className="note watch small">{s.label}</div>}
      {!s.tradeable_evidence && !s.label && <div className="note watch small"><b>Watch only.</b> Tested evidence: {s.evidence_short}. Study it; it isn't a trade call.</div>}
      <div className="levels">
        <div><div className="k">Entry</div><div className="v">{px(s.entry, decimals)}{s.entry_range && <span className="small faint"> ({px(s.entry_range[0], decimals)}–{px(s.entry_range[1], decimals)})</span>}</div></div>
        <div><div className="k">Stop</div><div className="v down">{px(s.stop, decimals)} <span className="small faint">{s.stop_ticks} ticks</span></div></div>
        <div><div className="k">Target</div><div className="v up">{px(s.target, decimals)} <span className="small faint">{s.reward_risk}R</span></div></div>
        <div><div className="k">Risk / contract</div><div className="v">{money(s.risk_per_contract_usd)}</div></div>
        <div><div className="k">Suggested size</div><div className="v">{s.suggested_contracts ?? "—"}</div></div>
      </div>
      <div className="small"><b>Why:</b> {s.conditions?.join("; ")}</div>
      <div className="small"><b>Invalidation:</b> {s.invalidation}</div>
      {s.next_level && <div className="small muted">Next level beyond target: {s.next_level.label} {px(s.next_level.price, decimals)}</div>}
      <div className="small muted">{s.sizing_note}</div>
      {s.risk_check?.problems?.length > 0 && <div className="note bad small">{s.risk_check.problems.join(" ")}</div>}
      {s.risk_check?.warnings?.length > 0 && <div className="note warn small">{s.risk_check.warnings.join(" ")}</div>}
      {onUse && <button className="small" onClick={() => onUse(s)}>Practice this plan in the simulator</button>}
    </div>
  );
}

export function DecisionSteps({ d }: { d: any }) {
  if (!d?.steps) return null;
  return (
    <details>
      <summary className="small">Decision pipeline: {d.outcome.replace("_", " ")} · {d.reason}</summary>
      <table className="small"><tbody>{d.steps.map((s: any) => <tr key={s.n}>
        <td style={{ width: 22 }} className={s.passed === false ? "down" : s.passed ? "up" : "faint"}>{s.passed === false ? "✗" : s.passed ? "✓" : "–"}</td>
        <td>{s.n}. {s.step}</td><td className="faint">{s.detail}</td></tr>)}</tbody></table>
      <div className="small faint">Decision {d.id} · bar {d.bar_time ? etTime(d.bar_time) + " ET" : "—"} · data {d.data?.provider} {d.data?.status} · evaluated {etTime(d.evaluated_at)} ET</div>
    </details>
  );
}

function RiskPanel({ acct, onChange }: { acct: any; onChange: () => void }) {
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  if (!acct) return null;
  const r = acct.risk || {};
  const o = r.official || {}, p = r.personal || {}, m = r.metrics || {};
  const act = async (f: () => Promise<any>) => { try { const x = await f(); setMsg(x?.note || "Done."); onChange(); } catch (e: any) { setMsg(e.message); } };
  return (
    <Panel title="Account and limits" sub={`${o.label || "No prop rules"} · simulator`} right={r.blocked ? <span className="act exit">Entries blocked</span> : <span className="act">Entries allowed</span>}>
      <div className="stack">
        <div className="levels">
          <div><div className="k">Balance</div><div className="v">{money(m.balance)}</div></div>
          <div><div className="k">Day P&amp;L</div><div className={`v ${sign(m.day_pnl)}`}>{money(m.day_pnl)}</div></div>
          <div><div className="k">Open risk</div><div className="v">{m.open_risk_usd == null ? "no stop!" : money(m.open_risk_usd)}</div></div>
          <div><div className="k">Contracts (mini-eq.)</div><div className="v">{num(m.open_mini_equivalent, 1)} / {m.max_mini_equivalent ?? "—"}</div></div>
        </div>
        <table><tbody>
          {o.mll_floor != null && <tr><td>Maximum Loss Limit floor</td><td className="r">{money(o.mll_floor)} <span className="small faint">{o.mll_locked ? "locked" : "end-of-day trailing"}</span></td></tr>}
          {o.mll_remaining != null && <tr><td>Room above the floor</td><td className={`r ${o.mll_remaining < 500 ? "down" : ""}`}>{money(o.mll_remaining)} ({num(o.mll_used_pct, 0)}% used)</td></tr>}
          {o.dll_remaining != null && <tr><td>Daily Loss Limit left</td><td className="r">{money(o.dll_remaining)}</td></tr>}
          {p.daily_loss_remaining != null && <tr><td>Your daily limit left</td><td className="r">{money(p.daily_loss_remaining)}</td></tr>}
          {o.profit_target && <tr><td>Profit target</td><td className="r">{money(o.profit)} of {money(o.profit_target, 0)} ({num(o.target_progress_pct, 0)}%)</td></tr>}
          {o.best_day_pct != null && <tr><td>Consistency (best day vs target)</td><td className={`r ${o.consistency_ok ? "" : "down"}`}>{num(o.best_day_pct, 0)}%</td></tr>}
          {o.minutes_to_flat != null && <tr><td>Minutes until you must be flat</td><td className="r">{num(o.minutes_to_flat, 0)}</td></tr>}
        </tbody></table>
        {!o.confirmed && o.enabled && <div className="note warn small">These prop-firm rules haven't been confirmed against your own account. Check them in Rules below.</div>}
        {r.warnings?.map((w: any) => <div key={w.code + w.text} className={`note ${w.level === "high" ? "bad" : "warn"} small`}>{w.text}</div>)}
        {r.blocks?.map((b: any) => <div key={b.code} className="note bad small"><b>{b.scope === "official" ? "Firm rule" : "Your rule"}:</b> {b.text}{b.until && <> Resets {etDate(b.until)} {ct(b.until)}.</>}</div>)}
        {r.blocks?.some((b: any) => b.needs_review && b.scope === "personal") && <div className="row">
          <input style={{ flex: 1 }} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What happened? (required to unlock)" aria-label="Review note" />
          <button onClick={() => act(() => api("/futures/risk/review", { method: "POST", json: { note } }))} disabled={note.trim().length < 10}>Log review and unlock</button></div>}
        <div className="small faint">{r.sim_only_note}</div>
        <div className="row">
          <button onClick={() => act(() => api("/futures/paper/flatten", { method: "POST", json: {} }))}>Flatten all</button>
          <button className="danger" onClick={() => confirm("Reset the simulated futures account? Its history is erased.") && act(() => api("/futures/paper/reset", { method: "POST", json: { confirm: true } }))}>Reset account</button>
        </div>
        {msg && <div className="note small">{msg}</div>}
      </div>
    </Panel>
  );
}

function Ticket({ contract, spec, prefill, replay, onDone }: { contract: string; spec: any; prefill?: any; replay?: boolean; onDone: () => void }) {
  const [f, setF] = useState<any>({ side: 1, qty: 1, type: "market", limit: "", stop: "", target: "" });
  const [pv, setPv] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (prefill) setF({ side: prefill.direction === "long" ? 1 : -1, qty: prefill.suggested_contracts || 1, type: "limit", limit: prefill.entry, stop: prefill.stop, target: prefill.target });
  }, [prefill]);
  const body = () => ({
    contract, side: f.side, qty: Number(f.qty), type: f.type, limit_price: f.type === "limit" ? Number(f.limit) : null, stop_price: f.type === "stop" ? Number(f.limit) : null,
    bracket: { stop: f.stop === "" ? null : Number(f.stop), targets: f.target === "" ? [] : [{ price: Number(f.target), qty: Number(f.qty) }] },
  });
  const preview = async () => { setErr(null); try { setPv(await api("/futures/paper/preview", { method: "POST", json: body() })); } catch (e: any) { setErr(e.message); } };
  const submit = async () => {
    setErr(null);
    try {
      const r = await api(replay ? "/futures/replay/orders" : "/futures/paper/orders", { method: "POST", json: { ...body(), confirm: true } });
      if (!r.order) { setPv(r.preview); return; }
      setPv(null); onDone();
    } catch (e: any) { setErr(e.message); }
  };
  const tick = spec?.tick_size;
  return (
    <Panel title={replay ? "Replay order" : "Paper order"} sub={`${contract} · tick ${tick} = ${money(spec?.tick_value)}`}>
      <div className="stack">
        <div className="row">
          <button className={f.side === 1 ? "primary" : ""} onClick={() => setF({ ...f, side: 1 })}>Buy</button>
          <button className={f.side === -1 ? "primary" : ""} onClick={() => setF({ ...f, side: -1 })}>Sell</button>
          <label className="f">Contracts<input type="number" min={1} value={f.qty} onChange={(e) => setF({ ...f, qty: e.target.value })} /></label>
          <label className="f">Type<select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}><option value="market">Market</option><option value="limit">Limit</option><option value="stop">Stop</option></select></label>
          {f.type !== "market" && <label className="f">{f.type === "limit" ? "Limit" : "Stop"} price<input type="number" step={tick} value={f.limit} onChange={(e) => setF({ ...f, limit: e.target.value })} /></label>}
        </div>
        <div className="row">
          <label className="f">Stop loss<input type="number" step={tick} value={f.stop} onChange={(e) => setF({ ...f, stop: e.target.value })} /></label>
          <label className="f">Target<input type="number" step={tick} value={f.target} onChange={(e) => setF({ ...f, target: e.target.value })} /></label>
        </div>
        <div className="row">{!replay && <button onClick={preview}>Review</button>}<button className="primary" onClick={submit} disabled={!replay && !pv?.ok}>Place {replay ? "replay" : "paper"} order</button></div>
        {pv && <div className="stack small">
          {pv.risk && <div>Risk: {pv.risk.stop_ticks} ticks, {money(pv.risk.trade_risk_usd)} incl. slippage and fees{pv.risk.reward_risk ? `, ${pv.risk.reward_risk}R to target` : ""}. Est. fees {money(pv.est_fees_round_turn)}.</div>}
          {pv.problems?.map((p: string) => <div key={p} className="note bad">{p}</div>)}
          {pv.warnings?.map((p: string) => <div key={p} className="note warn">{p}</div>)}
        </div>}
        {err && <div className="note bad small">{err}</div>}
        <div className="small faint">Simulator only. Nothing is sent to TopstepX or any broker.</div>
      </div>
    </Panel>
  );
}

function Orders({ acct, onChange, decimals }: { acct: any; onChange: () => void; decimals: number }) {
  if (!acct) return null;
  const cancel = async (id: string) => { await api(`/futures/paper/orders/${id}`, { method: "DELETE" }); onChange(); };
  return (
    <Panel title="Positions, orders and fills" flush>
      <table><thead><tr><th>Contract</th><th className="r">Qty</th><th className="r">Avg</th><th className="r">Mark</th><th className="r">Unrealized</th><th>Mark data</th></tr></thead>
        <tbody>{acct.positions.length === 0 ? <tr><td colSpan={6} className="muted">No open positions.</td></tr> : acct.positions.map((p: any) =>
          <tr key={p.contract}><td>{p.contract}</td><td className="r">{p.qty}</td><td className="r">{px(p.avg_price, decimals)}</td><td className="r">{px(p.mark, decimals)}</td>
            <td className={`r ${sign(p.unrealized)}`}>{money(p.unrealized)}</td><td className="small">{STATUS_TEXT[p.mark_status] || p.mark_status}</td></tr>)}</tbody></table>
      <table><thead><tr><th>Working order</th><th className="r">Qty</th><th className="r">Price</th><th>Role</th><th /></tr></thead>
        <tbody>{acct.working_orders.length === 0 ? <tr><td colSpan={5} className="muted">No working orders.</td></tr> : acct.working_orders.map((o: any) =>
          <tr key={o.id}><td>{o.side > 0 ? "BUY" : "SELL"} {o.contract} {o.type}</td><td className="r">{o.filled_qty}/{o.qty}</td><td className="r">{px(o.limit_price ?? o.stop_price, decimals)}</td>
            <td>{o.role.replace("_", " ")}</td><td><button className="ghost small" onClick={() => cancel(o.id)}>Cancel</button></td></tr>)}</tbody></table>
      <table><thead><tr><th>Fill</th><th className="r">Price</th><th className="r">Fee</th><th className="r">Realized</th><th>Basis</th></tr></thead>
        <tbody>{acct.fills.slice(0, 12).map((x: any) => <tr key={x.id}><td>{etTime(x.ts)} {x.side > 0 ? "BUY" : "SELL"} {x.qty} {x.contract} ({x.role.replace("_", " ")})</td>
          <td className="r">{px(x.price, decimals)}</td><td className="r">{money(x.fee)}</td><td className={`r ${sign(x.realized)}`}>{x.realized ? money(x.realized) : ""}</td><td className="small faint">{x.basis}{x.fee_note ? `. ${x.fee_note}` : ""}</td></tr>)}</tbody></table>
    </Panel>
  );
}

function levelLines(L: any): PriceLine[] {
  if (!L) return [];
  const m: [string, string, string, boolean?][] = [["vwap", "VWAP", "#d4a24c"], ["prev_day_high", "PDH", "#8aa4c8", true], ["prev_day_low", "PDL", "#8aa4c8", true],
    ["overnight_high", "ONH", "#7f8fa6", true], ["overnight_low", "ONL", "#7f8fa6", true], ["opening_range_high", "ORH", "#a58fd0"], ["opening_range_low", "ORL", "#a58fd0"],
    ["ib_high", "IBH", "#5aa7a0", true], ["ib_low", "IBL", "#5aa7a0", true]];
  return m.filter(([k]) => L[k] != null).map(([k, t, c, d]) => ({ price: L[k], title: t, color: c, dashed: d }));
}

function LevelsTable({ L, decimals }: { L: any; decimals: number }) {
  if (!L) return null;
  const row = (k: string, label: string) => L[k] != null && <tr key={k}><td>{label}</td><td className="r num">{px(L[k], decimals)}</td></tr>;
  const vp = L.profile_prev_rth;
  return (
    <Panel title="Session levels" sub={`trade date ${L.trade_date}`} flush>
      <table><tbody>
        {row("vwap", "Session VWAP")}{row("vwap_upper_1sd", "VWAP +1σ")}{row("vwap_lower_1sd", "VWAP −1σ")}{row("rth_vwap", "RTH VWAP")}
        {row("prev_day_high", "Previous day high (RTH)")}{row("prev_day_low", "Previous day low (RTH)")}{row("prev_day_close", "Previous day close (RTH)")}
        {row("prev_session_high", "Previous session high (Globex)")}{row("prev_session_low", "Previous session low (Globex)")}
        {row("overnight_high", "Overnight high")}{row("overnight_low", "Overnight low")}{row("premarket_high", "Pre-RTH hour high")}{row("premarket_low", "Pre-RTH hour low")}
        {row("opening_range_high", "Opening range high (15 min)")}{row("opening_range_low", "Opening range low")}{row("ib_high", "Initial balance high (60 min)")}{row("ib_low", "Initial balance low")}
        {vp && <tr><td>Prior RTH profile: POC / VAH / VAL</td><td className="r num">{px(vp.poc, decimals)} / {px(vp.vah, decimals)} / {px(vp.val, decimals)}</td></tr>}
        {vp?.hvn?.length > 0 && <tr><td>High-volume nodes</td><td className="r num">{vp.hvn.map((x: number) => px(x, decimals)).join(", ")}</td></tr>}
        {vp?.lvn?.length > 0 && <tr><td>Low-volume nodes</td><td className="r num">{vp.lvn.map((x: number) => px(x, decimals)).join(", ")}</td></tr>}
        <tr><td>Structure</td><td className="r">{L.trend}</td></tr>
        {L.structure?.slice(0, 3).map((s: any) => <tr key={s.ts}><td className="small">{s.kind}</td><td className="r small">{etTime(s.ts)} ET at {px(s.price, decimals)}</td></tr>)}
        {L.fvgs?.slice(0, 3).map((g: any) => <tr key={g.formed}><td className="small">Unfilled {g.kind} FVG</td><td className="r small num">{px(g.low, decimals)}–{px(g.high, decimals)}</td></tr>)}
        {L.sweeps?.slice(0, 3).map((s: any, i: number) => <tr key={i}><td className="small" colSpan={2}>{s.text}</td></tr>)}
      </tbody></table>
      {vp && <div className="small faint" style={{ padding: "6px 10px" }}>{vp.note}</div>}
    </Panel>
  );
}

function Replay({ symbol, spec }: { symbol: string; spec: any }) {
  const [day, setDay] = useState("");
  const [st, setSt] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const call = async (path: string, json: any) => { setErr(null); try { setSt(await api(path, { method: "POST", json })); } catch (e: any) { setErr(e.message); } };
  const bars = useMemo(() => (st?.chart || []).map((b: any) => ({ time: b.t, open: b.o, high: b.h, low: b.l, close: b.c, volume: b.v })), [st]);
  const d = spec?.decimals ?? 2;
  return (
    <div className="stack">
      <Panel title="Replay a past session" sub="practice without live data; a separate simulated account">
        <div className="row">
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)} aria-label="Trade date" />
          <button className="primary" disabled={!day} onClick={() => call("/futures/replay/start", { symbol, trade_date: day })}>Load {symbol}</button>
          {st && <>{[1, 5, 15, 60].map((n) => <button key={n} onClick={() => call("/futures/replay/step", { bars: n })}>+{n} bar{n > 1 ? "s" : ""}</button>)}
            <button onClick={async () => { await api("/futures/replay/flatten", { method: "POST" }); call("/futures/replay/step", { bars: 0 }); }}>Flatten</button></>}
        </div>
        {err && <div className="note bad small">{err}</div>}
        {st && <div className="small muted">{st.contract} · {etDate(st.bar_time)} {ct(st.bar_time)} · bar {st.progress.i} of {st.progress.of} ({st.timeframe}) · last {px(st.last, d)} · {st.note}</div>}
      </Panel>
      {st && <>
        <CandleChart bars={bars} lines={levelLines(st.levels)} height={380} />
        <div className="cols c-2">
          <Panel title="Signal at this bar" right={<Action a={st.signal.action} />}>
            <div className="small">{st.signal.reasons.join(" ")}</div>
            {(st.signal.signal || st.signal.watch?.[0]) && <FuturesPlan s={st.signal.signal || st.signal.watch[0]} decimals={d} />}
          </Panel>
          <Panel title="Replay account">
            <div className="levels"><div><div className="k">Balance</div><div className="v">{money(st.account.balance)}</div></div>
              <div><div className="k">Unrealized</div><div className={`v ${sign(st.account.unrealized)}`}>{money(st.account.unrealized)}</div></div></div>
            {st.account.fills.slice(0, 6).map((x: any) => <div key={x.id} className="small">{x.side > 0 ? "BUY" : "SELL"} {x.qty} @ {px(x.price, d)} ({x.role.replace("_", " ")})</div>)}
          </Panel>
        </div>
        <Ticket contract={st.contract} spec={spec} replay onDone={() => call("/futures/replay/step", { bars: 0 })} />
      </>}
    </div>
  );
}

function EvidencePanel({ root, info, onRun }: { root: string; info: any; onRun: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ev = info?.evidence?.[root];
  const run = async (kind: "research" | "backtest") => {
    setBusy(kind); setErr(null);
    try { await api(`/futures/${kind}`, { method: "POST", json: { root } }); onRun(); } catch (e: any) { setErr(e.message); } finally { setBusy(null); }
  };
  const o = ev?.oos_metrics, h = ev?.holdout_metrics;
  const M = ({ m, title }: { m: any; title: string }) => !m?.trades ? <div className="small muted">{title}: no trades.</div> : (
    <div><div className="small"><b>{title}</b></div><div className="levels">
      <div><div className="k">Trades / days</div><div className="v">{m.trades} / {m.days}</div></div>
      <div><div className="k">Win rate</div><div className="v">{m.win_rate}%</div></div>
      <div><div className="k">Avg R</div><div className={`v ${sign(m.avg_r)}`}>{num(m.avg_r, 3)}{m.avg_r_ci95 ? <span className="small faint"> ({num(m.avg_r_ci95[0], 2)} to {num(m.avg_r_ci95[1], 2)})</span> : null}</div></div>
      <div><div className="k">Profit factor</div><div className="v">{m.profit_factor ?? "—"}</div></div>
    </div><div className="small faint">Avg winner {num(m.avg_winner_r, 2)}R ({money(m.avg_winner_usd)}), avg loser {num(m.avg_loser_r, 2)}R ({money(m.avg_loser_usd)}), expectancy {money(m.expectancy_usd)}, max drawdown {money(m.max_drawdown_usd)} ({m.max_drawdown_r}R), avg cost {money(m.avg_cost_usd)}.</div></div>);
  return (
    <Panel title={`Strategy research: ${root}`} sub="walk-forward + holdout, ~59 days of 5-minute bars, after costs"
      right={<div className="row"><button onClick={() => run("research")} disabled={!!busy}>{busy === "research" ? "Researching… (several minutes)" : "Run research"}</button>
        <button className="ghost" onClick={() => run("backtest")} disabled={!!busy}>{busy === "backtest" ? "Testing…" : "Quick backtest"}</button></div>}>
      {err && <div className="note bad small">{err}</div>}
      {!ev ? <div className="small muted">Not tested yet. Until research validates a strategy, futures setups stay watch-only.</div> : <div className="stack small">
        {ev.run?.bundled && <div className="note warn small">{ev.run.note}</div>}
        <div className="row"><span className={`tier t-${ev.overall?.tier}`}>{TIER_TEXT[ev.overall?.tier]}</span>
          <span>Validated strategies: {ev.validated?.length ? ev.validated.join(", ") : "none"}. Mode B trades only validated strategies.</span></div>
        {o && <M m={o} title={`Out-of-sample (${ev.data?.development || "development folds"})`} />}
        {h && <M m={h} title={`Holdout, never used for choices (${ev.data?.holdout})`} />}
        {ev.registry && <table><thead><tr><th>Setup</th><th className="r">OOS trades</th><th className="r">OOS avg R</th><th className="r">Holdout</th><th>Status</th></tr></thead><tbody>
          {Object.entries(ev.registry).map(([k, r]: any) => <tr key={k}><td>{k.replace("|", " · ").replace(/_/g, " ")}</td><td className="r">{ev.by_setup?.[k]?.trades}</td>
            <td className={`r ${sign(ev.by_setup?.[k]?.avg_r)}`}>{num(ev.by_setup?.[k]?.avg_r, 2)}</td><td className="r">{ev.holdout_by_setup?.[k]?.trades ?? 0} / {num(ev.holdout_by_setup?.[k]?.avg_r, 2)}</td>
            <td title={r.why}><span className={r.status === "validated" ? "up" : "faint"}>{r.status}</span></td></tr>)}</tbody></table>}
        {!ev.registry && ev.by_setup && <div className="faint">Quick backtest only (no walk-forward). Run research to evaluate strategies for automation.</div>}
        {ev.diagnostics && <details><summary>Diagnostics (out-of-sample)</summary>{["volatility", "time_of_day", "trend_aligned", "volume", "vs_vwap"].map((dim) =>
          <div key={dim}><b>{dim.replace(/_/g, " ")}:</b> {(ev.diagnostics[dim] || []).map((x: any) => `${x.bucket} ${num(x.avg_r, 2)}R (${x.trades})`).join(" · ")}</div>)}</details>}
        {ev.cost_sensitivity && <div className="faint">Cost sensitivity (all dates): {Object.entries(ev.cost_sensitivity).map(([k, m]: any) => `${k}: ${num(m.avg_r, 3)}R`).join(" · ")}</div>}
        <div className="faint">{ev.run?.source}, run {ev.run?.at ? etDate(ev.run.at) : ""}. {ev.run?.note} {ev.run?.fee_note}</div>
      </div>}
    </Panel>
  );
}

export function FuturesRules({ info, onChange }: { info: any; onChange: () => void }) {
  const [prop, setProp] = useState<any>(null);
  const [pers, setPers] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { if (info) { setProp(info.prop); setPers(info.personal); } }, [info]);
  if (!info || !prop || !pers) return <div className="muted">Loading…</div>;
  const presets = info.presets;
  const put = async (path: string, json: any, ok = "Saved.") => { try { await api(path, { method: path.includes("preset") ? "POST" : "PUT", json }); setMsg(ok); onChange(); } catch (e: any) { setMsg(e.message); } };
  const nf = (obj: any, set: (x: any) => void, k: string, label: string) => <label className="f">{label}<input type="number" value={obj[k] ?? ""} placeholder="off"
    onChange={(e) => set({ ...obj, [k]: e.target.value === "" ? null : Number(e.target.value) })} /></label>;
  const tf = (obj: any, set: (x: any) => void, k: string, label: string) => <label className="f">{label}<input value={obj[k] ?? ""} placeholder="off" onChange={(e) => set({ ...obj, [k]: e.target.value || null })} /></label>;
  return (
    <div className="cols c-2">
      <Panel title="Prop-firm rules (official)" sub={prop.confirmed ? `confirmed ${prop.confirmed_at ? etDate(prop.confirmed_at) : ""}` : "not confirmed yet"}>
        <div className="stack">
          <label className="f">Start from a preset<select value={prop.preset_id} onChange={(e) => put("/futures/risk/preset", { preset_id: e.target.value }, "Preset loaded. Check each number, then confirm.")}>
            {presets.presets.map((p: any) => <option key={p.id} value={p.id}>{p.label}</option>)}</select></label>
          <div className="form">
            {nf(prop, setProp, "starting_balance", "Starting balance")}{nf(prop, setProp, "max_loss_limit", "Maximum Loss Limit ($)")}
            <label className="f">Drawdown type<select value={prop.mll_type} onChange={(e) => setProp({ ...prop, mll_type: e.target.value })}>
              <option value="eod_trailing">End-of-day trailing</option><option value="intraday_trailing">Intraday trailing</option><option value="static">Static</option></select></label>
            {nf(prop, setProp, "mll_lock_balance", "Trailing stops at balance")}{nf(prop, setProp, "daily_loss_limit", "Daily Loss Limit ($)")}
            {nf(prop, setProp, "profit_target", "Profit target ($)")}{nf(prop, setProp, "consistency_pct", "Consistency: best day ≤ % of target")}
            {nf(prop, setProp, "max_minis", "Max contracts (minis)")}{nf(prop, setProp, "micro_ratio", "Micros per mini")}
            {tf(prop, setProp, "flat_by_ct", "Flat by (CT)")}{tf(prop, setProp, "no_new_entries_after_ct", "No new entries after (CT)")}
          </div>
          <label className="check"><input type="checkbox" checked={!!prop.enabled} onChange={(e) => setProp({ ...prop, enabled: e.target.checked })} />Apply these rules to the simulator</label>
          <div className="row"><button onClick={() => put("/futures/risk/prop", { values: prop })}>Save</button>
            <button className="primary" onClick={() => put("/futures/risk/prop", { values: prop, confirm: true }, "Confirmed.")}>I checked these against my Topstep account: confirm</button></div>
          <div className="small muted">Starting values come from Topstep's help center as of {presets.verified_on}. Rules change, so check your own dashboard. Study Terminal applies them to its simulator only; it can't enforce anything on your real account.</div>
          <details><summary className="small">Sources and notes</summary>
            <ul className="small">{presets.topstep_sources.map((s: any) => <li key={s.url}>{s.what}: <a href={s.url} target="_blank" rel="noreferrer">{s.url.replace("https://", "")}</a></li>)}</ul>
            <ul className="small">{presets.topstep_notes.map((n: string) => <li key={n}>{n}</li>)}</ul></details>
        </div>
      </Panel>
      <Panel title="Your own limits (personal)" sub="separate from the firm's rules; usually tighter">
        <div className="stack">
          <div className="form">
            {nf(pers, setPers, "max_risk_per_trade_usd", "Max risk per trade ($)")}{nf(pers, setPers, "max_daily_loss_usd", "Max daily loss ($)")}
            {nf(pers, setPers, "max_contracts", "Max contracts (mini-eq.)")}{nf(pers, setPers, "max_consecutive_losses", "Losses in a row before a break")}
            {nf(pers, setPers, "daily_profit_target_usd", "Stop for the day at profit ($)")}{nf(pers, setPers, "min_reward_risk", "Minimum reward:risk")}
            {nf(pers, setPers, "max_open_risk_usd", "Max total open risk ($)")}
          </div>
          <label className="check"><input type="checkbox" checked={!!pers.require_stop} onChange={(e) => setPers({ ...pers, require_stop: e.target.checked })} />Every entry needs a stop</label>
          <label className="check"><input type="checkbox" checked={!!pers.rth_only} onChange={(e) => setPers({ ...pers, rth_only: e.target.checked })} />Regular hours only</label>
          <label className="check"><input type="checkbox" checked={!!pers.enabled} onChange={(e) => setPers({ ...pers, enabled: e.target.checked })} />Apply my limits</label>
          <button onClick={() => put("/futures/risk/personal", pers)}>Save my limits</button>
        </div>
      </Panel>
      {msg && <div className="note">{msg}</div>}
    </div>
  );
}

export function FuturesSettings() {
  const s = usePoll("/settings");
  const info = usePoll("/futures/info");
  const px_ = usePoll("/futures/projectx/check");
  const [v, setV] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { if (s.data && !v) setV(s.data.values); }, [s.data, v]);
  if (!v || !info.data) return <div className="muted">Loading…</div>;
  const save = async (ch: any) => { try { const r = await api("/settings", { method: "PUT", json: ch }); setV(r.values); setMsg("Saved."); info.reload(); } catch (e: any) { setMsg(e.message); } };
  const paper = { slippage_ticks_market: 1, slippage_ticks_stop: 1, participation: 0.1, auto_flatten: true, allow_delayed_practice: false, ...(v["futures.paper"] || {}) };
  const fees = v["futures.fees"] || {};
  return (
    <div className="cols c-2">
      <Panel title="Futures data" sub={`using ${info.data.data_source}`}>
        <div className="stack">
          <label className="f">Source<select value={v["futures.data_source"]} onChange={(e) => save({ "futures.data_source": e.target.value })}>
            <option value="yahoo">Yahoo Finance (free, delayed)</option><option value="projectx" disabled={!info.data.projectx_configured}>TopstepX API (your subscription)</option></select></label>
          <div className="small muted">TopstepX API: {px_.data?.detail || "checking…"}</div>
          <label className="check"><input type="checkbox" checked={!!v["futures.projectx_read_account"]} onChange={(e) => save({ "futures.projectx_read_account": e.target.checked })} />Let Study Terminal read my TopstepX account balances (read-only)</label>
          <table className="small"><thead><tr><th>Source</th><th>Real-time</th><th>Cost</th><th>In this app</th></tr></thead>
            <tbody>{info.data.sources.map((x: any) => <tr key={x.id}><td>{x.name}</td><td>{x.realtime}</td><td>{x.cost}</td><td>{x.status_in_app}</td></tr>)}</tbody></table>
        </div>
      </Panel>
      <Panel title="Futures simulator">
        <div className="stack">
          <div className="form">
            {(["slippage_ticks_market", "slippage_ticks_stop", "participation"] as const).map((k) => <label key={k} className="f">{({ slippage_ticks_market: "Market slippage (ticks)", slippage_ticks_stop: "Stop slippage (ticks)", participation: "Max share of bar volume per fill" } as any)[k]}
              <input type="number" step="any" value={paper[k]} onChange={(e) => save({ "futures.paper": { ...paper, [k]: Number(e.target.value) } })} /></label>)}
          </div>
          <label className="check"><input type="checkbox" checked={paper.auto_flatten} onChange={(e) => save({ "futures.paper": { ...paper, auto_flatten: e.target.checked } })} />Flatten automatically at the flat-by time</label>
          <label className="check"><input type="checkbox" checked={paper.allow_delayed_practice} onChange={(e) => save({ "futures.paper": { ...paper, allow_delayed_practice: e.target.checked } })} />Practice on delayed prices (fills are labeled and won't match the live market)</label>
          <h3>Fees (round turn per contract)</h3>
          <div className="form">{info.data.products.map((p: any) => <label key={p.root} className="f">{p.root}<input type="number" step="0.01" value={fees[p.root] ?? ""} placeholder={info.data.fees_default[p.root] != null ? String(info.data.fees_default[p.root]) : "not set"}
            onChange={(e) => save({ "futures.fees": { ...fees, [p.root]: e.target.value === "" ? undefined : Number(e.target.value) } })} /></label>)}</div>
          <div className="small faint">Placeholders are TopstepX's published totals (help.topstep.com). Products marked "not set" are charged the commission only, and fills say so.</div>
        </div>
      </Panel>
      {msg && <div className="note">{msg}</div>}
    </div>
  );
}

export function Futures({ symbol }: { symbol?: string }) {
  const settings = usePoll("/settings");
  const watch: string[] = settings.data?.values?.["futures.watch"] || ["ES", "NQ", "CL", "GC"];
  const [sym, setSym] = useState(symbol || "");
  const [input, setInput] = useState("");
  const [tab, setTab] = useState(symbol ? "live" : "live");
  const [prefill, setPrefill] = useState<any>(null);
  useEffect(() => { if (!sym && settings.data) setSym(settings.data.values["futures.default_root"] || "MES"); }, [settings.data, sym]);
  const d = usePoll(sym ? `/futures/dashboard?symbol=${encodeURIComponent(sym)}` : null, 20000, [sym]);
  const info = usePoll("/futures/info");
  const x = d.data;
  const spec = x?.spec;
  const dec = spec?.decimals ?? 2;
  const bars = useMemo(() => (x?.chart || []).map((b: any) => ({ time: b.t, open: b.o, high: b.h, low: b.l, close: b.c, volume: b.v })), [x]);
  const lines = useMemo(() => levelLines(x?.levels), [x]);
  const sig = x?.signal;
  const plan = sig?.signal || sig?.watch?.[0] || sig?.study_only?.[0];
  const reload = () => { d.reload(); info.reload(); };
  return (
    <div className="page">
      <div className="spread">
        <div className="row">
          {Array.from(new Set([...watch, "MES", "MNQ"])).map((r) => <button key={r} className={sym === r ? "primary" : ""} onClick={() => setSym(r)}>{r}</button>)}
          <form onSubmit={(e) => { e.preventDefault(); if (input.trim()) setSym(input.trim().toUpperCase()); }}><input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Contract, e.g. MNQZ26" aria-label="Contract" style={{ width: 160 }} /></form>
        </div>
        <div className="row">{["live", "rules", "replay", "evidence", "settings"].map((t) => <button key={t} className={tab === t ? "primary" : "ghost"} onClick={() => setTab(t)}>{({ live: "Live", rules: "Rules", replay: "Replay", evidence: "Evidence", settings: "Data & simulator" } as any)[t]}</button>)}</div>
      </div>
      {d.error && <div className="note bad">{d.error}</div>}
      {tab === "rules" && <FuturesRules info={info.data} onChange={reload} />}
      {tab === "settings" && <FuturesSettings />}
      {tab === "replay" && x && <Replay symbol={x.contract.code} spec={spec} />}
      {tab === "evidence" && x && <EvidencePanel root={x.contract.root} info={info.data} onRun={reload} />}
      {tab === "live" && (!x ? <div className="muted">{d.loading ? "Loading futures data…" : "Pick a product."}</div> : <>
        <div className="strip-lite row">
          <b>{x.contract.code}</b><span className="muted">{spec.name}</span>
          <span>Last {px(x.levels?.last, dec)}</span>
          <Meter withText status={x.data.status} reason={x.data.reason} />
          <span className="small muted">{x.session.label}{x.session.minutes_to_close != null ? ` · ${num(x.session.minutes_to_close, 0)} min to close` : ""}{x.session.reason ? ` · ${x.session.reason}` : ""}</span>
          <span className="small muted">Expires {x.contract.last_trade_date}{x.contract.in_roll_window ? " · past roll date" : ` · roll ${x.contract.roll_date}`}</span>
          <span className="small muted">Tick {spec.tick_size} = {money(spec.tick_value)} · 1 pt = {money(spec.point_value)}</span>
        </div>
        <div className={`note ${x.data.status === "delayed" || x.data.status === "stale" ? "warn" : ""} small`}>{x.data.reason} {x.data_notes?.join(" ")}</div>
        <div className="cols c-main">
          <div className="stack">
            <CandleChart bars={bars} lines={lines} height={420} />
            <Panel title="Signal" sub={`${sig?.timeframe} · last closed bar ${sig?.market_data_time ? etTime(sig.market_data_time) + " ET" : "—"}`} right={<Action a={sig?.action} />}>
              <div className="stack">
                <div className="small">{sig?.reasons?.join(" ")}</div>
                {plan && <FuturesPlan s={plan} decimals={dec} onUse={(s) => setPrefill({ ...s })} />}
                {sig?.position && <div className="note small">{sig.position.reasons.join(" ")}</div>}
                <DecisionSteps d={sig?.decision} />
                {sig?.developing?.length > 0 && <div className="small muted">{sig.developing.map((t: string) => <div key={t}>{t}</div>)}</div>}
                {sig?.rejected?.length > 0 && <details><summary className="small">Setups considered and rejected</summary>{sig.rejected.map((t: string) => <div key={t} className="small faint">{t}</div>)}</details>}
                <div className="small faint">{sig?.sim_note}</div>
              </div>
            </Panel>
            <Orders acct={x.account} onChange={reload} decimals={dec} />
          </div>
          <div className="stack">
            <RiskPanel acct={x.account} onChange={reload} />
            <Ticket contract={x.contract.code} spec={spec} prefill={prefill} onDone={reload} />
            <LevelsTable L={x.levels} decimals={dec} />
            <Panel title="High-impact events (3 days)">
              {x.upcoming_events?.length ? x.upcoming_events.map((e: any) => <div key={e.event + e.date} className="small">{e.date} {e.time_et} ET · {e.event}</div>)
                : <div className="small muted">None listed (or the economic calendar is off).</div>}
            </Panel>
          </div>
        </div>
      </>)}
    </div>
  );
}

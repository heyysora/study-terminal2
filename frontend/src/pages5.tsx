import { Fragment, useState } from "react";
import { Action, Meter, Panel } from "./components";
import { api, money, usePoll } from "./lib";
import { DecisionSteps } from "./pages4";

const STATUS_TEXT: Record<string, string> = {
  running: "Monitoring", paused: "Paused", stopped: "Stopped", emergency_stopped: "EMERGENCY STOP",
};

function ago(iso?: string | null) {
  if (!iso) return "never";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  return s < 90 ? `${s}s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : new Date(iso).toLocaleString();
}

function usd(x: any) { return typeof x === "number" ? money(x) : "-"; }

export function AutomationCenter() {
  const a = usePoll("/futures/automation", 5000);
  const acct = usePoll("/futures/paper", 10000);
  const sb = usePoll("/futures/sandbox", 15000);
  const dec = usePoll("/futures/decisions?limit=25", 15000);
  const jr = usePoll("/futures/journal/practice", 60000);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const st = a.data;
  const reload = () => { a.reload(); acct.reload(); sb.reload(); dec.reload(); };
  const act = async (path: string, json?: any) => {
    setErr(null);
    try { await api(`/futures/automation/${path}`, { method: "POST", json }); reload(); }
    catch (e: any) { setErr(e.message); }
  };
  const mode = async (m: string) => {
    setErr(null);
    try { await api("/futures/automation/mode", { method: "POST", json: { mode: m } }); reload(); }
    catch (e: any) { setErr(e.message); }
  };
  const cfg = async (json: any) => {
    setErr(null);
    try { await api("/futures/automation/config", { method: "PUT", json }); reload(); }
    catch (e: any) { setErr(e.message); }
  };
  if (!st) return <div className="page"><div className="muted">{a.error || "Loading automation…"}</div></div>;
  const risk = acct.data?.risk;
  const off = risk?.official || {};
  const met = risk?.metrics || {};
  const estop = st.status === "emergency_stopped";
  return (
    <div className="page">
      <div className={`note ${estop ? "bad" : "small"}`}>
        {estop ? <><b>Emergency stop active.</b> {st.emergency?.reason} ({st.emergency?.at?.slice(0, 19).replace("T", " ")} UTC). Working simulated orders were cancelled and
          simulated positions flattened. Write what happened to clear it.</> :
          <>Everything here is <b>simulated</b>. Study Terminal never sends orders to TopstepX or any broker, and it can't enforce limits on your real Topstep account.</>}
      </div>
      {err && <div className="note bad">{err}</div>}
      <div className="cols c-main">
        <div className="stack">
          <Panel title="Automation" sub={`${st.mode_label} · ${STATUS_TEXT[st.status] || st.status}`}
            right={<span className={`live-dot ${st.status === "running" ? "rec" : ""}`} aria-label={st.status === "running" ? "monitoring on" : "monitoring off"} />}>
            <div className="stack">
              <div className="row">
                {[["assisted", "A · Assisted"], ["paper_auto", "B · Automated paper"]].map(([m, l]) =>
                  <button key={m} className={st.mode === m ? "primary" : ""} onClick={() => mode(m)}>{l}</button>)}
                <button disabled title="Live execution is locked" aria-disabled>C · Live (locked)</button>
              </div>
              <div className="small muted">{st.mode === "assisted"
                ? "A: the app watches the market and records decisions; you place every simulated order yourself."
                : "B: the app enters and manages simulated trades on its own, only for strategies that passed walk-forward validation, inside every risk limit."}</div>
              <div className="row">
                {st.status === "running" && <button onClick={() => act("pause")}>Pause</button>}
                {st.status === "paused" && <button className="primary" onClick={() => act("resume")}>Resume</button>}
                {st.status === "stopped" && <button className="primary" onClick={() => act("start")}>Start monitoring</button>}
                {(st.status === "running" || st.status === "paused") && <button onClick={() => act("stop")}>Stop</button>}
                <button onClick={() => act("cycle")} disabled={estop}>Evaluate now</button>
                {!estop && <button className="danger" onClick={() => { if (confirm("Emergency stop: cancel all simulated working orders, flatten simulated positions and stop automation?")) act("emergency-stop", { reason: "Emergency stop pressed in the Automation Center" }); }}>Emergency stop</button>}
              </div>
              {estop && <div className="row"><input style={{ flex: 1 }} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What happened and what you checked" aria-label="Review note" />
                <button disabled={note.trim().length < 10} onClick={() => act("clear-emergency", { note })}>Clear emergency stop</button></div>}
              <div className="small muted">Started {ago(st.started_at)} · last cycle {ago(st.last_cycle_at)} · {st.cycles} cycles · every {st.interval_seconds}s</div>
              <div className="row small">
                <span>Contracts:</span>
                {["NQ", "MNQ", "ES", "MES"].map((r) => <label key={r} className="check"><input type="checkbox" checked={st.roots.includes(r)}
                  onChange={(e) => cfg({ roots: e.target.checked ? [...st.roots, r] : st.roots.filter((x: string) => x !== r) })} />{r}</label>)}
                <label className="check"><input type="checkbox" checked={st.sandbox_enabled} onChange={(e) => cfg({ sandbox_enabled: e.target.checked })} />Research sandbox</label>
              </div>
            </div>
          </Panel>

          <Panel title="Contracts" sub="latest evaluation per contract" flush>
            <table><thead><tr><th>Contract</th><th>Data</th><th>Regime</th><th>Decision</th><th>Reason</th><th>Checked</th></tr></thead>
              <tbody>{Object.entries(st.per_contract || {}).map(([c, p]: any) => <tr key={c}>
                <td><a href={`#/futures/${c}`}>{c}</a></td>
                <td>{p.error ? <span className="neg small">error</span> : <Meter withText status={p.data_status} />}</td>
                <td className="small">{p.regime || "-"}</td>
                <td>{p.outcome ? <Action a={p.action} /> : "-"}{p.outcome && p.outcome.replace(/_/g, " ") !== p.action && <div className="small faint">{p.outcome.replace(/_/g, " ")}</div>}</td>
                <td className="small">{p.error || p.reason}</td>
                <td className="small faint">{ago(p.last_eval)}</td></tr>)}
                {!Object.keys(st.per_contract || {}).length && <tr><td colSpan={6} className="muted">Not evaluated yet. Start monitoring or press "Evaluate now".</td></tr>}
              </tbody></table>
          </Panel>

          <Panel title="Recent decisions" sub="every pipeline result is stored with its reasoning" flush>
            <table><tbody>{(dec.data?.decisions || []).map((d: any) => <Fragment key={d.id}>
              <tr onClick={() => setOpen(open === d.id ? null : d.id)} style={{ cursor: "pointer" }}>
                <td className="small">{d.evaluated_at?.slice(5, 16).replace("T", " ")}</td><td>{d.contract}</td>
                <td className="small">{d.outcome?.replace(/_/g, " ")}</td><td className="small">{d.reason}</td>
                <td className="small">{d.acted ? `acted (${d.acted.slice(0, 8)})` : ""}</td></tr>
              {open === d.id && <tr><td colSpan={5}><DecisionSteps d={d} /></td></tr>}</Fragment>)}
              {!(dec.data?.decisions || []).length && <tr><td className="muted">No decisions yet.</td></tr>}</tbody></table>
          </Panel>

          <Panel title="Automation log" flush>
            <div style={{ maxHeight: 260, overflow: "auto" }}>{(st.log || []).map((l: any, i: number) =>
              <div key={i} className={`small ${l.level === "high" || l.level === "critical" ? "neg" : ""}`} style={{ padding: "3px 12px" }}>
                <span className="faint">{l.at?.slice(5, 19).replace("T", " ")}</span> {l.text}</div>)}</div>
          </Panel>
        </div>

        <div className="stack">
          <Panel title="Practice account" sub={off.label || "simulator"}>
            <table><tbody>
              <tr><td className="muted">Balance / equity</td><td className="num">{usd(acct.data?.balance)} / {usd(acct.data?.equity)}</td></tr>
              <tr><td className="muted">Day P&L</td><td className={`num ${met.day_pnl >= 0 ? "pos" : "neg"}`}>{usd(met.day_pnl)}</td></tr>
              <tr><td className="muted">Room above max loss</td><td className="num">{usd(off.mll_remaining)}{off.mll_floor != null ? ` (floor ${usd(off.mll_floor)})` : ""}</td></tr>
              <tr><td className="muted">Daily loss left</td><td className="num">{usd(off.dll_remaining)}</td></tr>
              <tr><td className="muted">Open risk</td><td className="num">{usd(met.open_risk_usd)}</td></tr>
              <tr><td className="muted">Trades today</td><td className="num">{met.trades_today ?? "-"}</td></tr>
            </tbody></table>
            {(risk?.blocks || []).map((b: any) => <div key={b.code} className="note bad small">{b.text}</div>)}
            {(risk?.warnings || []).slice(0, 3).map((w: any) => <div key={w.code} className="note warn small">{w.text}</div>)}
            {!off.confirmed && <div className="note warn small">Prop rules not confirmed against your account (Futures &gt; Rules).</div>}
          </Panel>

          <Panel title="Positions & working orders" flush>
            <table><tbody>
              {(acct.data?.positions || []).map((p: any) => <tr key={p.contract}><td>{p.contract}</td><td className="num">{p.qty > 0 ? "+" : ""}{p.qty} @ {p.avg_price}</td>
                <td className={`num ${p.unrealized >= 0 ? "pos" : "neg"}`}>{usd(p.unrealized)}</td>
                <td className="small faint">{st.managed?.[p.contract] ? "managed by automation" : "manual"}</td></tr>)}
              {(acct.data?.working_orders || []).map((o: any) => <tr key={o.id}><td className="small">{o.contract}</td><td className="small">{o.side} {o.qty} {o.type}</td>
                <td className="small num">{o.limit_price ?? o.stop_price ?? ""}</td><td className="small faint">{o.role} · {o.origin}</td></tr>)}
              {!(acct.data?.positions || []).length && !(acct.data?.working_orders || []).length && <tr><td className="muted">Flat. No working orders.</td></tr>}
            </tbody></table>
          </Panel>

          <Panel title="Automated vs manual" sub="practice account, closed trades">
            {jr.data ? <table><thead><tr><th></th><th>Trades</th><th>Net</th><th>Avg R</th><th>Max DD</th></tr></thead><tbody>
              {[["Automated", jr.data.automated], ["Manual", jr.data.manual]].map(([l, s]: any) => <tr key={l}><td>{l}</td><td>{s?.trades ?? 0}</td>
                <td className="num">{usd(s?.net)}</td><td className="num">{s?.avg_r ?? "-"}</td><td className="num">{usd(s?.max_drawdown)}</td></tr>)}
            </tbody></table> : <div className="muted small">Loading…</div>}
            <div className="small faint">{jr.data?.comparison_note}</div>
          </Panel>

          {st.sandbox_enabled && <Panel title="Research sandbox" sub="experimental strategies, separate account">
            <div className="small">Equity {usd(sb.data?.equity)} · {(sb.data?.positions || []).length} position(s) · {(sb.data?.fills || []).length} recent fill(s)</div>
            <div className="small faint">{sb.data?.label}</div>
          </Panel>}

          <MobileAccess />

          <Panel title="Live execution" sub="locked">
            <div className="small">{st.live?.note}</div>
            <ul className="small" style={{ paddingLeft: 18 }}>{(st.live?.checklist || []).map((c: any) => <li key={c.item}><b>{c.item}</b>: {c.status}.
              <span className="faint"> {c.detail}</span></li>)}</ul>
            <div className="small faint">Unlocking needs your explicit written authorization and an independently verified integration. It isn't something a setting can turn on.</div>
          </Panel>
        </div>
      </div>
    </div>
  );
}


function MobileAccess() {
  const m = usePoll("/mobile-access", 0);
  const [tok, setTok] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const set = async (enabled: boolean, new_token = false) => {
    setErr(null);
    try { const r = await api("/mobile-access", { method: "POST", json: { enabled, new_token } }); setTok(r.token || null); m.reload(); }
    catch (e: any) { setErr(e.message); }
  };
  const d = m.data;
  return (
    <Panel title="Mobile companion" sub={d?.enabled ? "on" : "off"}>
      {!d ? <div className="muted small">Loading…</div> : <div className="stack">
        <div className="small muted">A phone can read status and pause, resume or emergency-stop automation. It can't place orders or change rules.</div>
        <div className="row">{d.enabled ? <><button onClick={() => set(true, true)}>New token</button><button className="danger" onClick={() => set(false)}>Turn off</button></>
          : <button onClick={() => set(true)}>Turn on</button>}</div>
        {tok && <div className="note warn small">Token (shown once): <code style={{ wordBreak: "break-all" }}>{tok}</code></div>}
        <div className="small faint">Listening on {d.listening_on} only{d.allowed_hosts?.length ? `; also accepts ${d.allowed_hosts.join(", ")} for the mobile API` : ""}. {d.note}</div>
        {err && <div className="note bad small">{err}</div>}
      </div>}
    </Panel>
  );
}

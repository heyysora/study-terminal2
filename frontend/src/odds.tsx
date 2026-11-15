// "Check the odds" for a practice plan: how often the target came first, the stop came first, or neither by the flat time,
// on recent past days and in 10,000 simulated sessions built from them. A simulation, not a prediction.
import { useState } from "react";
import { api } from "./lib";

export function OddsCheck({ symbol, direction, entry, stop, target }: { symbol: string; direction: string; entry: number; stop: number; target: number }) {
  const [busy, setBusy] = useState(false);
  const [r, setR] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setBusy(true); setErr(null);
    try { setR(await api("/odds", { method: "POST", json: { symbol, direction: direction === "up" || direction === "long" ? "long" : "short", entry, stop, target } })); }
    catch (e: any) { setErr(e.message); }
    setBusy(false);
  };
  if (!r) {
    return (
      <div className="stack">
        <button onClick={run} disabled={busy}>{busy ? "Checking the last 60 days…" : "Check the odds"}</button>
        <span className="small faint">Tests this exact stop and target against how the price really moved recently.</span>
        {err && <div className="note bad">{err}</div>}
      </div>
    );
  }
  const s = r.simulation, p = r.past_days;
  return (
    <div className="odds stack">
      <div><b className={r.tone === "good" ? "up" : r.tone === "bad" ? "down" : ""}>{r.verdict}.</b> {r.say}</div>
      <div className="odds-bar" role="img" aria-label={`Target first ${s.target_first_pct}%, neither ${s.neither_pct}%, stop first ${s.stop_first_pct}%`}>
        <span className="t" style={{ width: `${s.target_first_pct}%` }} />
        <span className="n" style={{ width: `${s.neither_pct}%` }} />
        <span className="s" style={{ width: `${s.stop_first_pct}%` }} />
      </div>
      <div className="small"><span className="up">Target first {s.target_first_pct}%</span> · <span className="muted">Neither by {r.plan.flat_by}: {s.neither_pct}%</span> · <span className="down">Stop first {s.stop_first_pct}%</span>
        <span className="muted"> ({s.sessions.toLocaleString()} simulated sessions)</span></div>
      <div className="small">At {r.plan.reward_risk}:1, you need the target first more than <b>{s.breakeven_win_pct}%</b> of the times it's decided to break even.
        Average result per trade in the simulation: <b className={s.expectancy_r > 0 ? "up" : s.expectancy_r < 0 ? "down" : ""}>{s.expectancy_r > 0 ? "+" : ""}{s.expectancy_r}R</b> before costs.</div>
      <div className="small">Same plan from {r.plan.start} on each of the last {p.days} trading days ({p.first} to {p.last}): target first <b>{p.target}</b>, stop first <b>{p.stop}</b>, neither <b>{p.neither}</b>.</div>
      <ul className="small faint" style={{ margin: 0, paddingLeft: 18 }}>{r.notes.map((n: string) => <li key={n}>{n}</li>)}</ul>
      <div className="small faint">{r.data.source}.</div>
      <div><button className="ghost" onClick={() => setR(null)}>Hide</button></div>
    </div>
  );
}

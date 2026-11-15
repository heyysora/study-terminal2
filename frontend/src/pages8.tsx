import { Panel } from "./components";
import { usePoll } from "./lib";

const CLS: Record<string, string> = { PASSED: "pos", FAILED: "neg", "IN PROGRESS": "", UNTESTED: "" };

function fmt(v: any): string {
  if (v == null) return "—";
  if (Array.isArray(v)) return `[${v.map(fmt).join(", ")}]`;
  if (typeof v === "object") { const e = Object.entries(v); return e.length ? e.map(([k, x]) => `${k.replace(/_/g, " ")}: ${fmt(x)}`).join(" · ") : "—"; }
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000);
  return String(v);
}

export function TrustDashboard() {
  const t = usePoll("/trust", 60000);
  const d = t.data;
  if (!d) return <div className="page"><div className="muted">{t.error || "Loading…"}</div></div>;
  const r = d.readiness;
  return (
    <div className="page">
      <Panel title="Readiness" sub={`generated ${d.generated_at.slice(0, 16).replace("T", " ")} UTC`}>
        <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
          {r.levels.map((l: string, i: number) => <span key={l} className={`badge ${i <= r.level_index ? "pos" : ""}`}
            style={{ opacity: i <= r.level_index ? 1 : 0.5, outline: i === r.level_index ? "1px solid var(--up)" : "none" }}>{i + 1}. {l}</span>)}
        </div>
        <div style={{ marginTop: 8 }}>Current level: <b>{r.level}</b></div>
        <div className="note small" style={{ marginTop: 8 }}><b>Live brokerage execution: {r.live_execution}</b></div>
        {r.next_level && <>
          <h3>Still unverified before {r.next_level}</h3>
          <ul className="small" style={{ paddingLeft: 18 }}>{r.remaining_for_next_level.map((m: string, i: number) => <li key={i}>{m}</li>)}</ul>
        </>}
        {d.automatic && <div className="note small" style={{ marginTop: 8 }}><b>This fills in by itself.</b> While your TopstepX chart is open, Study Terminal checks its own readings against reference market data and the browser tab's name. Automatic checks so far: {d.automatic.samples}. Labelled by hand: {d.automatic.by_hand}. You don't need to label anything.</div>}
        <div className="small faint">{d.excluded.note} Synthetic screenshots excluded so far: {d.excluded.synthetic_screenshots}.</div>
      </Panel>
      <div className="grid-2" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(480px, 1fr))", gap: 12 }}>
        {d.categories.map((c: any, i: number) => (
          <Panel key={c.key} title={`${i + 1}. ${c.name}`} right={<span className={`badge ${CLS[c.status]}`}>{c.status}</span>}>
            <table className="small"><tbody>
              <tr><td className="muted">Observations</td><td>{c.observations}</td></tr>
              <tr><td className="muted">Last validated</td><td>{c.last_validated ? String(c.last_validated).slice(0, 19).replace("T", " ") : "never"}</td></tr>
              {Object.entries<any>(c.metrics || {}).map(([k, v]) => <tr key={k}><td className="muted">{k.replace(/_/g, " ")}</td><td style={{ wordBreak: "break-word" }}>{fmt(v)}</td></tr>)}
            </tbody></table>
            {c.remaining?.length > 0 && <div className="note warn small"><b>Remaining:</b><ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {c.remaining.map((m: string, j: number) => <li key={j}>{m}</li>)}</ul></div>}
            <details><summary className="small">Evidence</summary>{c.evidence.map((e: string, j: number) => <div key={j} className="small faint">{e}</div>)}</details>
            <details><summary className="small">Known limitations</summary>{c.limitations.map((e: string, j: number) => <div key={j} className="small faint">{e}</div>)}</details>
          </Panel>
        ))}
      </div>
      <Panel title="Thresholds">
        <div className="small faint">{Object.entries<any>(d.criteria).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(" · ")}</div>
        <div className="small faint">Accuracy is judged by the lower end of the 95% confidence range, so a small perfect sample isn't enough
          (about 35 correct out of 35 are needed to show 90%). Unit tests never change these statuses.</div>
      </Panel>
    </div>
  );
}

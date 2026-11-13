// Chart check: guided test of the Visual Monitor against your real TopstepX chart. Records results; never invents any.
import { useEffect, useState } from "react";
import { api, usePoll } from "./lib";

const STATUS_CLASS: Record<string, string> = { "PASSED": "up", "PROBLEMS FOUND": "down", "IN PROGRESS": "warn-link", "NOT TESTED": "muted" };
const WORD: Record<string, string> = { HEALTHY: "Working", DEGRADED: "Working, with problems", STALE: "Chart isn't updating",
  UNREADABLE: "Can't read the chart", DISCONNECTED: "Can't find the chart", REQUIRES_RECALIBRATION: "Check chart settings", OFF: "Not watching" };

function Compare({ step, onDone }: { step: any; onDone: () => void }) {
  const [s, setS] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [actual, setActual] = useState<Record<string, string>>({});
  const [last, setLast] = useState<any>(null);
  const typed = step.id === "candle" || step.id === "indicators";
  const take = async () => {
    setErr(null); setLast(null); setActual({});
    try { setS(await api("/chart-check/sample", { method: "POST", json: { step: step.id } })); } catch (e: any) { setErr(e.message); }
  };
  const send = async (matches: boolean | null) => {
    try {
      const act = typed ? Object.fromEntries(Object.entries(actual).filter(([, v]) => v.trim() !== "").map(([k, v]) => [k, Number(v)])) : (actual.value ? { value: actual.value } : {});
      setLast(await api("/chart-check/answer", { method: "POST", json: { sample: s.sample, matches, actual: act } }));
      setS(null); onDone();
    } catch (e: any) { setErr(e.message); }
  };
  return (
    <div className="stack">
      <p>{step.how}</p>
      {!s && <button className="primary" onClick={take}>{last ? "Take another" : "Read my chart now"}</button>}
      {err && <div className="note bad">{err}</div>}
      {last && <div className={`note ${last.outcome === "pass" ? "" : "bad"}`}>Recorded: <b>{last.outcome}</b>{last.errors ? ` (differences: ${Object.entries(last.errors).map(([k, v]) => `${k} ${v}`).join(", ")})` : ""}. {last.counts ? "" : "This came from a test source, so it doesn't count."}</div>}
      {s && <div className="plan">
        {s.image && <img src={s.image} alt="The part of your chart Study Terminal just read" style={{ width: step.id === "price" ? 520 : undefined, maxWidth: "100%", maxHeight: step.id === "price" ? undefined : 360, imageRendering: "auto", borderRadius: 8, border: "1px solid var(--rule)" }} />}
        <dl className="facts">{Object.entries<any>(s.shown.values || {}).map(([k, v]) => <div key={k}><dt>{k} · {v.how}</dt><dd>{v.value ?? "—"}</dd></div>)}</dl>
        {typed ? <>
          <div className="small muted">Type what TopstepX shows (leave blank to skip). Allowed difference: {s.shown.tolerance}.</div>
          <div className="row">{Object.keys(step.id === "candle" ? { open: 1, high: 1, low: 1, close: 1 } : s.shown.values || {}).map((k) =>
            <label key={k} className="f">{k}<input value={actual[k] || ""} onChange={(e) => setActual({ ...actual, [k]: e.target.value })} inputMode="decimal" style={{ width: 120 }} /></label>)}</div>
          <div className="row"><button className="primary" onClick={() => send(null)}>Compare</button><button onClick={() => setS(null)}>Cancel</button></div>
        </> : <>
          <div className="row"><button className="primary" onClick={() => send(true)}>Matches</button><button onClick={() => send(false)}>Doesn't match</button>
            <input placeholder="What it should be (optional)" value={actual.value || ""} onChange={(e) => setActual({ value: e.target.value })} /></div>
        </>}
      </div>}
    </div>
  );
}

function Watch({ step, onDone }: { step: any; onDone: () => void }) {
  const [w, setW] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<any>(null);
  const [right, setRight] = useState<boolean | null>(null);
  useEffect(() => {
    if (!w) return;
    const t = setInterval(async () => { try { setW((await api("/chart-check/watch")).watch); } catch { /* keep the last view */ } }, 2000);
    return () => clearInterval(t);
  }, [w?.step]); // eslint-disable-line react-hooks/exhaustive-deps
  const call = async (action: string, json: any = {}) => {
    setErr(null);
    try {
      const r = await api(`/chart-check/watch/${action}`, { method: "POST", json: { step: step.id, ...json } });
      if (action === "finish") { setRes(r.result); setW(null); onDone(); } else setW(r.watch);
    } catch (e: any) { setErr(e.message); }
  };
  const quiet = step.id === "resize" || step.id === "zoom";
  return (
    <div className="stack">
      <p className="small muted">Passes when: {step.pass}</p>
      {!w && <button className="primary" onClick={() => { setRes(null); call("start"); }}>Start this check</button>}
      {w && <ol className="plain-list">
        <li className={w.phase === "before" ? "" : "muted"}><b>{step.do}</b> {w.phase === "before" && <button className="primary small" onClick={() => call("phase", { phase: "did" })}>I did it</button>}</li>
        <li className={w.phase === "did" ? "" : "muted"}>Wait {step.within} seconds and watch the light at the top. Then: <b>{step.undo}</b> {w.phase === "did" && <button className="primary small" onClick={() => call("phase", { phase: "undid" })}>I put it back</button>}</li>
        <li className={w.phase === "undid" ? "" : "muted"}>Wait up to {step.recover} seconds for it to say Working, then finish.
          {quiet && w.phase === "undid" && <div className="row" style={{ marginTop: 6 }}>Does the price Study Terminal shows match TopstepX now?
            <button className={right === true ? "primary small" : "small"} onClick={() => setRight(true)}>Yes</button>
            <button className={right === false ? "primary small" : "small"} onClick={() => setRight(false)}>No</button></div>}
          {w.phase === "undid" && <div style={{ marginTop: 6 }}><button className="primary" onClick={() => call("finish", { price_still_right: right })}>Finish</button></div>}</li>
      </ol>}
      {w && <div className="small">What Study Terminal reported: {w.timeline.map((e: any, i: number) => <span key={i}>{i ? " → " : ""}{WORD[e.code] || e.code} <span className="faint">({e.t}s)</span></span>)}
        {" "}<button className="ghost small" onClick={() => call("cancel")}>Cancel</button></div>}
      {err && <div className="note bad">{err}</div>}
      {res && <div className={`note ${res.outcome === "pass" ? "" : "bad"}`}>Recorded: <b>{res.outcome}</b>. Noticed the problem: {res.detected ? `yes, after ${res.detected_after_s}s` : "no"}.
        Came back: {res.recovered ? `yes, after ${res.recovered_after_s}s` : "no"}. {res.follow_up || ""} {res.counts ? "" : "Test source: doesn't count."}</div>}
    </div>
  );
}

function Manual({ step, onDone }: { step: any; onDone: () => void }) {
  const [a, setA] = useState<Record<string, boolean | null>>({ watching_resumed: null, stop_kept: null });
  const [res, setRes] = useState<any>(null);
  const yn = (k: string, label: string, na = false) => <div className="row">{label}
    {[[true, "Yes"], [false, "No"], ...(na ? [[null, "Didn't apply"]] : [])].map(([v, l]: any) =>
      <button key={l} className={a[k] === v ? "primary small" : "small"} onClick={() => setA({ ...a, [k]: v })}>{l}</button>)}</div>;
  return (
    <div className="stack">
      <p>{step.how}</p>
      {yn("watching_resumed", "Did watching start again by itself?")}
      {yn("stop_kept", "If Stop everything was on, was it still on after restarting?", true)}
      <button className="primary" disabled={a.watching_resumed === null} onClick={async () => { setRes(await api("/chart-check/manual", { method: "POST", json: { step: step.id, answers: a } })); onDone(); }}>Record</button>
      {res && <div className="note">Recorded: <b>{res.outcome}</b>.</div>}
    </div>
  );
}

export function ChartCheck() {
  const sm = usePoll("/chart-check", 0);
  const [open, setOpen] = useState<string | null>(null);
  const steps: any[] = sm.data?.steps || [];
  const done = steps.filter((s) => s.status === "PASSED").length;
  return (
    <div className="page home">
      <section className="guide">
        <h2>Chart check</h2>
        <p style={{ margin: 0 }}>Test Study Terminal against your own TopstepX chart in Microsoft Edge, one check at a time. Every result is saved with the time,
          what Study Terminal read and how it got each value. Only results from your real screen count. Nothing here can trade.</p>
        <div className="small muted">{done} of {steps.length} checks passed so far. Do them while the market is open; the frozen-chart check needs it.</div>
        {sm.data && !sm.data.real_capture && <div className="note bad">This copy is using a test chart source, so results here won't count.</div>}
      </section>
      <div className="sheet">
        {steps.map((s) => (
          <section key={s.id} className="qa">
            <div className="spread">
              <button className="ghost" style={{ padding: 0, fontSize: 16, fontWeight: 650, color: "var(--text)" }} onClick={() => setOpen(open === s.id ? null : s.id)}>{s.title}</button>
              <span className={`small ${STATUS_CLASS[s.status] || ""}`}>{s.status}{s.real_results ? ` · ${s.passed} passed, ${s.failed} failed${s.unavailable ? `, ${s.unavailable} not available` : ""} (need ${s.need || 1})` : ""}</span>
            </div>
            {open === s.id && (s.kind === "compare" ? <Compare step={s} onDone={sm.reload} /> : s.kind === "watch" ? <Watch step={s} onDone={sm.reload} /> : <Manual step={s} onDone={sm.reload} />)}
          </section>
        ))}
      </div>
      <p className="small muted foot">Results are saved in your Study Terminal data folder under chart_checks. Send me results.jsonl from there and I can read them.</p>
    </div>
  );
}

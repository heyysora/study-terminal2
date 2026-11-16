// System health: everything about whether Study Terminal itself is OK, in one place, with the buttons to fix it.
import { useState } from "react";
import { api, usePoll } from "./lib";
import { BackupStatus, HelpFileButton, Restarting, when } from "./pagesData";

const LEVEL: Record<string, string> = { ok: "up", bad: "down", attention: "warn-link", idle: "muted" };

function Row({ label, word, level, children }: { label: string; word: React.ReactNode; level?: string; children?: React.ReactNode }) {
  return (
    <section className="qa">
      <div className="spread"><h3 style={{ margin: 0 }}>{label}</h3><b className={LEVEL[level || "idle"] || ""}>{word}</b></div>
      {children && <div className="stack small" style={{ marginTop: 6 }}>{children}</div>}
    </section>
  );
}

function SelfCheck({ last, onDone }: { last: any; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setBusy(true); setErr(null);
    try { await api("/system/self-check", { method: "POST" }); onDone(); } catch (e: any) { setErr(e.message); }
    setBusy(false);
  };
  return (
    <div className="stack">
      <p style={{ margin: 0 }}>Tests backup, restore, restoring over a damaged file, rescuing a partly damaged file, a failed restore putting everything back, and spotting a damaged backup, <b>on this computer</b>.
        It works on a scratch copy next to your data; your real data file is only read, never changed. Takes under a minute.</p>
      {last && <div className={last.passed ? "up" : "down"}>Last run {when(last.ran_at)} (version {last.version}): {last.passed ? "everything passed" : "something failed"}.
        <ul className="small" style={{ margin: "4px 0" }}>{last.steps.map((s: any) => <li key={s.step} className={s.ok ? "" : "down"}>{s.ok ? "✓" : "✗"} {s.step}{s.ok ? "" : `: ${s.detail}`}</li>)}</ul></div>}
      <div className="row"><button onClick={run} disabled={busy}>{busy ? "Running the check…" : last ? "Run it again" : "Run the recovery check"}</button></div>
      {err && <div className="note bad">{err}</div>}
    </div>
  );
}

function TextReader() {
  /** The screen-text reader, checked for real: the library, the modules it loads by name at run time, the model files,
   *  that the engine starts, and that it reads known text out of a picture. 0.18.1 shipped with this broken and the
   *  app could only say "I can't read your chart", so the check lives on screen with a button, not in a log file. */
  const [r, setR] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async (refresh: boolean) => {
    setBusy(true); setErr(null);
    try { setR(await api(`/visual/ocr-check${refresh ? "?refresh=true" : ""}`, { timeoutMs: 120_000 })); }
    catch (e: any) { setErr(e.message); }
    setBusy(false);
  };
  const word = !r ? (busy ? "Checking…" : "Not checked yet") : r.ok ? "Working" : "Not working";
  return (
    <Row label="Screen text reader" word={word} level={!r ? "idle" : r.ok ? "ok" : "bad"}>
      <div>Reading your chart means reading text off the picture: the market, the timeframe and the prices. This checks
        that the part doing that can actually start and read known text, instead of waiting to find out on your chart.</div>
      {r && !r.ok && r.advice && <div className="note bad">{r.advice}</div>}
      {r && <ul className="small" style={{ margin: "4px 0" }}>
        {r.steps.map((s: any) => <li key={s.id} className={s.status === "fail" ? "down" : s.status === "pass" ? "" : "muted"}>
          {s.status === "pass" ? "✓" : s.status === "fail" ? "✗" : "–"} {s.name}{s.detail ? `: ${s.detail}` : ""}</li>)}
      </ul>}
      {r && <div className="muted small">Versions: {Object.entries(r.versions).map(([k, v]) => `${k} ${v}`).join(" · ")}{r.took_ms ? ` · took ${(r.took_ms / 1000).toFixed(1)}s` : ""}</div>}
      <div className="row"><button onClick={() => run(!!r)} disabled={busy}>{busy ? "Checking…" : r ? "Check again" : "Check the text reader"}</button></div>
      {err && <div className="note bad">{err}</div>}
    </Row>
  );
}

function BuildCheck() {
  /** Every part of the app, each doing a small piece of real work, in the copy you actually installed. */
  const [r, setR] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setBusy(true); setErr(null);
    try { setR(await api("/system/subsystems", { timeoutMs: 180_000 })); } catch (e: any) { setErr(e.message); }
    setBusy(false);
  };
  return (
    <Row label="This build" word={!r ? (busy ? "Checking…" : "Not checked yet") : r.ok ? "All parts work" : `${r.failed.length} part(s) broken`}
      level={!r ? "idle" : r.ok ? "ok" : "bad"}>
      <div>Checks every part of Study Terminal by making it do something real — fit a model, open a database, build a
        market calendar, read text off a picture — in the copy on this PC, not in a test.</div>
      {r && <ul className="small" style={{ margin: "4px 0" }}>
        {r.checks.map((c: any) => <li key={c.id} className={c.status === "fail" ? "down" : ""}>
          {c.status === "pass" ? "✓" : "✗"} {c.name}: {c.detail}</li>)}
      </ul>}
      <div className="row"><button onClick={run} disabled={busy}>{busy ? "Checking…" : r ? "Check again" : "Check every part"}</button></div>
      {err && <div className="note bad">{err}</div>}
    </Row>
  );
}

export function SystemHealth() {
  const h = usePoll("/system/health", 15000);
  const lock = usePoll("/crypto/lock-check", 600000);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [askRestart, setAskRestart] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const d = h.data;
  if (restarting) return <Restarting />;
  if (!d) return <div className="page muted">{h.error ? `Couldn't load: ${h.error}` : "Loading…"}</div>;
  const backup = async () => {
    try { await api("/data/backup", { method: "POST" }); setMsg({ text: "Backed up and checked." }); h.reload(); }
    catch (e: any) { setMsg({ text: e.message, bad: true }); }
  };
  const openData = async () => {
    try { const r = await api("/data/show", { method: "POST", json: { what: "data" } }); if (!r.shown) setMsg({ text: `It's here: ${r.path}` }); }
    catch (e: any) { setMsg({ text: e.message, bad: true }); }
  };
  const restart = async () => {
    try { await api("/system/restart", { method: "POST", json: { confirm: true } }); setRestarting(true); } catch (e: any) { setMsg({ text: e.message, bad: true }); }
  };
  const df = d.data_file, ext = d.extension, cm = d.chart_monitor, st = d.startups;
  return (
    <div className="page home">
      <section className="guide">
        <div className="spread"><h2 style={{ margin: 0 }}>System health</h2>
          <b className={d.overall === "All good" ? "up" : d.overall === "Problem" ? "down" : "warn-link"}>{d.overall}</b></div>
        <p className="small muted" style={{ margin: 0 }}>Whether Study Terminal itself is working: the app, your data, backups, the chart monitor and the Chrome extension.
          This page updates every 15 seconds. Nothing here can trade; practice mode only.</p>
        {d.restart_recommended
          ? <div className="note warn stack"><div><b>A restart is recommended.</b> {d.restart_reasons.join(" ")}</div>
            {askRestart
              ? <div className="stack"><div>Study Terminal stops cleanly and starts again (about 10 seconds). Nothing is lost. If you were watching a chart, check My chart afterwards.</div>
                <div className="row"><button className="primary" onClick={restart}>Restart now</button><button className="ghost" onClick={() => setAskRestart(false)}>Cancel</button></div></div>
              : <div className="row"><button className="primary" onClick={() => setAskRestart(true)}>Restart Study Terminal</button></div>}</div>
          : <div className="small up">No restart needed.</div>}
        {msg && <div className={`note ${msg.bad ? "bad" : ""}`}>{msg.text}</div>}
      </section>
      <div className="sheet">
        <Row label="App" word={d.app.mode === "recovery" ? "Recovery mode" : "Running"} level={d.app.mode === "recovery" ? "bad" : "ok"}>
          <div>Version {d.app.version}{d.app.started_at ? ` · running since ${when(d.app.started_at)}` : ""} · port {d.app.port} · practice mode only (real orders can't be placed).</div>
        </Row>
        <Row label="Data file" word={df.ok ? "OK" : "Problem"} level={df.ok ? "ok" : "bad"}>
          <div>{df.ok ? `Opens and passes SQLite's check (${df.size_mb} MB).` : `Problem: ${df.problem || "not found"}`}{df.checked_at ? ` Checked ${when(df.checked_at)}.` : ""}</div>
          <div className={df.disk?.low_space ? "down" : "muted"}>{df.disk?.free_mb != null ? `${df.disk.free_mb.toLocaleString()} MB free on the disk.` : ""}{df.disk?.low_space ? " That's almost full: free up some space." : ""}</div>
          <div className="row"><button className="ghost" onClick={openData}>Open my data folder</button></div>
        </Row>
        <Row label="Backups" word={d.backups.warning ? "None usable" : d.backups.newest_ok ? "OK" : "Check needed"} level={d.backups.warning ? "bad" : d.backups.newest_ok ? "ok" : "attention"}>
          <BackupStatus summary={d.backups} />
          <div className="row"><button onClick={backup}>Back up now</button><a className="btn ghost" href="#/settings">Backups and restore (Settings)</a></div>
        </Row>
        <Row label="Chart monitor" word={cm.word} level={cm.level}>
          {cm.reason && <div>{cm.reason}</div>}{cm.do && <div className="muted">{cm.do}</div>}
          {d.chart_loop_restarts > 0 && <div className="muted">The chart-reading loop restarted itself {d.chart_loop_restarts} time(s) since the app started.</div>}
          <div className="row"><a className="btn ghost" href="#/visual">My chart</a><a className="btn ghost" href="#/check">Chart check</a></div>
        </Row>
        <TextReader />
        <BuildCheck />
        <Row label="Crypto prices" word={!lock.data ? "Checking…" : lock.data.locked ? "Read-only" : "Problem"} level={!lock.data ? "idle" : lock.data.locked ? "ok" : "bad"}>
          <div>{lock.data?.detail || "Checking that the exchange price library can only read public prices."}</div>
          <div className="muted">Live crypto prices come from public exchange data (Kraken, Coinbase or Bitstamp). No account, no keys, and every order function is switched off.</div>
        </Row>
        <Row label="Chrome extension" word={ext.word} level={ext.level}>
          {ext.do && <div>{ext.do}</div>}
          {ext.enabled && <div className="muted">Study Terminal is on port {ext.app_port}; the extension finds it automatically.
            {ext.last_seen ? ` Last contact ${when(ext.last_seen)}${ext.extension_port ? ` on port ${ext.extension_port}` : ""}${ext.extension_version ? ` (extension ${ext.extension_version})` : ""}.` : ""}</div>}
          <div className="row"><a className="btn ghost" href="#/settings">Extension settings</a></div>
        </Row>
        <Row label="Starting up" word={st.last_ok ? `Last good start ${when(st.last_ok.at)}` : "No good start recorded yet"} level={st.unclean_last_time ? "attention" : "ok"}>
          {st.unclean_last_time && <div>Last time, Study Terminal didn't close normally (for example the computer lost power). Nothing needs doing unless it keeps happening.</div>}
          {st.recent?.length > 0 && <div className="muted">Recent starts: {st.recent.map((x: any) => `${when(x.at)}${x.mode === "recovery" ? " (Recovery mode)" : ""}`).join(" · ")}</div>}
        </Row>
        <Row label="Recent errors" word={d.recent_errors.length ? `${d.recent_errors.length} in the last 3 days` : "None"} level={d.recent_errors.length ? "attention" : "ok"}>
          {d.recent_errors.length > 0 && <>
            <div className="muted">These are technical messages from the app's log. One or two now and then is normal; a lot in a short time is a reason to restart or to send a help file.</div>
            <ul style={{ margin: 0 }}>{d.recent_errors.map((e: any, i: number) => <li key={i}><span className="muted">{when(e.at)}</span> {e.text}</li>)}</ul></>}
        </Row>
        <Row label="Recovery check on this computer" word={d.self_check ? (d.self_check.passed ? "Passed" : "Failed") : "Not run yet"} level={d.self_check ? (d.self_check.passed ? "ok" : "bad") : "attention"}>
          <SelfCheck last={d.self_check} onDone={h.reload} />
        </Row>
        <Row label="Help file" word="">
          <div>Saves everything needed to look into a problem (logs, this page, backups list, Chart check results, recovery check results) to your Downloads folder. Passwords and keys are blanked out.</div>
          <HelpFileButton label="Save a complete help file" />
        </Row>
      </div>
    </div>
  );
}

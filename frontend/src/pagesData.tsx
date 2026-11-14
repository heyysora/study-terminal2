// Your data, without a terminal: Recovery screen, backups and restore, the help file. Nothing here ever deletes anything.
import { useEffect, useState } from "react";
import { api, usePoll } from "./lib";

const KIND: Record<string, string> = { daily: "Daily", manual: "You made it", "before upgrade": "Before an update", "before restore": "Before a restore", other: "Backup" };

export function when(iso?: string | null) {
  if (!iso) return "unknown time";
  const d = new Date(iso);
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function whatsIn(b: any) {
  const c = b.counts || {};
  const parts = Object.entries(c).filter(([, n]) => (n as number) > 0).map(([k, n]) => `${n} ${k}`);
  return parts.length ? parts.join(", ") : "no journal trades or practice orders yet";
}

// After a restore/rescue/fresh start is scheduled, the desktop app restarts itself. Wait for it, then reload.
export function Restarting() {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const t0 = Date.now();
    const id = setInterval(async () => {
      try {
        const st = await api("/data/status");
        if (!st.restart_requested && !st.pending) { clearInterval(id); location.hash = "#/home"; location.reload(); }
      } catch { /* the app is restarting */ }
      if (Date.now() - t0 > 25000) setSlow(true);
    }, 1500);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="page home"><section className="guide">
      <h2>Restarting Study Terminal…</h2>
      <p>This takes a few seconds. Your request is done before your data is opened.</p>
      {slow && <div className="note warn">This is taking longer than usual. Close Study Terminal and open it again; your request is kept and will be done then.</div>}
    </section></div>
  );
}

export function HelpFileButton({ label = "Save a help file", note = true }: { label?: string; note?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [withData, setWithData] = useState(false);
  const make = async () => {
    setBusy(true); setErr(null); setRes(null);
    try { setRes(await api("/data/help-file", { method: "POST", json: { include_database: withData } })); } catch (e: any) { setErr(e.message); }
    setBusy(false);
  };
  const show = async () => { try { await api("/data/show", { method: "POST", json: { what: "help", name: res.name } }); } catch (e: any) { setErr(e.message); } };
  return (
    <div className="stack">
      <div className="row"><button className="primary" disabled={busy} onClick={make}>{busy ? "Saving…" : label}</button></div>
      {note && <label className="check small"><input type="checkbox" checked={withData} onChange={(e) => setWithData(e.target.checked)} />Also include my data file (journal, practice accounts, settings)</label>}
      {res && <div className="note">Saved <b>{res.name}</b> in {res.folder}. <button className="ghost" onClick={show}>Show it</button><br />
        It has your logs, Chart check results and pictures, and chart setups. Passwords and API keys are blanked out.</div>}
      {err && <div className="note bad">{err}</div>}
    </div>
  );
}

function BackupList({ list, onPick, pickLabel }: { list: any[]; onPick: (b: any) => void; pickLabel: string }) {
  if (!list.length) return <p className="muted">There are no backups yet.</p>;
  return (
    <div className="sheet">
      {list.map((b) => (
        <section key={b.name} className="qa">
          <div className="spread">
            <div><b>{when(b.made_at)}</b> <span className="small muted">· {KIND[b.kind] || "Backup"}</span>
              <div className="small muted">{b.ok ? whatsIn(b) : "This backup's data file didn't pass the check, so it can't be used."}</div></div>
            {b.ok && <button onClick={() => onPick(b)}>{pickLabel}</button>}
          </div>
        </section>
      ))}
    </div>
  );
}

function Confirm({ text, yes, onYes, onNo }: { text: React.ReactNode; yes: string; onYes: () => void; onNo: () => void }) {
  return (
    <div className="note warn stack">
      <div>{text}</div>
      <div className="row"><button className="primary" onClick={onYes}>{yes}</button><button className="ghost" onClick={onNo}>Cancel</button></div>
    </div>
  );
}

async function schedule(action: string, backup?: string) {
  await api("/data/schedule", { method: "POST", json: { action, backup, confirm: true } });
}

const PROBLEM: Record<string, string> = {
  database: "Your data file is damaged, so Study Terminal can't open it.",
  disk: "Study Terminal can't save anything in its data folder.",
};

// Shown instead of the app when the data file is damaged or the folder can't be written.
export function RecoveryScreen({ status }: { status: any }) {
  const rec = status.recovery;
  const bk = usePoll("/data/backups");
  const [ask, setAsk] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const list: any[] = (bk.data?.backups || []);
  const good = list.filter((b) => b.ok);
  const go = async (action: string, backup?: string) => {
    try { await schedule(action, backup); setRestarting(true); } catch (e: any) { setErr(e.message); }
  };
  if (restarting) return <Restarting />;
  if (rec.kind === "disk") {
    return (
      <div className="page home"><section className="guide">
        <h2>{PROBLEM.disk}</h2>
        <p>Your data hasn't been changed. Usually the disk is full, or another program (like antivirus or a sync app) is holding the folder.</p>
        <ol className="small"><li>Free up some disk space{rec.disk?.free_mb != null ? ` (${rec.disk.free_mb} MB free now)` : ""}.</li>
          <li>Restart your computer.</li><li>Open Study Terminal again.</li></ol>
        <div className="small muted">Folder: {status.data_folder}. Technical reason: {rec.problem}</div>
        <HelpFileButton note={false} />
      </section></div>
    );
  }
  return (
    <div className="page home">
      <section className="guide">
        <h2>{PROBLEM.database}</h2>
        <p style={{ margin: 0 }}>Nothing has been deleted. Pick one of these and Study Terminal will restart and fix it. Whatever you pick, the damaged file is kept in a folder called "damaged".</p>
        <div className="small muted">Technical reason: {rec.problem}</div>
      </section>
      {err && <div className="note bad">{err}</div>}
      <div className="sheet">
        {good[0] && (
          <section className="qa">
            <h3>Use my most recent backup (recommended)</h3>
            <p>From <b>{when(good[0].made_at)}</b>: {whatsIn(good[0])}. Anything you did after that is lost.</p>
            {ask?.action === "restore" && ask.backup === good[0].name
              ? <Confirm text={`Restore the backup from ${when(good[0].made_at)}?`} yes="Restore and restart" onYes={() => go("restore", good[0].name)} onNo={() => setAsk(null)} />
              : <button className="primary" onClick={() => setAsk({ action: "restore", backup: good[0].name })}>Use this backup</button>}
          </section>
        )}
        <section className="qa">
          <h3>Try to rescue what's left</h3>
          <p>Copies every part of your data that can still be read into a new file. Works when only part of the file is damaged.</p>
          {ask?.action === "rescue"
            ? <Confirm text="Rescue what can be read and restart?" yes="Rescue and restart" onYes={() => go("rescue")} onNo={() => setAsk(null)} />
            : <button onClick={() => setAsk({ action: "rescue" })}>Try to rescue</button>}
        </section>
        {good.length > 1 && (
          <section className="qa">
            <button className="ghost" onClick={() => setMore(!more)}>{more ? "Hide other backups" : `Pick another backup (${good.length - 1} more)`}</button>
            {more && <BackupList list={list.slice(1)} pickLabel="Use this one" onPick={(b) => setAsk({ action: "restore", backup: b.name, when: b.made_at })} />}
            {ask?.action === "restore" && ask.backup !== good[0].name &&
              <Confirm text={`Restore the backup from ${when(ask.when)}?`} yes="Restore and restart" onYes={() => go("restore", ask.backup)} onNo={() => setAsk(null)} />}
          </section>
        )}
        <section className="qa">
          <h3>Start with empty data</h3>
          <p>Your journal, practice accounts and settings start over. The damaged file is kept, not deleted.</p>
          {ask?.action === "fresh"
            ? <Confirm text="Start with empty data and restart?" yes="Start fresh" onYes={() => go("fresh")} onNo={() => setAsk(null)} />
            : <button className="ghost" onClick={() => setAsk({ action: "fresh" })}>Start fresh</button>}
        </section>
        <section className="qa">
          <h3>Not sure? Save a help file and send it to me</h3>
          <HelpFileButton note={false} />
        </section>
      </div>
    </div>
  );
}

// Settings > Your data
export function YourData() {
  const st = usePoll("/data/status", 0);
  const bk = usePoll("/data/backups");
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [ask, setAsk] = useState<any>(null);
  const [restarting, setRestarting] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const list: any[] = bk.data?.backups || [];
  const backup = async () => {
    setMsg(null);
    try { const r = await api("/data/backup", { method: "POST" }); setMsg({ text: `Backed up: ${whatsIn(r)}.` }); bk.reload(); st.reload(); }
    catch (e: any) { setMsg({ text: e.message, bad: true }); }
  };
  const show = async (what: string) => {
    try { const r = await api("/data/show", { method: "POST", json: { what } }); if (!r.shown) setMsg({ text: `It's here: ${r.path}` }); }
    catch (e: any) { setMsg({ text: e.message, bad: true }); }
  };
  const restore = async (b: any) => {
    try { await schedule("restore", b.name); setRestarting(true); } catch (e: any) { setMsg({ text: e.message, bad: true }); }
  };
  if (restarting) return <Restarting />;
  const disk = st.data?.disk;
  return (
    <div className="stack">
      <p className="small muted" style={{ margin: 0 }}>A backup is made every day you use Study Terminal and before every update. Restoring keeps a copy of your current data first, so you can go back.</p>
      {st.data?.last_backup ? <div>Last good backup: <b>{when(st.data.last_backup.made_at)}</b> ({whatsIn(st.data.last_backup)}).</div>
        : <div className="note warn">No backup yet. Make one now.</div>}
      {disk?.low_space && <div className="note bad">Your disk is almost full ({disk.free_mb} MB free). Backups are paused until there's more room.</div>}
      <div className="row">
        <button className="primary" onClick={backup}>Back up now</button>
        <button onClick={() => show("data")}>Open my data folder</button>
        <button className="ghost" onClick={() => show("backups")}>Open backups folder</button>
      </div>
      {msg && <div className={`note ${msg.bad ? "bad" : ""}`}>{msg.text}</div>}
      {ask && <Confirm text={<>Go back to the backup from <b>{when(ask.made_at)}</b> ({whatsIn(ask)})? Study Terminal restarts. Your current data is backed up first.</>}
        yes="Restore and restart" onYes={() => restore(ask)} onNo={() => setAsk(null)} />}
      <BackupList list={showAll ? list : list.slice(0, 4)} pickLabel="Restore" onPick={setAsk} />
      {list.length > 4 && <button className="ghost" onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer" : `Show all ${list.length} backups`}</button>}
      <h3 style={{ marginBottom: 0 }}>Something not working?</h3>
      <HelpFileButton />
    </div>
  );
}

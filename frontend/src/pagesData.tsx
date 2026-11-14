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
              <div className="small muted">{b.usable ? whatsIn(b) : ""}</div>
              <div className={`small ${b.usable ? "up" : "down"}`}>{b.status_text}{b.legacy && b.usable ? " (an older backup: only its data file can be checked)" : ""}</div></div>
            {b.usable && <button onClick={() => onPick(b)}>{pickLabel}</button>}
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

// One recovery option, always answering the same three questions.
function Option({ title, recommended, does, loss, next, children }: { title: string; recommended?: boolean; does: React.ReactNode; loss: React.ReactNode; next: React.ReactNode; children?: React.ReactNode }) {
  return (
    <section className="qa">
      <h3 style={{ marginTop: 0 }}>{title}{recommended && <span className="small up"> · recommended</span>}</h3>
      <dl className="explain">
        <dt>What it does</dt><dd>{does}</dd>
        <dt>Could I lose anything?</dt><dd>{loss}</dd>
        <dt>What happens next</dt><dd>{next}</dd>
      </dl>
      {children}
    </section>
  );
}

// Shown instead of the app when the data file is damaged or the folder can't be written.
export function RecoveryScreen({ status }: { status: any }) {
  const rec = status.recovery;
  const bk = usePoll("/data/backups");
  const [ask, setAsk] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const list: any[] = (bk.data?.backups || []);
  const good = list.filter((b) => b.usable);
  const last = status.last_recovery;
  const go = async (action: string, backup?: string) => {
    try { await schedule(action, backup); setRestarting(true); } catch (e: any) { setErr(e.message); setAsk(null); bk.reload(); }
  };
  const retry = async () => { try { await api("/system/restart", { method: "POST", json: { confirm: true } }); setRestarting(true); } catch (e: any) { setErr(e.message); } };
  if (restarting) return <Restarting />;
  if (rec.kind === "disk") {
    return (
      <div className="page home">
        <section className="guide">
          <h2>Study Terminal can't save anything right now</h2>
          <h3>What went wrong</h3>
          <p>Windows won't let Study Terminal write in its data folder. Usually the disk is full{rec.disk?.free_mb != null ? ` (${rec.disk.free_mb} MB free now)` : ""}, or another program (antivirus, OneDrive or another sync app) is holding the folder.</p>
          <h3>Is my data safe?</h3>
          <p>Yes. Nothing was changed or deleted. Study Terminal stopped before saving anything.</p>
          <div className="small muted">Folder: {status.data_folder}. Technical reason: {rec.problem}</div>
        </section>
        <div className="sheet">
          <Option title="Free up space, then try again" recommended does="You delete or move some files (for example from Downloads), then click Try again."
            loss="No. Study Terminal only checks the folder again." next="If it can write now, it restarts and opens normally. If not, you come back to this screen.">
            <button className="primary" onClick={retry}>Try again</button>
          </Option>
          <Option title="Restart your computer" does="Closes whatever program is holding the folder." loss="No." next="Open Study Terminal again afterwards." />
          <Option title="Save a help file" does="Saves a zip with the app's logs to your Downloads folder (if there's room) so someone can look at it."
            loss="No. Nothing in the app changes." next="Send the file. You can still try the other options."><HelpFileButton note={false} /></Option>
        </div>
      </div>
    );
  }
  const newest = good[0];
  const pick = ask?.action === "restore" ? list.find((b) => b.name === ask.backup) : null;
  return (
    <div className="page home">
      <section className="guide">
        <h2>Study Terminal needs to fix your data file</h2>
        {last && !last.ok && <div className="note bad">Your last choice didn't work: {last.detail}</div>}
        <h3>What went wrong</h3>
        <p style={{ margin: 0 }}>Your journal, practice accounts and settings are kept in one data file. That file is damaged, so Study Terminal can't open it safely.</p>
        <div className="small muted">Technical reason: {rec.problem}</div>
        <h3>Is my data safe?</h3>
        <p style={{ margin: 0 }}>Nothing has been deleted or changed. The damaged file stays exactly as it is until you choose below, and every option keeps a copy of it in a folder called "damaged".
          {newest ? <> Your newest usable backup is from <b>{when(newest.made_at)}</b> ({whatsIn(newest)}).</> : <> <b>You don't have a usable backup</b>, so rescuing is the best first try.</>}</p>
      </section>
      {err && <div className="note bad">{err}</div>}
      <div className="sheet">
        {newest && (
          <Option title={`Use my backup from ${when(newest.made_at)}`} recommended
            does={<>Puts your data back exactly as it was on {when(newest.made_at)}. The backup is checked again before it's used.</>}
            loss={<>Yes: anything you did after {when(newest.made_at)} (trades, notes, setting changes) won't be there. The damaged file is kept, so it isn't gone for good.</>}
            next="Study Terminal restarts by itself (a few seconds) and opens normally, with a message saying what was done. If the backup turns out to be bad, nothing changes and you come back here.">
            {ask?.action === "restore" && ask.backup === newest.name
              ? <Confirm text={<>Go back to {when(newest.made_at)}? Anything after that won't be in the app.</>} yes="Yes, use this backup" onYes={() => go("restore", newest.name)} onNo={() => setAsk(null)} />
              : <button className="primary" onClick={() => setAsk({ action: "restore", backup: newest.name })}>Use this backup</button>}
          </Option>
        )}
        <Option title="Rescue what can still be read" recommended={!newest}
          does="Copies every part of the damaged file that can still be read into a new data file."
          loss="Maybe: parts that can't be read are left out, and the message afterwards lists them. The damaged file is kept."
          next="Study Terminal restarts by itself. If nothing at all can be read, nothing changes and you come back here to pick another option.">
          {ask?.action === "rescue"
            ? <Confirm text="Rescue what can be read? Parts that can't be read will be missing." yes="Yes, rescue" onYes={() => go("rescue")} onNo={() => setAsk(null)} />
            : <button className={newest ? "" : "primary"} onClick={() => setAsk({ action: "rescue" })}>Try to rescue</button>}
        </Option>
        {good.length > 1 && (
          <Option title="Use an older backup" does="Same as using the newest backup, from an earlier date. Useful if the newest one is missing something."
            loss="Yes: anything after the date you pick won't be there. The damaged file is kept." next="Study Terminal restarts by itself and opens normally.">
            <button className="ghost" onClick={() => setMore(!more)}>{more ? "Hide older backups" : `Show older backups (${good.length - 1})`}</button>
            {more && <BackupList list={list.filter((b) => b.name !== newest?.name)} pickLabel="Use this one" onPick={(b) => setAsk({ action: "restore", backup: b.name })} />}
            {pick && pick.name !== newest?.name &&
              <Confirm text={<>Go back to {when(pick.made_at)}? Anything after that won't be in the app.</>} yes="Yes, use this backup" onYes={() => go("restore", pick.name)} onNo={() => setAsk(null)} />}
          </Option>
        )}
        <Option title="Start with empty data"
          does="Starts with an empty journal, a new practice account and the default settings."
          loss={<><b>Yes, everything in the app starts over.</b> The damaged file is kept in "damaged", so it could still be looked at later.</>}
          next="Study Terminal restarts by itself and opens like a new install, with the setup guide on Home.">
          {ask?.action === "fresh"
            ? <Confirm text="Start over with empty data? Your journal, practice accounts and settings will be empty in the app." yes="Yes, start fresh" onYes={() => go("fresh")} onNo={() => setAsk(null)} />
            : <button className="ghost" onClick={() => setAsk({ action: "fresh" })}>Start fresh</button>}
        </Option>
        <Option title="Not sure? Save a help file"
          does="Saves a zip with the app's logs and a description of the problem to your Downloads folder."
          loss="No. Nothing in the app changes." next="Send the file. You can come back and pick an option any time.">
          <HelpFileButton note={false} />
        </Option>
      </div>
    </div>
  );
}

// Settings > Your data
export function BackupStatus({ summary }: { summary: any }) {
  if (!summary) return null;
  const lg = summary.last_good, nw = summary.newest;
  return (
    <div className="stack">
      {summary.warning && <div className="note bad"><b>You have no usable backup.</b> If your data file were damaged now, there'd be nothing to restore. Click Back up now.</div>}
      {lg && <div>Last good backup: <b>{when(lg.made_at)}</b> ({whatsIn(lg)}).</div>}
      {nw && (nw.usable
        ? <div className="small up">The newest backup ({when(nw.made_at)}) passed its check.</div>
        : <div className="note warn">The newest backup ({when(nw.made_at)}) didn't pass its check: {nw.status_text} {lg ? `Your backup from ${when(lg.made_at)} is still usable.` : ""}</div>)}
    </div>
  );
}

export function YourData() {
  const st = usePoll("/data/status", 0);
  const bk = usePoll("/data/backups");
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [ask, setAsk] = useState<any>(null);
  const [restarting, setRestarting] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [checking, setChecking] = useState(false);
  const list: any[] = bk.data?.backups || [];
  const backup = async () => {
    setMsg(null);
    try { const r = await api("/data/backup", { method: "POST" }); setMsg({ text: `Backed up and checked: ${whatsIn(r)}.` }); bk.reload(); st.reload(); }
    catch (e: any) { setMsg({ text: e.message, bad: true }); bk.reload(); }
  };
  const check = async () => {
    setChecking(true); setMsg(null);
    try {
      const r = await api("/system/check-backups", { method: "POST" });
      const bad = r.backups.filter((b: any) => !b.usable).length;
      setMsg({ text: bad ? `${r.backups.length - bad} backups are usable; ${bad} didn't pass (shown in red).` : `All ${r.backups.length} backups passed.`, bad: !r.summary.usable_count });
      bk.reload(); st.reload();
    } catch (e: any) { setMsg({ text: e.message, bad: true }); }
    setChecking(false);
  };
  const show = async (what: string) => {
    try { const r = await api("/data/show", { method: "POST", json: { what } }); if (!r.shown) setMsg({ text: `It's here: ${r.path}` }); }
    catch (e: any) { setMsg({ text: e.message, bad: true }); }
  };
  const restore = async (b: any) => {
    try { await schedule("restore", b.name); setRestarting(true); } catch (e: any) { setMsg({ text: e.message, bad: true }); setAsk(null); bk.reload(); }
  };
  if (restarting) return <Restarting />;
  const disk = st.data?.disk;
  return (
    <div className="stack">
      <p className="small muted" style={{ margin: 0 }}>A backup is made every day you use Study Terminal and before every update, and each one is read back to check it can really be used. Backups are checked again once a day.</p>
      <BackupStatus summary={bk.data?.summary} />
      {disk?.low_space && <div className="note bad">Your disk is almost full ({disk.free_mb} MB free). Backups are paused until there's more room.</div>}
      <div className="row">
        <button className="primary" onClick={backup}>Back up now</button>
        <button onClick={check} disabled={checking}>{checking ? "Checking…" : "Check my backups"}</button>
        <button className="ghost" onClick={() => show("data")}>Open my data folder</button>
        <button className="ghost" onClick={() => show("backups")}>Open backups folder</button>
      </div>
      {msg && <div className={`note ${msg.bad ? "bad" : ""}`}>{msg.text}</div>}
      {ask && <Confirm text={<><b>Go back to {when(ask.made_at)}?</b> ({whatsIn(ask)})<br />
        Could I lose anything? Changes after {when(ask.made_at)} won't be in the app, but your current data is backed up first (it appears in this list as "Before a restore"), so you can switch back.<br />
        What happens next: Study Terminal restarts by itself and shows what it did. If the backup turns out to be bad, nothing changes.</>}
        yes="Restore and restart" onYes={() => restore(ask)} onNo={() => setAsk(null)} />}
      <BackupList list={showAll ? list : list.slice(0, 4)} pickLabel="Restore" onPick={setAsk} />
      {list.length > 4 && <button className="ghost" onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer" : `Show all ${list.length} backups`}</button>}
      <h3 style={{ marginBottom: 0 }}>Something not working?</h3>
      <p className="small muted" style={{ margin: 0 }}>See Health in the menu for everything in one place.</p>
      <HelpFileButton />
    </div>
  );
}

// The safety bar (practice badge, health light, Stop everything), the plain risk line, and the shared "why" block.
import { useState } from "react";
import { api, money, sign } from "./lib";
import { Why, actionWord, explain, isSimple, reloadHome, say, setUiMode, term, useHome, useUiMode } from "./plain";

export const LEVEL_CLASS: Record<string, string> = { ok: "ok", off: "off", attention: "attn", bad: "bad" };

/** A trading term with an everyday explanation on hover or keyboard focus. */
export function Term({ k, children }: { k: string; children?: React.ReactNode }) {
  const t = term(k);
  const mode = useUiMode();
  if (!t) return <>{children ?? k}</>;
  const text = children ?? (mode === "simple" ? t.simple : t.technical);
  return <span className="term" tabIndex={0} title={`${t.technical}: ${t.explain}`}>{text}</span>;
}

/** The answer to "why?": one plain sentence, what to do, and the original wording one click away. */
export function WhyBlock({ reason, why, compact }: { reason?: string | null; why?: Why; compact?: boolean }) {
  const mode = useUiMode();
  const w = why || explain(reason);
  if (!w.original && !w.headline) return null;
  if (mode === "advanced" && !compact) {
    return <div className="why"><div className="small">{w.original || w.headline}</div>
      {w.matched && <div className="small faint">In plain words: {w.headline}</div>}</div>;
  }
  return (
    <div className={`why${compact ? " compact" : ""}`}>
      <div className="why-head">{w.headline}</div>
      {w.do && <div className="why-do"><span className="k">What to do</span> {w.do}</div>}
      {w.original && w.original !== w.headline && !compact &&
        <details><summary className="small">More detail</summary><div className="small faint">{w.original}</div></details>}
    </div>
  );
}

/** WAIT / PRACTICE IDEA / STOPPED word. The original action is kept in the tooltip. */
export function ActionWord({ a, big }: { a?: string | null; big?: boolean }) {
  const w = actionWord(a);
  return <span className={`aword t-${w.tone}${big ? " big" : ""}`} title={a ? `Shown in Advanced as: ${a}` : undefined}>{w.word}</span>;
}

function Dialog({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="dialog-back" role="presentation" onClick={onClose}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2>{children}
      </div>
    </div>
  );
}

export function StopEverything() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const go = async () => {
    setBusy(true); setErr(null);
    try { setRes(await api("/stop-everything", { method: "POST", json: { confirm: true } })); reloadHome(); }
    catch (e: any) { setErr(e.message || "Study Terminal didn't answer."); }
    finally { setBusy(false); }
  };
  const close = () => { setOpen(false); setRes(null); setErr(null); };
  return (
    <>
      <button className="stop-all" onClick={() => setOpen(true)} title="Stops all watching and all practice trading that Study Terminal is doing by itself">Stop everything</button>
      {open && <Dialog title={res ? "Everything is stopped" : "Stop everything?"} onClose={close}>
        {!res ? <>
          <p>This stops Study Terminal from watching your chart and from doing anything by itself:</p>
          <ul className="plain-list">
            <li>It stops watching your chart and checking the market.</li>
            <li>It cancels practice orders that Study Terminal placed by itself and closes the practice trades it was managing.</li>
            <li>Practice trades you placed yourself are left as they are.</li>
          </ul>
          <p className="muted">Your real TopstepX account is never touched. Study Terminal can't place, change or cancel real orders.</p>
          {err && <div className="note bad">Stopping didn't work: {err} Quit Study Terminal from the tray icon to stop it completely.</div>}
          <div className="row end"><button onClick={close}>Cancel</button><button className="stop-all" disabled={busy} onClick={go}>{busy ? "Stopping…" : "Yes, stop everything"}</button></div>
        </> : <>
          <ul className="plain-list">
            {res.done.map((d: string) => <li key={d}>{d}</li>)}
            {res.failed.map((d: string) => <li key={d} className="down">{d}</li>)}
            {(res.practice_orders_cancelled > 0 || res.practice_trades_closed > 0) &&
              <li>{res.practice_orders_cancelled} practice orders cancelled, {res.practice_trades_closed} practice trades closed.</li>}
            {res.practice_trades_waiting_to_close > 0 && <li>{res.practice_trades_waiting_to_close} practice trades will close at the next usable price.</li>}
          </ul>
          <p className="muted">{res.left_alone} {res.real_account}</p>
          <p>To start again, go to Home and follow "What should I do next?".</p>
          <div className="row end"><a className="btn" href="#/home" onClick={close}>Go to Home</a><button className="primary" onClick={close}>OK</button></div>
        </>}
      </Dialog>}
    </>
  );
}

/** Row 1 of every screen: brand, practice badge, health light, Simple/Advanced, Stop everything. */
export function TopBar({ connected }: { connected: boolean }) {
  const h = useHome();
  const mode = useUiMode();
  const offline = !connected && h.failures >= 2;
  const hl = offline ? { level: "bad", word: "Not working", sentence: "Study Terminal's engine isn't answering." }
    : h.data?.health || { level: "off", word: "Starting…", sentence: "Checking that everything is running." };
  return (
    <div className="topbar" role="banner">
      <a className="brand" href="#/home"><span className="brand-mark" />Study Terminal</a>
      <span className="practice" title={h.data?.mode?.note || "Everything here uses pretend money. Study Terminal can't place real orders."}>
        <b>PRACTICE MODE</b><span>no real money</span>
      </span>
      <a className={`health h-${LEVEL_CLASS[hl.level] || "off"}`} href="#/home" role="status" aria-live="polite" title={hl.sentence}>
        <i className="lamp" aria-hidden /><b>{hl.word}</b><span className="health-text">{hl.sentence}</span>
      </a>
      <span className="grow" />
      <span className="seg" role="group" aria-label="How much detail to show">
        {(["simple", "advanced"] as const).map((m) =>
          <button key={m} className={mode === m ? "on" : ""} aria-pressed={mode === m} onClick={() => setUiMode(m)}
            title={m === "simple" ? "Plain words and only what you need" : "Every tool and the full trading terms. Your limits and safety rules are the same in both."}>
            {m === "simple" ? "Simple" : "Advanced"}</button>)}
      </span>
      <StopEverything />
    </div>
  );
}

export function OfflineBanner({ connected }: { connected: boolean }) {
  const h = useHome();
  if (connected || h.failures < 2) return null;
  return (
    <div className="banner bad" role="alert">
      <b>Study Terminal's engine isn't running, so nothing on this screen is up to date.</b>
      <span>Quit Study Terminal from its icon near the clock (right-click, then Quit) and open it again. Your saved practice trades and settings are safe.</span>
    </div>
  );
}

/** Always-visible risk line in plain words (Simple mode). */
export function SimpleStrip({ trades, onTrades }: { trades: string; onTrades: (m: string) => void }) {
  const h = useHome();
  const r = h.data?.risk;
  const stopped = r?.new_trades === "stopped";
  const cell = (k: React.ReactNode, v: React.ReactNode, cls = "") => <div className="cell"><span className="k">{k}</span><span className={`v ${cls}`}>{v}</span></div>;
  return (
    <div className="strip simple" role="status" aria-label="Your practice account">
      <div className="cell"><span className="k">I'm practicing</span><span className="v row" style={{ gap: 4 }}>
        {[["futures", "Futures"], ["equities", "Stocks"]].map(([m, l]) =>
          <button key={m} className={`small ${trades === m ? "primary" : "ghost"}`} onClick={() => onTrades(m)}>{l}</button>)}</span></div>
      {cell("Practice money", r ? money(r.practice_money, 0) : "Loading…")}
      {cell("Today so far", r ? money(r.today) : "Loading…", sign(r?.today))}
      {cell(<Term k="dll">Most you can still lose today</Term>, r ? (r.can_lose_today != null ? money(r.can_lose_today, 0) : "No limit set") : "Loading…")}
      {cell(<Term k="open_risk">At risk right now</Term>, r ? (r.at_risk_now != null ? money(r.at_risk_now, 0) : `${r.open_trades ?? 0} open`) : "Loading…")}
      {cell("New practice trades", r ? (stopped ? "Stopped" : "Allowed") : "Loading…", stopped ? "down" : "")}
      {r && !r.limits_confirmed && <div className="cell"><span className="k">Loss limits</span><span className="v"><a href="#/futures">Not confirmed yet</a></span></div>}
    </div>
  );
}

/** Server-written sentences (alerts, toasts) in plain words while in Simple mode. */
export const Say = ({ t }: { t?: string | null }) => { useUiMode(); return <>{isSimple() ? say(t) : t}</>; };

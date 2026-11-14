// Home: five questions, five plain answers, and what to do next. Reads GET /api/home only.
import { useState } from "react";
import { api, money } from "./lib";
import { reloadHome, useHome, useUiMode } from "./plain";
import { LEVEL_CLASS, Term, WhyBlock } from "./simple";
import { LivePrice } from "./livechart";
import { Countdown } from "./markethours";

const clock = (iso?: string | null) => { if (!iso) return null; const d = new Date(iso); return Number.isNaN(d.getTime()) ? null : d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); };

function Row({ n, q, children, tone }: { n: number; q: string; children: React.ReactNode; tone?: string }) {
  return (
    <section className={`qa ${tone || ""}`} aria-label={q}>
      <div className="q"><span className="qn">{n}</span><h2>{q}</h2></div>
      <div className="a">{children}</div>
    </section>
  );
}

function SetupGuide({ setup }: { setup: any }) {
  const [busy, setBusy] = useState(false);
  const save = async (json: any) => { setBusy(true); try { await api("/settings", { method: "PUT", json }); await reloadHome(); } finally { setBusy(false); } };
  return (
    <section className="guide" aria-label="Getting started">
      <div className="spread">
        <div><h2>Getting started</h2><span className="muted">{setup.progress}. Each step shows a tick when it's really done.</span></div>
        <button className="ghost" onClick={() => save({ "ui.setup_dismissed": true })}>Hide this guide</button>
      </div>
      <ol>
        {setup.steps.map((s: any, i: number) => {
          const cur = s.id === setup.current;
          return (
            <li key={s.id} className={s.done ? "done" : cur ? "cur" : ""}>
              <span className="tick" aria-hidden>{s.done ? "✓" : i + 1}</span>
              <div>
                <b>{s.title}</b>{s.done && <span className="muted"> · done</span>}
                {(cur || s.id === "choose") && !s.done && <div className="muted">{s.text}</div>}
                {s.id === "choose" && !s.done && <div className="row" style={{ marginTop: 8 }}>
                  <button className="primary" disabled={busy} onClick={() => save({ "app.market_mode": "futures", "ui.trades_chosen": true })}>Futures (TopstepX)</button>
                  <button disabled={busy} onClick={() => save({ "app.market_mode": "equities", "ui.trades_chosen": true })}>Stocks</button>
                </div>}
                {cur && s.link && <div style={{ marginTop: 8 }}><a className="btn primary" href={s.link}>{s.button}</a></div>}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function StartAgain({ emergency }: { emergency: any }) {
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const go = async () => {
    try { await api("/start-again", { method: "POST", json: { note } }); setErr(null); await reloadHome(); }
    catch (e: any) { setErr(e.message); }
  };
  return (
    <section className="guide stopped" aria-label="Everything is stopped">
      <h2>Everything is stopped</h2>
      <p>Nothing is being watched and Study Terminal isn't practicing anything by itself{clock(emergency?.at) ? ` (stopped at ${clock(emergency.at)})` : ""}.
        Before starting again, write one sentence about why you stopped. It goes in your record so you can look back on it.</p>
      <div className="row">
        <input style={{ flex: 1, minWidth: 260 }} value={note} onChange={(e) => setNote(e.target.value)} placeholder="For example: I wanted a break after two losing practice trades." aria-label="Why you stopped" />
        <button className="primary" disabled={note.trim().length < 10} onClick={go}>Start again</button>
      </div>
      {err && <div className="note bad">{err}</div>}
      <div className="small muted">Starting again clears the stop. Watching stays off until you turn it on.</div>
    </section>
  );
}

export function Home() {
  const h = useHome();
  const mode = useUiMode();
  const d = h.data;
  if (!d) {
    return <div className="page home"><div className="sheet"><p className="muted">{h.failures >= 2
      ? "Study Terminal's engine isn't answering. Quit Study Terminal from its icon near the clock and open it again."
      : "Loading…"}</p></div></div>;
  }
  const { health, market, decision, risk, next, setup } = d;
  const fut = d.trades === "futures";
  return (
    <div className="page home">
      {d.stopped && <StartAgain emergency={d.emergency} />}
      {setup.show && !d.stopped && <SetupGuide setup={setup} />}
      {fut && <LivePrice />}
      <div className="sheet">
        <Row n={5} q="What should I do next?" tone={`next k-${next.kind}`}>
          <div className="big-line"><b>{next.title}.</b> {next.text}</div>
          {next.link && next.button && next.link !== "#/home" && <a className="btn primary" href={next.link}>{next.button}</a>}
        </Row>
        <div className="home-grid">
        <Row n={3} q="Should I practice a trade or wait?" tone={`t-${decision.tone}`}>
          <div className="verdict"><span className={`aword big t-${decision.tone}`}>{decision.word}</span>
            {decision.contract && <span className="muted">{decision.contract}{clock(decision.as_of) ? ` · ${clock(decision.as_of)}` : ""}</span>}</div>
          <WhyBlock why={{ headline: decision.headline, do: decision.do, kind: "", original: decision.original, matched: true }} />
          {decision.plan && <div className="plan">
            <div className="plan-title">{decision.watch_only ? "The idea I noticed (for watching, not trading)" : "The practice plan"}: price going <b>{decision.plan.direction}</b></div>
            <dl>
              <div><dt><Term k="entry" /></dt><dd>{decision.plan.start_price}</dd></div>
              <div><dt><Term k="stop" /></dt><dd>{decision.plan.exit_if_wrong}</dd></div>
              <div><dt><Term k="target" /></dt><dd>{decision.plan.take_gain ?? "—"}</dd></div>
              <div><dt>You could lose</dt><dd className="down">{decision.plan.could_lose_usd != null ? `about ${money(decision.plan.could_lose_usd, 0)}` : "—"}</dd></div>
              <div><dt>You could gain</dt><dd className="up">{decision.plan.could_gain_usd != null ? `about ${money(decision.plan.could_gain_usd, 0)}` : "—"}</dd></div>
              <div><dt><Term k="contract">Contracts</Term></dt><dd>{decision.plan.contracts}</dd></div>
            </dl>
            <div className="small faint">{decision.plan.note}{decision.plan.cancelled_if ? ` The plan is cancelled if: ${decision.plan.cancelled_if}` : ""}</div>
          </div>}
          <div className="small muted">{decision.note}{decision.confidence ? ` Chart reading: ${decision.confidence}. ${decision.confidence_note}` : ""}</div>
        </Row>

        <Row n={4} q="How much could I lose?">
          <div className="big-line">{risk.at_risk_now ? <>You have <b>{money(risk.at_risk_now, 0)}</b> at risk right now.</> : (risk.open_trades ? <>You have {risk.open_trades} open practice {risk.open_trades === 1 ? "trade" : "trades"}.</> : <>Nothing is at risk right now.</>)}
            {" "}{risk.can_lose_today != null
              ? <>Today you can lose up to <b>{money(risk.can_lose_today, 0)}</b> more before new practice trades are stopped.</>
              : <>No daily loss limit is set.</>}</div>
          {risk.new_trades === "stopped" && risk.stopped_why.map((w: any, i: number) => <WhyBlock key={i} why={w} />)}
          <dl className="facts">
            <div><dt>Practice money</dt><dd>{money(risk.practice_money, 0)}</dd></div>
            <div><dt>Today so far</dt><dd className={risk.today > 0 ? "up" : risk.today < 0 ? "down" : ""}>{money(risk.today)}</dd></div>
            {risk.left_before_account_fails != null && <div><dt><Term k="mll" /></dt><dd>{money(risk.left_before_account_fails, 0)}</dd></div>}
            {risk.trades_today != null && <div><dt>Practice trades today</dt><dd>{risk.trades_today}</dd></div>}
          </dl>
          {risk.warnings?.map((w: string) => <div key={w} className="note warn">{w}</div>)}
          {!risk.limits_confirmed && <div className="why-do"><span className="k">Not confirmed yet</span> These limits come from a standard {risk.rules_name || "account"} template.
            Check them against your own account. <a href="#/futures">Check my limits</a></div>}
          <div className="small faint">{risk.note}{risk.can_lose_today_from ? ` The amount above comes from ${risk.can_lose_today_from}.` : ""}</div>
        </Row>

        </div>
        <div className="home-grid">
        <Row n={1} q="Is Study Terminal working?">
          <div className={`big-line h-${LEVEL_CLASS[health.level]}`}><i className="lamp" aria-hidden /><b>{health.word}.</b> {health.sentence}</div>
          {health.do && <div className="why-do"><span className="k">What to do</span> {health.do} {health.link && health.button && <a href={health.link}>{health.button}</a>}</div>}
          <details><summary className="small">What I checked</summary>
            <ul className="checks">{health.checks.map((c: any) => <li key={c.id} className={`h-${LEVEL_CLASS[c.level]}`}><i className="lamp" aria-hidden />
              <span><b>{c.name}:</b> {c.text}{mode === "advanced" && c.detail ? <span className="faint"> ({c.detail})</span> : null}</span></li>)}</ul>
          </details>
        </Row>

        <Row n={2} q="What is the market doing?">
          <div className="big-line">{market.sentence}{market.closed && market.opens_at ? <> <span className="muted small"><Countdown to={market.opens_at} /></span></> : null}</div>
          {market.details?.length > 0 && <ul className="plain-list">{market.details.map((t: string) => <li key={t}>{t.includes("open Charts") ? <>{t.replace(": open Charts to watch them live.", ":")} <a href="#/chart/BTC-USD">Bitcoin</a> · <a href="#/chart/ETH-USD">Ethereum</a></> : t}</li>)}</ul>}
          {market.source && <div className="small faint">{market.source}{clock(market.as_of) ? ` Read at ${clock(market.as_of)}.` : ""}
            {market.confidence ? <> <Term k="data_confidence">How sure I am about the reading</Term>: {market.confidence}.</> : null}</div>}
          {!market.known && fut && <div className="why-do"><span className="k">What to do</span> {health.level === "bad" && health.do ? health.do : "Connect your chart and turn watching on."} <a href="#/visual">Open my chart</a></div>}
        </Row>

        </div>
      </div>

      {d.recent?.length > 0 && <section className="recent" aria-label="What happened recently">
        <h2>What happened recently</h2>
        <ul>{d.recent.map((r: any, i: number) => <li key={i}><span className="faint">{clock(r.at) || r.time || ""} {r.contract}</span> {r.sentence}</li>)}</ul>
        {mode === "advanced" && <a className="small" href="#/automation">Every decision with all of its steps</a>}
      </section>}
      <p className="small faint foot">{d.mode.note}{d.backup?.made ? ` A backup of your data was made before this version first started: ${d.backup.path}` : ""}</p>
    </div>
  );
}

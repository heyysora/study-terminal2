// Data Health: what Study Terminal has checked about its own data, in plain words first, with the full detail underneath.
import { useState } from "react";
import { api, usePoll } from "./lib";

const TONE: Record<string, string> = { VERIFIED: "up", HEALTHY: "up", DELAYED: "warn-link", DEGRADED: "down", STALE: "down", CONFLICTING: "down",
  UNVERIFIED: "warn-link", OFFLINE: "down", UNSUPPORTED: "muted" };
const STATE: Record<string, [string, string]> = { pass: ["Passing", "up"], fail: ["Failing", "down"], questionable: ["Sources disagree", "down"],
  unknown: ["Not confirmed", "warn-link"], unsupported: ["Not available", "muted"] };
const when = (iso?: string | null) => iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "not yet";
const ago = (iso?: string | null) => { if (!iso) return "not yet"; const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000)); return s < 90 ? `${s} s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`; };

function Source({ s, legend }: { s: any; legend: any }) {
  const feats = Object.entries(s.features || {}) as [string, any][];
  const cmp = Object.entries(s.symbols || {}).filter(([, v]: any) => v?.comparison?.values) as [string, any][];
  return (
    <section className="qa">
      <div className="spread"><h3 style={{ margin: 0 }}>{s.name}</h3><b className={TONE[s.status] || ""} title={legend?.[s.status]?.[0]}>{s.word || s.status}</b></div>
      <div>{s.explain && s.status !== "VERIFIED" && s.status !== "HEALTHY" ? s.explain : s.why}</div>
      <div className="small muted">
        {s.status === "UNSUPPORTED" ? "Not connected." : <>Last checked {ago(s.checked_at)}{s.from_previous_run ? " (before the last restart; checking again now)" : ""} · last good {s.last_good_at ? ago(s.last_good_at) : s.status === "VERIFIED" || s.status === "HEALTHY" || s.status === "DELAYED" ? ago(s.checked_at) : "never yet"}
          {s.latency_ms != null ? ` · answers in about ${s.latency_ms} ms` : ""}</>}
        {" · "}<b className={s.signals_permitted ? "up" : "muted"}>{s.source === "topstepx_chart" ? "Never gives trade ideas by itself" : s.signals_permitted ? "May give trade ideas" : "May not give trade ideas"}</b>
      </div>
      {s.coverage?.fields > 0 && <div className="small">{s.coverage.text}</div>}
      {feats.length > 0 && <details><summary className="small">What was checked ({feats.length})</summary>
        <table className="small"><tbody>{feats.map(([k, f]) => <tr key={k}><td style={{ whiteSpace: "nowrap", verticalAlign: "top" }}><b>{k}</b></td>
          <td style={{ whiteSpace: "nowrap", verticalAlign: "top" }} className={STATE[f.state]?.[1]}>{STATE[f.state]?.[0] || f.state}{f.independent && f.state === "pass" ? " (independent)" : ""}</td>
          <td className="faint">{f.detail}</td></tr>)}</tbody></table></details>}
      {cmp.length > 0 && <details><summary className="small">Prices from each source ({cmp.length})</summary>
        <table className="small"><thead><tr><th>What</th><th>Each source's own price</th><th>Biggest gap</th><th>Allowed</th></tr></thead>
          <tbody>{cmp.map(([k, v]) => <tr key={k}><td>{v.symbol || (k.length > 12 ? `${k.slice(0, 4)}…${k.slice(-4)}` : k)}</td>
            <td>{Object.entries(v.comparison.values).map(([n, p]: any) => `${n} ${Number(p) >= 1 ? Number(p).toLocaleString(undefined, { maximumFractionDigits: 2 }) : Number(p).toPrecision(4)}`).join(" · ")}
              {v.comparison.silent?.length ? <span className="faint"> · no answer: {v.comparison.silent.join(", ")}</span> : null}</td>
            <td className={v.comparison.ok === false ? "down" : ""}>{v.comparison.max_diff_pct != null ? `${v.comparison.max_diff_pct}%` : "—"}</td>
            <td>{v.comparison.tolerance_pct != null ? `${v.comparison.tolerance_pct}%` : "—"}</td></tr>)}</tbody></table>
        <div className="small faint">Prices are never averaged. If two sources disagree by more than allowed, neither is trusted.</div></details>}
      {s.chart && <Chart c={s.chart} />}
    </section>
  );
}

function Chart({ c }: { c: any }) {
  const n = c.counts;
  return (
    <details open={n.real_readings > 0}><summary className="small">Automatic chart validation on this PC</summary>
      <div className="stack small" style={{ marginTop: 6 }}>
        <div>{n.real_readings} readings of your chart · {n.compared} compared with reference prices · <b className="up">{n.matched} matched</b> · <b className={n.mismatched ? "down" : ""}>{n.mismatched} didn't</b> · {n.waiting} waiting to be compared</div>
        <div className="faint">{c.rules} {c.note}</div>
        <div><b>Situations seen on this PC</b> (recorded when they happen; Study Terminal never clicks or types in TopstepX):</div>
        <table><tbody>{c.scenarios.map((x: any) => <tr key={x.key}><td>{x.name}</td><td className={x.count ? "up" : "muted"}>{x.count ? `seen ${x.count}×, last ${when(x.last)}` : "not seen yet"}</td></tr>)}
          {Object.entries(c.cannot_observe).map(([k, v]: any) => <tr key={k}><td>{k}</td><td className="faint">Can't be tested automatically. {v}</td></tr>)}</tbody></table>
        {c.recent.length > 0 && <details><summary>Latest readings</summary><table><thead><tr><th>When</th><th>Chart</th><th>Price read</th><th>Reference range</th><th>Result</th></tr></thead>
          <tbody>{c.recent.slice(0, 15).map((r: any, i: number) => <tr key={i}><td>{when(r.at)}</td><td>{r.symbol || "—"} {r.timeframe}</td><td>{r.price ?? "—"}</td>
            <td>{r.ref_low != null ? `${r.ref_low} – ${r.ref_high}` : "—"}</td><td className={r.outcome === "match" ? "up" : r.outcome === "mismatch" ? "down" : "muted"}>{r.outcome.replace("_", " ")}{r.real ? "" : " (test source)"}</td></tr>)}</tbody></table></details>}
      </div>
    </details>
  );
}

export function DataHealth() {
  const h = usePoll("/datahealth", 15000);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const d = h.data;
  const run = async () => { setBusy(true); setMsg(null); try { await api("/datahealth/run", { method: "POST" }); h.reload(); setMsg("Checked every source just now."); } catch (e: any) { setMsg(e.message); } finally { setBusy(false); } };
  if (!d) return <div className="page home"><section className="guide">{h.error ? <div className="note bad">{h.error}</div> : "Checking your data…"}</section></div>;
  const groups: [string, string][] = [["stocks", "Stocks"], ["futures", "Futures"], ["crypto", "Crypto"], ["memecoins", "Solana memecoins"]];
  const tone = d.tone === "ok" ? "up" : d.tone === "bad" ? "down" : "warn-link";
  return (
    <div className="page home">
      <section className={`qa next${d.tone === "bad" ? " k-fix" : ""}`}>
        <div className="q"><h2>Can I trust the data right now?</h2></div>
        <div className="a"><div className="big-line"><b className={tone}>{d.tone === "ok" ? "The checks are passing. " : d.tone === "bad" ? "Not all of it. " : d.tone === "idle" ? "" : "Checking. "}</b>{d.overall}</div>
          <div className="small muted">Study Terminal checks its data by itself, all the time. You don't need to do anything here. {d.note}</div></div>
      </section>
      {d.safety && <section className="qa"><div className="q"><h2>Which markets may give trade ideas right now?</h2></div>
        <div className="a"><dl className="facts">{groups.map(([k, n]) => { const m = d.safety.markets[k]; return <div key={k}><dt>{n}</dt><dd className={m.allowed ? "up" : "down"} title={m.reason}>{m.allowed ? "Allowed" : "Paused"}</dd></div>; })}</dl>
          {groups.filter(([k]) => !d.safety.markets[k].allowed).map(([k, n]) => <div key={k} className="small"><b>{n}:</b> {d.safety.markets[k].reason}</div>)}
          <div className="small faint">One safety check sits in front of every market. It can only pause ideas; it can't place or change anything. Crypto is watch-only either way.</div></div></section>}
      {d.flagged_positions.length > 0 && <section className="qa next k-fix"><div className="q"><h2>Open practice trades with untrusted data</h2></div>
        <div className="a">{d.flagged_positions.map((p: any, i: number) => <div key={i}><b>{p.name || p.symbol}</b> ({p.account}): {p.warning}</div>)}</div></section>}
      {groups.map(([k, n]) => { const list = d.sources.filter((s: any) => s.market === k); return list.length ? <section key={k} className="guide stack">
        <h2 style={{ margin: 0 }}>{n}</h2><div className="sheet">{list.map((s: any) => <Source key={s.source} s={s} legend={d.legend} />)}</div></section> : null; })}
      <section className="guide stack">
        <h2 style={{ margin: 0 }}>Outages and recoveries</h2>
        {d.outages.length === 0 ? <div className="muted">None recorded.</div> : <table className="small"><thead><tr><th>Source</th><th>Started</th><th>Came back</th><th>Lasted</th><th>Why</th></tr></thead>
          <tbody>{d.outages.map((o: any, i: number) => <tr key={i}><td>{o.source.replace(/_/g, " ")}</td><td>{when(o.started_at)}</td><td className={o.ended_at ? "up" : "down"}>{o.ended_at ? when(o.ended_at) : "still down"}</td>
            <td>{o.minutes != null ? `${o.minutes} min` : "—"}</td><td className="faint">{o.reason}</td></tr>)}</tbody></table>}
      </section>
      <section className="guide stack">
        <h2 style={{ margin: 0 }}>What the words mean</h2>
        <table className="small"><tbody>{Object.entries(d.legend).map(([k, v]: any) => <tr key={k}><td><b className={TONE[k]}>{k[0] + k.slice(1).toLowerCase()}</b></td><td>{v[0]}</td><td className="faint">{v[1]}</td></tr>)}</tbody></table>
        <div className="row"><button onClick={run} disabled={busy}>{busy ? "Checking…" : "Check everything now"}</button>
          <a className="btn ghost" href="/api/datahealth/report" target="_blank" rel="noreferrer">Full technical report</a></div>
        {msg && <div className="note small">{msg}</div>}
        <div className="small faint">Checks version {d.test_version} · app {d.app_version} · results are kept on this PC for 45 days.</div>
      </section>
    </div>
  );
}

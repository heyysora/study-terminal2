import { useEffect, useState } from "react";
import { CandleChart, LineChart, Panel } from "./components";
import { TIMEFRAMES, api, etDate, etTime, money, num, pct, sign, useLive, usePoll } from "./lib";
import { Diagnostics, Evidence } from "./pages3";

// ======================= Backtest + ML =======================
export function Backtest() {
  const settings = usePoll("/settings");
  const runs = usePoll("/backtest/runs");
  const cal = usePoll("/calibration");
  const ml = usePoll("/ml");
  const [f, setF] = useState<any>({ symbols: "SPY, QQQ, AAPL, TSLA, NVDA, AMD", timeframe: "5Min", days: 58, mode: "walk_forward",
    setups: [] as string[], slippage_bps: 1, slippage_min: 0.01, commission_per_share: 0, risk_pct: 0.5, allow_short: true, train_sessions: 20, test_sessions: 5 });
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [mlMsg, setMlMsg] = useState<any>(null);
  const setups: Record<string, string> = settings.data?.setups || {};
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      const body = { ...f, symbols: f.symbols.split(/[ ,]+/).filter(Boolean), setups: f.setups.length ? f.setups : null, days: Number(f.days) };
      setRes(await api("/backtest", { method: "POST", json: body }));
      runs.reload(); cal.reload();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const load = async (id: number) => setRes(await api(`/backtest/runs/${id}`));
  const train = async () => { setMlMsg(null); try { setMlMsg(await api("/ml/train", { method: "POST" })); ml.reload(); } catch (e: any) { setMlMsg({ reason: e.message }); } };
  const m = res?.metrics;
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  return (
    <div className="page">
      <Panel title="Test a strategy on history" sub="same setups and fill rules as live practice trading" right={<button className="primary" onClick={run} disabled={busy}>{busy ? "Running… (walk-forward can take a few minutes)" : "Run"}</button>}>
        <div className="stack">
          <div className="form">
            <label className="f" style={{ gridColumn: "span 2" }}>Symbols<input value={f.symbols} onChange={set("symbols")} /></label>
            <label className="f">Timeframe<select value={f.timeframe} onChange={set("timeframe")}>{TIMEFRAMES.map((t) => <option key={t}>{t}</option>)}</select></label>
            <label className="f">Days of history<input type="number" value={f.days} onChange={set("days")} /></label>
            <label className="f">Mode<select value={f.mode} onChange={set("mode")}><option value="walk_forward">Walk-forward (honest, calibrates signals)</option><option value="backtest">Backtest with time split</option><option value="optimize">Parameter optimization (in-sample)</option></select></label>
            <label className="f">Risk per trade %<input type="number" step="0.1" value={f.risk_pct} onChange={set("risk_pct")} /></label>
            <label className="f">Slippage (bps)<input type="number" step="0.5" value={f.slippage_bps} onChange={set("slippage_bps")} /></label>
            <label className="f">Min slippage ($/sh)<input type="number" step="0.01" value={f.slippage_min} onChange={set("slippage_min")} /></label>
            <label className="f">Commission ($/sh)<input type="number" step="0.001" value={f.commission_per_share} onChange={set("commission_per_share")} /></label>
            {f.mode === "walk_forward" && <><label className="f">Train sessions<input type="number" value={f.train_sessions} onChange={set("train_sessions")} /></label>
              <label className="f">Test sessions<input type="number" value={f.test_sessions} onChange={set("test_sessions")} /></label></>}
          </div>
          <div className="row">{Object.entries(setups).map(([k, v]) => <label key={k} className="check"><input type="checkbox" checked={f.setups.includes(k)} onChange={(e) => setF({ ...f, setups: e.target.checked ? [...f.setups, k] : f.setups.filter((x: string) => x !== k) })} />{v}</label>)}
            <span className="small faint">none checked = all setups</span></div>
          <label className="check"><input type="checkbox" checked={f.allow_short} onChange={set("allow_short")} />Include short setups</label>
          <p className="small muted">Yahoo limits intraday history: 1-minute about 7 days, 2–30 minute about 60 days, hourly about 2 years. Costs (slippage, commission) are always charged.</p>
          {err && <div className="note bad">{err}</div>}
        </div>
      </Panel>

      {res && (res.results ? (
        <Panel title="Optimization results" sub="in-sample" flush>
          <div className="note warn" style={{ margin: 12 }}>{res.warning}</div>
          <table><thead><tr><th>Parameters</th><th className="r">Trades</th><th className="r">Win %</th><th className="r">Avg R</th><th className="r">Profit factor</th><th className="r">Max DD</th></tr></thead>
            <tbody>{res.results.map((r: any, i: number) => <tr key={i}><td>{Object.entries(r.params).map(([k, v]) => `${k}=${v}`).join(", ")}</td><td className="r">{r.metrics.trades}</td>
              <td className="r">{num(r.metrics.win_rate, 1)}</td><td className={`r ${sign(r.metrics.expectancy_r)}`}>{num(r.metrics.expectancy_r, 3)}</td><td className="r">{num(r.metrics.profit_factor)}</td><td className="r">{num(r.metrics.max_drawdown_pct)}%</td></tr>)}</tbody></table>
        </Panel>) : m && (
        <div className="stack">
          <div className="note">{res.explanation}</div>
          {res.notes?.map((n: string, i: number) => <div key={i} className="note small">{n}</div>)}
          <section className="panel"><div className="strip" style={{ borderBottom: 0 }}>
            {[["Trades", m.trades], ["Win rate", m.win_rate != null ? `${m.win_rate}%` : "—"], ["Avg R", num(m.expectancy_r, 3)], ["Avg R before costs", num(m.expectancy_r_before_costs, 3)],
              ["Cost per trade", `${num(m.avg_cost_r, 3)}R`], ["Profit factor", num(m.profit_factor)], ["Expectancy", money(m.expectancy)], ["Avg win", money(m.avg_win)], ["Avg loss", money(m.avg_loss)],
              ["Max drawdown", `${num(m.max_drawdown_pct)}%`], ["Total return", pct(m.total_return_pct)], ["Sharpe", num(m.sharpe)], ["Avg hold", `${num(m.avg_hold_minutes, 0)} min`]]
              .map(([k, v]) => <div key={k as string} className="cell" style={{ padding: "8px 14px" }}><span className="k">{k}</span><span className="v">{v as any}</span></div>)}
          </div></section>
          {m.sample_warning && <div className="note warn">{m.sample_warning}</div>}
          <Evidence ev={res.evidence} title={res.out_of_sample ? "Statistical evidence (out-of-sample)" : "Statistical evidence (last part of the period only)"} />
          {res.search && <div className="note small">{res.search.note}</div>}
          <Diagnostics d={res.diagnostics} setupNames={setups} />
          <div className="note">Past results do not guarantee future results. A positive backtest is a reason to keep practice testing, not proof of an edge.</div>
          {res.equity?.length > 1 && <Panel title="Equity curve" sub={res.out_of_sample ? "out-of-sample only" : "full period"}><LineChart points={res.equity} /></Panel>}
          <div className="cols c-2">
            {[["By setup", res.by_setup], ["By market regime", res.by_regime], ["By symbol", res.by_symbol]].filter(([, d]) => d).map(([title, d]: any) => (
              <Panel key={title} title={title} flush><table><thead><tr><th /><th className="r">Trades</th><th className="r">Win %</th><th className="r">Avg R</th><th className="r">Net</th></tr></thead>
                <tbody>{Object.entries(d).map(([k, v]: any) => <tr key={k}><td>{setups[k] || k}</td><td className="r">{v.trades}</td><td className="r">{num(v.win_rate, 1)}</td><td className={`r ${sign(v.expectancy_r)}`}>{num(v.expectancy_r, 3)}</td><td className={`r ${sign(v.net_pnl)}`}>{money(v.net_pnl, 0)}</td></tr>)}</tbody></table></Panel>))}
            {res.folds && <Panel title="Walk-forward folds" flush><table><thead><tr><th>Train</th><th>Test</th><th>Chosen parameters</th><th className="r">Test trades</th><th className="r">Test avg R</th></tr></thead>
              <tbody>{res.folds.map((fo: any, i: number) => <tr key={i}><td>{fo.train.join(" to ")}</td><td>{fo.test.join(" to ")}</td><td className="small">{fo.skipped || Object.entries(fo.chosen_params || {}).map(([k, v]) => `${k}=${v}`).join(", ")}</td>
                <td className="r">{fo.test_metrics?.trades ?? "—"}</td><td className={`r ${sign(fo.test_metrics?.expectancy_r)}`}>{num(fo.test_metrics?.expectancy_r, 3)}</td></tr>)}</tbody></table></Panel>}
          </div>
          <Panel title="Trades" sub={`${res.trades.length}`} flush>
            <details style={{ padding: "4px 12px" }}><summary>Show trades</summary>
              <table><thead><tr><th>Entry</th><th>Symbol</th><th>Setup</th><th>Dir</th><th className="r">Entry</th><th className="r">Exit</th><th>Exit reason</th><th className="r">R</th><th className="r">P&amp;L</th><th>Regime</th></tr></thead>
                <tbody>{res.trades.slice(0, 500).map((t: any, i: number) => <tr key={i}><td>{etDate(t.entry_ts)} {etTime(t.entry_ts)}</td><td className="sym">{t.symbol}</td><td>{setups[t.setup] || t.setup}</td><td>{t.direction}</td>
                  <td className="r">{num(t.entry_price)}</td><td className="r">{num(t.exit_price)}</td><td className="muted">{t.exit_reason.replace("_", " ")}</td><td className={`r ${sign(t.r_multiple)}`}>{num(t.r_multiple)}</td><td className={`r ${sign(t.pnl)}`}>{money(t.pnl)}</td><td className="muted">{t.regime}</td></tr>)}</tbody></table>
            </details>
          </Panel>
        </div>))}

      <div className="cols c-2">
        <Panel title="Signal calibration" sub="from walk-forward, feeds signal confidence" flush>
          {!cal.data || !Object.keys(cal.data).length ? <div className="empty">No calibration yet. Run a walk-forward test. Until then, signals say "no out-of-sample history" instead of showing invented confidence.</div> :
            <table><thead><tr><th>Setup</th><th>Timeframe</th><th className="r">Trades</th><th className="r">Win %</th><th className="r">Avg R</th><th>Used?</th></tr></thead>
              <tbody>{Object.entries(cal.data).map(([k, v]: any) => { const [s, tf] = k.split("|"); return <tr key={k}><td>{setups[s] || s}</td><td>{tf}</td><td className="r">{v.trades}</td><td className="r">{num(v.win_rate, 1)}</td>
                <td className={`r ${sign(v.expectancy_r)}`}>{num(v.expectancy_r, 3)}</td><td className="small muted">{v.available ? (v.expectancy_r < 0 ? "yes: downgrades this setup" : "yes") : "too few trades"}</td></tr>; })}</tbody></table>}
        </Panel>
        <Panel title="Machine learning" sub="deployed only if it beats the base rate on unseen data" right={<button onClick={train}>Train on latest walk-forward</button>}>
          {mlMsg && <div className={`note ${mlMsg.deployed ? "" : "warn"}`}>{mlMsg.reason}</div>}
          {ml.data?.model ? (
            <div className="stack small">
              <div>Model {ml.data.model.version} ({ml.data.model.model}): <b>{ml.data.model.deployed ? "deployed" : "not deployed"}</b></div>
              <div className="muted">{ml.data.model.reason}</div>
              <table><thead><tr><th>Candidate</th><th className="r">Brier skill</th><th className="r">AUC</th><th className="r">Precision</th><th className="r">Recall</th></tr></thead>
                <tbody>{Object.entries(ml.data.model.candidates).map(([k, v]: any) => <tr key={k}><td>{k}</td><td className="r">{v.brier_skill}</td><td className="r">{v.auc}</td><td className="r">{v.precision}</td><td className="r">{v.recall}</td></tr>)}</tbody></table>
              <div className="muted">Trained {ml.data.model.train_period?.map((x: string) => x.slice(0, 10)).join(" to ")}, tested {ml.data.model.test_period?.map((x: string) => x.slice(0, 10)).join(" to ")} ({ml.data.model.n_test} unseen trades).</div>
              <details><summary>Calibration and feature importance</summary>
                <table><tbody>{ml.data.model.calibration.map((c: any) => <tr key={c.bin}><td>predicted {c.bin}</td><td className="r">n={c.n}</td><td className="r">actual {num(c.actual * 100, 0)}%</td></tr>)}</tbody></table>
                <table><tbody>{ml.data.model.feature_importance.map((f: any) => <tr key={f.feature}><td>{f.feature}</td><td className="r">{f.importance}</td></tr>)}</tbody></table></details>
              {ml.data.drift?.available && <div>Drift: {ml.data.drift.status}. <span className="muted">{ml.data.drift.note}</span></div>}
            </div>) : <p className="muted">No model trained yet. A simple rule with a real edge beats an impressive model without one.</p>}
        </Panel>
      </div>
      <Panel title="Previous runs" flush>
        {!runs.data?.length ? <div className="empty">No runs yet.</div> :
          <table><tbody>{runs.data.map((r: any) => <tr key={r.id} className="click" onClick={() => load(r.id)}><td>{etDate(r.created_at)} {etTime(r.created_at)}</td><td>{r.kind.replace("_", "-")}</td>
            <td>{r.config?.symbols?.join(", ")}</td><td>{r.config?.timeframe}</td><td className="r">{r.metrics?.trades ?? "—"} trades</td><td className={`r ${sign(r.metrics?.expectancy_r)}`}>{num(r.metrics?.expectancy_r, 3)}R</td></tr>)}</tbody></table>}
      </Panel>
    </div>
  );
}

// ======================= Learning center =======================
export function Learn({ id }: { id?: string }) {
  const lessons = usePoll("/learn/lessons", 0, [id]);
  const prog = usePoll("/learn/progress", 0, [id]);
  const [g, setG] = useState("");
  const gloss = usePoll(`/learn/glossary${g ? `?q=${encodeURIComponent(g)}` : ""}`);
  if (id === "exercise") return <Exercise />;
  if (id) return <Lesson id={id} />;
  const p = prog.data;
  return (
    <div className="page">
      <div className="cols c-side">
        <div className="stack">
          <Panel title="Your progress">
            {p && <div className="stack">
              <div className="spread"><span>{p.core_done} of {p.core_total} core lessons</span><span className="muted small">{p.quiz_attempts} quiz attempts</span></div>
              <div className="progress"><i style={{ width: `${(100 * p.core_done) / p.core_total}%` }} /></div>
              <h3>Recommended next</h3>
              {p.recommendations.map((r: any) => <div key={r.lesson}><a href={`#/learn/${r.lesson}`}>{r.title}</a><div className="small muted">{r.why}</div></div>)}
            </div>}
          </Panel>
          <Panel title="Chart exercise" sub="real historical charts">
            <p className="small muted">The chart stops right where a setup formed. Name the setup, then see what actually happened next.</p>
            <a href="#/learn/exercise" className="btn">Start an exercise</a>
          </Panel>
          <Panel title="Glossary" flush right={<input placeholder="Search terms" value={g} onChange={(e) => setG(e.target.value)} style={{ width: 150 }} aria-label="Search glossary" />}>
            <div style={{ maxHeight: 420, overflow: "auto" }}>
              {gloss.data && Object.entries(gloss.data).map(([k, v]) => <div key={k} style={{ padding: "6px 12px", borderBottom: "1px solid var(--rule)" }}><b>{k}</b><div className="small muted">{v as string}</div></div>)}
            </div>
          </Panel>
        </div>
        <Panel title="Lessons" flush>
          <table><tbody>{(lessons.data || []).map((l: any) => (
            <tr key={l.id} className="click" onClick={() => (location.hash = `#/learn/${l.id}`)}>
              <td>{l.completed ? <span className="up">✓</span> : <span className="faint">○</span>}</td><td><b>{l.title}</b>{l.module === "options" && <span className="small muted"> separate options module</span>}</td>
              <td className="muted">{l.level}</td><td className="r muted">{l.minutes} min</td><td className="r">{l.best_quiz != null ? `${l.best_quiz}%` : ""}</td></tr>))}</tbody></table>
        </Panel>
      </div>
    </div>
  );
}

function Lesson({ id }: { id: string }) {
  const l = usePoll(`/learn/lessons/${id}`);
  const [ans, setAns] = useState<number[]>([]);
  const [res, setRes] = useState<any>(null);
  useEffect(() => { setAns([]); setRes(null); }, [id]);
  const d = l.data;
  if (!d) return <div className="page muted">{l.error || "Loading…"}</div>;
  const submit = async () => setRes(await api(`/learn/lessons/${id}/quiz`, { method: "POST", json: { answers: ans } }));
  return (
    <div className="page" style={{ maxWidth: 860 }}>
      <a href="#/learn" className="small">Back to lessons</a>
      <h1>{d.title}</h1>
      <div className="small muted">{d.level}, about {d.minutes} minutes{d.prerequisite_titles?.length ? `. Builds on: ${d.prerequisite_titles.join(", ")}` : ""}</div>
      <section className="panel lesson"><div className="body">
        {d.sections.map((s: any) => <div key={s.heading}><h3>{s.heading}</h3><p>{s.body}</p></div>)}
        <p className="small muted">Key terms: {d.key_terms.join(", ")}</p>
      </div></section>
      <Panel title="Check your understanding" sub={`${d.quiz.length} questions`}>
        {d.quiz.map((q: any, i: number) => (
          <div key={i} style={{ marginBottom: 16 }}>
            <p><b>{q.q}</b></p>
            {q.options.map((o: string, j: number) => {
              const r = res?.results?.[i];
              const cls = r ? (j === r.answer ? "right" : j === ans[i] ? "wrong" : "") : ans[i] === j ? "sel" : "";
              return <button key={j} className={`quiz-opt ${cls}`} disabled={!!res} onClick={() => { const a = [...ans]; a[i] = j; setAns(a); }}>{o}</button>;
            })}
            {res?.results?.[i]?.explain && <div className="note small">{res.results[i].explain}</div>}
          </div>))}
        {!res ? <button className="primary" disabled={ans.filter((x) => x !== undefined).length < d.quiz.length} onClick={submit}>Check answers</button> :
          <div className="row"><b>{res.score}%</b><span className="muted">{res.passed ? "Lesson complete." : "Review the lesson and try again: 70% completes it."}</span>
            <button onClick={() => { setAns([]); setRes(null); }}>Try again</button></div>}
      </Panel>
      {d.exercise && <a href="#/learn/exercise" className="small">Practice this on a real chart</a>}
    </div>
  );
}

function Exercise() {
  const [ex, setEx] = useState<any>(null);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = async () => { setRes(null); setErr(null); try { setEx(await api("/learn/exercise", { method: "POST" })); } catch (e: any) { setErr(e.message); } };
  useEffect(() => { load(); }, []);
  const answer = async (c: string) => setRes(await api(`/learn/exercise/${ex.id}`, { method: "POST", json: { choice: c } }));
  const bars = ex ? (res ? [...ex.bars, ...res.future] : ex.bars) : [];
  const lines = res ? [{ price: res.trigger, title: "Trigger", color: "#e0a43a" }, { price: res.stop, title: "Stop", color: "#e5534b" }] : [];
  return (
    <div className="page">
      <a href="#/learn" className="small">Back to lessons</a>
      {err && <div className="note bad">{err}</div>}
      {ex && <div className="cols c-chart">
        <section className="panel"><CandleChart bars={bars} lines={lines} overlays={[{ name: "VWAP", data: ex.vwap, color: "#e0a43a", width: 2 }]} /></section>
        <Panel title={`${ex.symbol}, ${ex.timeframe}`} sub="real data">
          <p>{ex.question}</p>
          {ex.options.map((o: any) => <button key={o.id} className={`quiz-opt ${res ? (o.id === res.answer ? "right" : "") : ""}`} disabled={!!res} onClick={() => answer(o.id)}>{o.label}</button>)}
          {res && <div className="stack" style={{ marginTop: 10 }}>
            <div className={`note ${res.correct ? "" : "warn"}`}>{res.correct ? "Correct." : `It was a ${res.answer_label} (${res.direction}).`} {res.what_happened}</div>
            {res.lesson && <a href={`#/learn/${res.lesson}`}>Related lesson</a>}
            <button className="primary" onClick={load}>Next chart</button></div>}
          <p className="small faint" style={{ marginTop: 10 }}>{ex.note}</p>
        </Panel>
      </div>}
    </div>
  );
}

// ======================= Alerts =======================
export function Alerts() {
  const L = useLive();
  const h = usePoll("/alerts", 20000, [L.alerts.length]);
  const test = async () => { await api("/alerts/test", { method: "POST" }); h.reload(); };
  const list = h.data?.alerts || [];
  return (
    <div className="page">
      <Panel title="Alert history" sub={h.data ? `${h.data.sent} sent this session, ${h.data.suppressed_duplicates} duplicates suppressed. Desktop notifications ${h.data.desktop_notifications}.` : ""}
        right={<button onClick={test}>Send test alert</button>} flush>
        {!list.length ? <div className="empty">No alerts yet. They arrive when a setup develops, confirms or becomes invalid, when a position needs attention, or when market conditions change.</div> :
          list.map((a: any) => (
            <div key={a.id} className={`alert ${a.severity}`}><span className="bar" />
              <div><div className="spread"><span className="t">{a.title}</span><span className="small faint">{etDate(a.ts)} {etTime(a.ts)} ET, {a.category}</span></div>
                <div className="b">{a.body}</div>{a.symbol && <a href={`#/chart/${a.symbol}`} className="small">Open chart</a>}</div></div>))}
      </Panel>
    </div>
  );
}

// ======================= Settings =======================
export function Settings() {
  const s = usePoll("/settings");
  const ai = usePoll("/ai/status");
  const [v, setV] = useState<any>(null);
  const [saved, setSaved] = useState<string | null>(null);
  useEffect(() => { if (s.data && !v) setV(s.data.values); }, [s.data, v]);
  if (!v) return <div className="page muted">Loading…</div>;
  const save = async (changes: any) => {
    try { const r = await api("/settings", { method: "PUT", json: changes }); setV(r.values); setSaved("Saved."); ai.reload(); }
    catch (e: any) { setSaved(e.message); }
    setTimeout(() => setSaved(null), 3000);
  };
  const n = (k: string, label: string, step = "any") => <label className="f">{label}<input type="number" step={step} value={v[k] ?? ""} placeholder="default"
    onChange={(e) => setV({ ...v, [k]: e.target.value === "" ? null : Number(e.target.value) })} onBlur={() => save({ [k]: v[k] })} /></label>;
  const b = (k: string, label: string) => <label className="check"><input type="checkbox" checked={!!v[k]} onChange={(e) => { setV({ ...v, [k]: e.target.checked }); save({ [k]: e.target.checked }); }} />{label}</label>;
  const setups = s.data?.setups || {};
  const startup = async (on: boolean) => { try { await api(`/desktop/startup?enabled=${on}`, { method: "POST" }); setV({ ...v, "desktop.start_on_login": on }); } catch (e: any) { setSaved(e.message); } };
  return (
    <div className="page">
      {saved && <div className="note">{saved}</div>}
      <div className="cols c-2">
        <Panel title="Risk limits" sub="applied immediately to practice trading">
          <div className="form">{n("risk.max_per_trade_pct", "Max risk per trade (%)")}{n("risk.max_daily_loss_pct", "Max daily loss (%)")}{n("risk.max_open_positions", "Max open positions", "1")}
            {n("risk.min_reward_risk", "Preferred reward:risk")}{n("risk.max_consecutive_losses", "Losses in a row before pausing", "1")}{n("risk.max_exposure_pct", "Max exposure (% of equity)")}</div>
          <div style={{ marginTop: 10 }}>{b("risk.require_stop", "Every entry needs a stop loss")}</div>
          <p className="small muted" style={{ marginTop: 8 }}>Empty fields use the defaults from your configuration (0.5% per trade, 2% per day, 3 positions, 2:1).</p>
        </Panel>
        <Panel title="Practice account settings (stocks)">
          <div className="form">{n("paper.slippage_bps", "Slippage (bps)")}{n("paper.slippage_min", "Min slippage ($/share)")}{n("paper.commission_per_share", "Commission ($/share)")}
            {n("paper.commission_per_order", "Commission ($/order)")}{n("paper.margin_multiplier", "Margin multiplier")}{n("paper.borrow_fee_annual_pct", "Short borrow fee (%/yr)")}</div>
          <div style={{ marginTop: 10 }}>{b("paper.allow_short", "Allow short selling")}</div>
        </Panel>
        <Panel title="Signals">
          <p className="small muted">Timeframes the engine evaluates (the first is the main one; the others act as higher-timeframe checks).</p>
          <div className="row">{TIMEFRAMES.map((t) => <label key={t} className="check"><input type="checkbox" checked={v["signals.timeframes"].includes(t)}
            onChange={(e) => { const cur = v["signals.timeframes"]; const nx = e.target.checked ? TIMEFRAMES.filter((x) => cur.includes(x) || x === t) : cur.filter((x: string) => x !== t); if (nx.length) { setV({ ...v, "signals.timeframes": nx }); save({ "signals.timeframes": nx }); } }} />{t}</label>)}</div>
          <h3>Setups to watch</h3>
          <div className="row">{Object.entries(setups).map(([k, lbl]: any) => { const on = !v["signals.enabled_setups"].length || v["signals.enabled_setups"].includes(k);
            return <label key={k} className="check"><input type="checkbox" checked={on} onChange={(e) => { const all = Object.keys(setups); const cur = v["signals.enabled_setups"].length ? v["signals.enabled_setups"] : all;
              const nx = e.target.checked ? [...cur, k] : cur.filter((x: string) => x !== k); const val = nx.length === all.length ? [] : nx; setV({ ...v, "signals.enabled_setups": val }); save({ "signals.enabled_setups": val }); }} />{lbl}</label>; })}</div>
        </Panel>
        <Panel title="Alerts">
          <div className="stack">{b("alerts.desktop", "Windows desktop notifications")}{b("alerts.sound", "Sound alerts")}
            <div className="form">
              <label className="f">Desktop notifications from<select value={v["alerts.min_severity_desktop"]} onChange={(e) => save({ "alerts.min_severity_desktop": e.target.value })}>{["low", "medium", "high"].map((x) => <option key={x}>{x}</option>)}</select></label>
              <label className="f">Sound from<select value={v["alerts.min_severity_sound"]} onChange={(e) => save({ "alerts.min_severity_sound": e.target.value })}>{["low", "medium", "high"].map((x) => <option key={x}>{x}</option>)}</select></label>
            </div>
            <div className="row">{["entry", "position", "market", "system"].map((c) => <label key={c} className="check"><input type="checkbox" checked={v["alerts.categories"][c] !== false}
              onChange={(e) => { const cat = { ...v["alerts.categories"], [c]: e.target.checked }; setV({ ...v, "alerts.categories": cat }); save({ "alerts.categories": cat }); }} />{c} alerts</label>)}</div></div>
        </Panel>
        <Panel title="AI mentor" sub={ai.data?.engine}>
          <div className="form">
            <label className="f">Provider<select value={v["ai.provider"]} onChange={(e) => save({ "ai.provider": e.target.value })}>
              <option value="auto">Automatic</option><option value="none">Built-in explanations only</option><option value="claude">Claude API (needs ANTHROPIC_API_KEY in .env)</option><option value="ollama">Ollama (local, free)</option></select></label>
            <label className="f">Model<input value={v["ai.model"]} placeholder="default" onChange={(e) => setV({ ...v, "ai.model": e.target.value })} onBlur={() => save({ "ai.model": v["ai.model"] })} /></label>
            <label className="f">Your level<select value={v["learning.level"]} onChange={(e) => save({ "learning.level": e.target.value })}><option value="beginner">Beginner: define everything</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></label>
          </div>
          <div style={{ marginTop: 10 }}>{b("ai.vision", "Let the AI look at chart images on material changes (sends a cropped screenshot to the AI provider)")}</div>
          <p className="small muted">The AI only explains numbers the app calculated. It never sets prices or places orders. Without a provider, built-in explanations still answer everything.</p>
        </Panel>
        <Panel title="Desktop and screen">
          <div className="stack">
            <label className="check"><input type="checkbox" checked={!!v["desktop.start_on_login"]} onChange={(e) => startup(e.target.checked)} />Start Study Terminal when I log in to Windows</label>
            {b("desktop.keep_awake_while_monitoring", "Keep the PC awake while monitoring")}
            <div className="form">{n("screen.capture_fps", "Screen checks per second")}{n("screen.ocr_interval_seconds", "Min seconds between screen reads")}</div>
            <label className="f">Platform on screen<select value={v["screen.platform"] || "auto"} onChange={(e) => { setV({ ...v, "screen.platform": e.target.value }); save({ "screen.platform": e.target.value }); }}>
              <option value="auto">Detect automatically</option><option value="tradingview">TradingView (stocks or futures)</option><option value="topstepx">TopstepX (futures)</option><option value="generic">Other</option></select></label>
            {b("screen.read_account_info", "Read account/position panels on screen (off by default; always marked unverified)")}
            <p className="small muted">If the computer sleeps, monitoring stops; the app reports the gap when it wakes instead of pretending it watched.</p>
            <MonitoringToggle />
          </div>
        </Panel>
        <ExtensionPanel />
        <AboutFiles />
      </div>
    </div>
  );
}

function ExtensionPanel() {
  const p = usePoll("/extension/pairing");
  const latest = usePoll("/extension/latest", 15000);
  const [show, setShow] = useState(false);
  const [copied, setCopied] = useState(false);
  const d = p.data;
  const toggle = async (on: boolean) => { await api("/settings", { method: "PUT", json: { "extension.enabled": on } }); p.reload(); };
  const rotate = async () => { await api("/extension/pairing/rotate", { method: "POST" }); p.reload(); };
  const copy = async () => { try { await navigator.clipboard.writeText(d.token); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { setShow(true); } };
  return (
    <Panel title="Chrome extension" sub="optional, off by default">
      {!d ? <span className="muted small">Loading…</span> : <div className="stack small">
        <p className="muted" style={{ margin: 0 }}>Sends only your active TradingView tab's title and address to this app, so the copilot can follow the
          chart without screen capture. No screenshots, no page contents. Install steps are in the extension folder's README.</p>
        <label className="check"><input type="checkbox" checked={d.enabled} onChange={(e) => toggle(e.target.checked)} />Accept data from the Chrome extension</label>
        {d.enabled && <div className="row">
          <span className="muted">Pairing token</span><code>{show ? d.token : "•".repeat(12)}</code>
          <button className="ghost small" onClick={() => setShow(!show)}>{show ? "Hide" : "Show"}</button>
          <button className="ghost small" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
          <button className="ghost small" onClick={rotate} title="Disconnects the extension until you paste the new token">New token</button>
        </div>}
        {latest.data && <div className="muted">Last from extension: {latest.data.symbol || "no symbol"} {latest.data.timeframe || ""}, {latest.data.action || ""} ({latest.data.received_at ? new Date(latest.data.received_at).toLocaleTimeString() : ""})</div>}
      </div>}
    </Panel>
  );
}

function AboutFiles() {
  const d = usePoll("/desktop/info");
  const [msg, setMsg] = useState<string | null>(null);
  const open = async (which: string) => { try { await api(`/desktop/open-folder?which=${which}`, { method: "POST" }); setMsg(null); } catch (e: any) { setMsg(e.message); } };
  const i = d.data;
  return (
    <Panel title="About and files" sub={i ? `version ${i.version}${i.installed_app ? ", installed app" : ", running from source"}` : ""}>
      {!i ? <span className="muted small">Loading…</span> : <div className="stack small">
        <div><span className="muted">Your data (journal, practice account, settings, backtests): </span><code>{i.data_dir}</code></div>
        <div><span className="muted">Log file: </span><code>{i.log_file}</code></div>
        <div><span className="muted">Optional settings file (API keys etc.): </span><code>{i.settings_files[0]}</code></div>
        <div className="row"><button onClick={() => open("logs")}>Open logs folder</button><button className="ghost" onClick={() => open("data")}>Open data folder</button>
          {msg && <span className="faint">{msg}</span>}</div>
        <p className="muted" style={{ margin: 0 }}><b>Updating:</b> {i.update_procedure}</p>
        <p className="faint" style={{ margin: 0 }}>To back up everything, copy the data folder while the app is closed.</p>
      </div>}
    </Panel>
  );
}

function MonitoringToggle() {
  const L = useLive();
  const on = L.status?.monitoring_enabled !== false;
  return <div className="row"><span>Market monitoring is {on ? "on" : "paused"}.</span>
    <button onClick={() => api(on ? "/monitoring/pause" : "/monitoring/resume", { method: "POST" })}>{on ? "Pause monitoring" : "Resume monitoring"}</button></div>;
}

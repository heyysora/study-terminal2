import { useEffect, useRef, useState } from "react";
import { Panel } from "./components";
import { api, ensureLive, onLiveMessage, usePoll } from "./lib";
import { confidenceWord, say, sourceClass, useUiMode } from "./plain";
import { ActionWord, Term, WhyBlock } from "./simple";

const ROOTS = ["auto", "NQ", "MNQ", "ES", "MES"];
const TFS = ["auto", "1Min", "2Min", "3Min", "5Min", "15Min", "30Min", "1Hour", "4Hour", "1Day"];
const COLOR_KEYS: [string, string][] = [["up_color", "Up candle"], ["down_color", "Down candle"], ["vwap_color", "VWAP line"],
  ["ema:9", "EMA 9"], ["ema:20", "EMA 20"], ["ema:50", "EMA 50"], ["ema:200", "EMA 200"]];
const LABEL_CLASS: Record<string, string> = { "LIVE VISUAL OBSERVATION": "pos", STALE: "neg", UNREADABLE: "neg", DISCONNECTED: "neg", PAUSED: "", STOPPED: "" };
// how a value was obtained: plain words in Simple mode, the exact class name in Advanced
const CLASS_TEXT = new Proxy({} as Record<string, string>, { get: (_t, k) => sourceClass(String(k)) });
const METHODS: [string, string][] = [["auto", "Automatic (Graphics Capture → PrintWindow → screen)"], ["wgc", "Windows Graphics Capture"],
  ["printwindow", "PrintWindow"], ["screen", "Screen region (window must be visible)"]];

const blank = (): any => ({ name: "TopstepX chart", window_title_contains: "TopstepX", window_process: null, window_hwnd: null, window_size: null,
  region: [0, 0, 0, 0], root: "auto", timeframe: "auto", axis_mode: "auto", axis_points: [], axis_x: null, plot_bottom: 0.8,
  up_color: null, down_color: null, vwap_color: null, ema_colors: {}, color_tolerance: 40, capture_seconds: 2, stale_seconds: 20,
  frozen_seconds: 90, active: true, capture_method: "auto", axis_size: null });

const hex = (c: number[] | null | undefined) => (c ? "#" + c.map((v) => v.toString(16).padStart(2, "0")).join("") : "");

export function VisualMonitor({ tab: startTab }: { tab?: string } = {}) {
  const st = usePoll("/visual/status", 5000);
  const [tab, setTab] = useState<"monitor" | "setup">(startTab === "setup" ? "setup" : "monitor");
  useEffect(() => { if (startTab === "setup") setTab("setup"); }, [startTab]);
  useUiMode();
  const [editing, setEditing] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { ensureLive(); return onLiveMessage((m) => { if (m.type === "visual") st.reload(); }); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const act = async (a: string) => { setErr(null); try { await api(`/visual/${a}`, { method: "POST" }); st.reload(); } catch (e: any) { setErr(e.message); } };
  const s = st.data;
  const charts = Object.values<any>(s?.charts || {});
  return (
    <div className="page">
      <div className="spread">
        <div className="row">
          <button className={tab === "monitor" ? "primary" : "ghost"} onClick={() => setTab("monitor")}>Monitor</button>
          <button className={tab === "setup" ? "primary" : "ghost"} onClick={() => setTab("setup")}>Set up a chart</button>
        </div>
        <div className="row">
          <span className="small muted">Monitoring: <b>{s?.state || "…"}</b></span>
          {s?.state !== "running" && s?.state !== "paused" && <button className="primary" onClick={() => act("start")}>Start monitoring</button>}
          {s?.state === "running" && <button onClick={() => act("pause")}>Pause</button>}
          {s?.state === "paused" && <button className="primary" onClick={() => act("resume")}>Resume</button>}
          {(s?.state === "running" || s?.state === "paused") && <button onClick={() => act("stop")}>Stop</button>}
        </div>
      </div>
      <div className="note small">{s?.note} Monitoring keeps running when you leave this page or close the window to the tray.</div>
      {err && <div className="note bad">{err}</div>}
      {tab === "setup" ? <Setup initial={editing} onSaved={() => { st.reload(); }} /> : (
        !charts.length ? <div className="empty">No chart set up yet. Open TopstepX in Microsoft Edge, then use "Set up a chart".</div> :
          charts.map((c: any) => <ChartCard key={c.profile.id} c={c} running={s?.state === "running"}
            onRecalibrate={() => { setEditing(c.profile); setTab("setup"); }} />)
      )}
    </div>
  );
}

function ChartCard({ c, running, onRecalibrate }: { c: any; running: boolean; onRecalibrate: () => void }) {
  const r = c.reading;
  const rec = c.recommendation;
  const [tick, setTick] = useState(0);
  useEffect(() => { if (!running) return; const t = setInterval(() => setTick((n) => n + 1), 2000); return () => clearInterval(t); }, [running]);
  const h = c.capture_health || {};
  const a = rec?.analysis;
  return (
    <div className="cols c-main" style={{ marginBottom: 16 }}>
      <div className="stack">
        <Panel title={c.profile.name} sub={c.window?.title ? `${c.window.title}${c.window.process ? ` (${c.window.process})` : ""}` : "window not found"}
          right={<span className={`badge ${LABEL_CLASS[c.label] ?? ""}`}>{c.label}</span>}>
          <div className="small">{c.reason}</div>
          {running && c.last_capture_at && <img src={`/api/visual/region-preview/${c.profile.id}?t=${tick}`} alt="Live capture of the chart region (memory only)"
            style={{ width: "100%", marginTop: 8, border: "1px solid var(--rule)", opacity: c.label === "LIVE VISUAL OBSERVATION" ? 1 : 0.45 }} />}
          <table className="small" style={{ marginTop: 6 }}><tbody>
            <tr><td className="muted">Source</td><td>SCREEN CAPTURE via {h.method || "—"}{h.requested && h.requested !== "auto" ? " (pinned)" : ""}</td></tr>
            <tr><td className="muted">Capture time</td><td>{c.last_capture_at ? c.last_capture_at.replace("T", " ").slice(0, 19) + " UTC" : "—"}{h.frame_age_seconds != null ? ` · frame ${h.frame_age_seconds}s old` : ""}</td></tr>
            <tr><td className="muted">Last successful observation</td><td>{c.last_good_at ? c.last_good_at.replace("T", " ").slice(0, 19) + " UTC" : "none yet"}</td></tr>
            <tr><td className="muted">Capture health</td><td>{(h.tried || []).map((t: any) => `${t.method}: ${t.error || "ok"}`).join(" · ") || "—"}</td></tr>
            <tr><td className="muted">Counts</td><td>{c.captures} captures, {c.readings} readings (OCR runs only when the chart changed)</td></tr>
          </tbody></table>
          <div className="row" style={{ marginTop: 6 }}><button onClick={onRecalibrate}>Recalibrate / edit region</button></div>
        </Panel>
        {rec && <RecCard rec={rec} label={c.label} />}
        {a && !a.error && <Panel title="Market read" sub={`bias: ${a.bias?.label} · ${a.class}`}>
          <table className="small"><tbody>
            <tr><td className="muted">Bias</td><td>{a.bias?.label} ({a.bias?.reasons?.join(", ") || "no clear signs"})</td></tr>
            <tr><td className="muted">Structure</td><td>{a.structure} {a.swings?.pattern?.length ? `· ${a.swings.pattern.join(" ")}` : ""}</td></tr>
            <tr><td className="muted">Last BOS/CHoCH</td><td>{a.last_structure_break ? `${a.last_structure_break.kind} ${a.last_structure_break.direction} through ${a.last_structure_break.level}` : "none visible"}</td></tr>
            <tr><td className="muted">VWAP</td><td>{a.vwap?.value != null ? `${a.vwap.value} (price ${a.vwap.position})` : "UNAVAILABLE"}</td></tr>
            <tr><td className="muted">EMAs</td><td>{a.ema_alignment?.alignment || a.ema_alignment?.note}</td></tr>
            {Object.entries<any>(a.levels || {}).map(([k, v]) => <tr key={k}><td className="muted">{k.replace(/_/g, " ")}</td><td>{v.value ?? `UNAVAILABLE (${v.note})`}</td></tr>)}
            <tr><td className="muted">Volume</td><td>{a.volume?.last_vs_20_bar_average != null ? `last bar ${a.volume.last_vs_20_bar_average}× the 20-bar average (relative)` : "UNAVAILABLE"}</td></tr>
            <tr><td className="muted">Support / resistance</td><td>{a.support_resistance ? `${a.support_resistance.support.join(", ") || "—"} / ${a.support_resistance.resistance.join(", ") || "—"}` : "—"}</td></tr>
            <tr><td className="muted">Fair value gaps</td><td>{(a.fair_value_gaps || []).map((g: any) => `${g.kind} ${g.low}–${g.high}`).join("; ") || "none unfilled"}</td></tr>
            <tr><td className="muted">Sweeps</td><td>{(a.liquidity_sweeps || []).map((s: any) => s.text).join("; ") || "none"}</td></tr>
          </tbody></table>
          <div className="small faint">Derived from visually estimated candles; not exact market data.</div>
        </Panel>}
        <Panel title="History" flush>
          <div style={{ maxHeight: 220, overflow: "auto" }}>{(c.history || []).map((h: any, i: number) =>
            <div key={i} className="small" style={{ padding: "2px 12px" }}><span className="faint">{h.at.slice(11, 19)}{h.repeats ? ` (×${h.repeats + 1}, since ${h.since.slice(11, 19)})` : ""}</span> {h.status} · {h.action} · {h.price ?? "—"} · {h.reason}</div>)}</div>
        </Panel>
      </div>
      <div className="stack">
        <Panel title="What the chart shows" sub={r ? `confidence ${r.confidence}` : ""}>
          {!r ? <div className="muted small">No reading yet.</div> : <>
            <table className="small"><tbody>
              {(["instrument", "timeframe", "price", "bid", "ask", "volume"] as const).map((k) => <tr key={k}><td className="muted">{k === "price" ? "observed price" : k}</td>
                <td>{r[k].value ?? "—"}</td><td className="faint">{CLASS_TEXT[r[k].class]} · {r[k].confidence}</td></tr>)}
              <tr><td className="muted">axis</td><td>{r.axis ? `${r.axis.labels} labels, ${r.axis.price_per_pixel} pts/px` : r.calibration_valid === false ? "calibration invalid" : "—"}</td><td className="faint">{r.axis ? `${CLASS_TEXT[r.axis.class]} (${r.axis.mode}${r.axis.verified === false ? ", unverified" : ""})` : ""}</td></tr>
              <tr><td className="muted">candles</td><td>{r.candles.length}</td><td className="faint">{CLASS_TEXT.VISUALLY_ESTIMATED} · {r.candle_confidence}</td></tr>
              {Object.entries<any>(r.indicators || {}).map(([k, v]) => <tr key={k}><td className="muted">{k}</td><td>{v.last ?? "—"}</td>
                <td className="faint">{CLASS_TEXT[v.class]}{v.confidence ? ` · ${v.confidence}` : ""}{v.class === "UNAVAILABLE" ? ` (${v.source})` : ""}</td></tr>)}
              {(r.levels || []).slice(0, 6).map((l: any, i: number) => <tr key={i}><td className="muted">line {l.label || ""}</td><td>{l.price}</td><td className="faint">{CLASS_TEXT[l.class]}</td></tr>)}
            </tbody></table>
            {r.problems?.length > 0 && <div className="note warn small">{r.problems.join(" ")}</div>}
            <div className="small faint">Captured {r.captured_at}. Live visual observation of your screen, not a verified exchange feed. A changed screenshot is not a market tick.</div>
          </>}
        </Panel>
      </div>
    </div>
  );
}

function RecCard({ rec, label }: { rec: any; label: string }) {
  const simple = useUiMode() === "simple";
  const cls = rec.action === "LONG" ? "pos" : rec.action === "SHORT" || rec.action === "EXIT" ? "neg" : "";
  const plan = rec.entry != null && <table className="small"><tbody>
    <tr><td className="muted">Price I read</td><td>{rec.observed_price}</td><td className="muted"><Term k="entry" /></td><td>{rec.entry_zone?.join(" – ")}</td></tr>
    <tr><td className="muted"><Term k="stop" /></td><td>{rec.stop}</td><td className="muted"><Term k="target" /></td><td>{(rec.target_levels || [rec.target_1, rec.target_2]).join(" / ")}</td></tr>
    <tr><td className="muted"><Term k="reward_risk" /></td><td>{simple ? `$${rec.reward_risk} for every $1 risked` : `${rec.reward_risk}R`}</td><td className="muted">{simple ? "Kind of idea" : "Setup"}</td><td>{say(`${rec.setup} ${rec.direction}`)}</td></tr>
    <tr><td className="muted"><Term k="evidence_tier" /></td><td>{rec.evidence_tier}</td><td className="muted">{simple ? "Contracts (within your limits)" : "Size (risk engine)"}</td><td>{rec.suggested_contracts ?? "—"}</td></tr>
  </tbody></table>;
  return (
    <Panel title={simple ? "Practice a trade or wait?" : "Recommendation"} sub={`${rec.contract || ""} ${rec.timeframe || ""}`}
      right={simple ? <ActionWord a={rec.action} /> : <span className={`badge ${cls}`}>{rec.action}{rec.potential ? ` · potential ${rec.potential}` : ""}</span>}>
      <WhyBlock reason={rec.reason} />
      {simple && rec.potential && plan ? <details><summary className="small">The idea I noticed (for watching, not trading)</summary>{plan}</details> : plan}
      {rec.invalidation && <div className="small">{simple ? "The plan is cancelled if" : "What invalidates it"}: {say(rec.invalidation)}</div>}
      {!simple && rec.values && <div className="small faint">{rec.values}</div>}
      {rec.evidence?.length > 0 && <details><summary className="small">{simple ? "Checks it passed" : "Supporting evidence"}</summary>{rec.evidence.map((e: string, i: number) => <div key={i} className="small faint">{e}</div>)}</details>}
      {(rec.risk_check?.problems || []).map((p: string) => <WhyBlock key={p} reason={p} />)}
      {rec.notes?.length > 0 && <div className="small faint">{say(rec.notes.join(" "))}</div>}
      <div className="small faint">{simple
        ? <><Term k="data_confidence" />: {confidenceWord(rec.data_confidence)} (this is not the chance of winning). Read from your screen at {rec.captured_at || "—"}. Study Terminal never clicks or places orders.</>
        : <>Data confidence {rec.data_confidence} · captured {rec.captured_at || "—"} · {label} (SCREEN CAPTURE). Study Terminal never clicks or places orders.</>}</div>
    </Panel>
  );
}

// ---------------- setup ----------------

function Setup({ onSaved, initial }: { onSaved: () => void; initial?: any }) {
  const wins = usePoll("/visual/windows");
  const profs = usePoll("/visual/profiles");
  const [p, setP] = useState<any>(initial ? { ...blank(), ...initial } : blank());
  const [usedMethod, setUsedMethod] = useState<string | null>(null);
  const [hwnd, setHwnd] = useState<number | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [img, setImg] = useState<{ url: string; scale: number; w: number; h: number } | null>(null);
  const [mode, setMode] = useState<string>("region");                  // region | axis | color:<key>
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const [pending, setPending] = useState<{ y: number } | null>(null);
  const [price, setPrice] = useState("");
  const [test, setTest] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const canvas = useRef<HTMLCanvasElement>(document.createElement("canvas"));
  const set = (k: string, v: any) => setP((x: any) => ({ ...x, [k]: v }));

  const loadPreview = async () => {
    setMsg(null);
    try {
      if (file) {
        const url = URL.createObjectURL(file);
        const im = new Image();
        im.onload = () => setImg({ url, scale: Math.min(1, 1400 / im.width), w: im.width, h: im.height });
        im.src = url;
        return;
      }
      if (hwnd == null) return;
      const r = await fetch(`/api/visual/preview?hwnd=${hwnd}&method=${p.capture_method || "auto"}`, { headers: { "X-Study-Terminal": "1" } });
      if (!r.ok) { setMsg((await r.json()).detail); return; }
      setUsedMethod(r.headers.get("X-Capture-Method"));
      const b = await r.blob();
      setImg({ url: URL.createObjectURL(b), scale: Number(r.headers.get("X-Scale")), w: Number(r.headers.get("X-Window-Width")), h: Number(r.headers.get("X-Window-Height")) });
    } catch (e: any) { setMsg(e.message); }
  };
  useEffect(() => { if (hwnd != null || file) loadPreview(); }, [hwnd, file]); // eslint-disable-line react-hooks/exhaustive-deps

  // pointer position in WINDOW pixels
  const pos = (e: React.MouseEvent) => {
    const el = imgRef.current!, rc = el.getBoundingClientRect();
    const sx = img!.w / rc.width, sy = img!.h / rc.height;
    return { x: Math.round((e.clientX - rc.left) * sx), y: Math.round((e.clientY - rc.top) * sy), px: e.clientX - rc.left, py: e.clientY - rc.top, rc };
  };
  const down = (e: React.MouseEvent) => {
    if (!img) return;
    const q = pos(e);
    if (mode === "region") { setDrag({ x: q.x, y: q.y }); set("region", [q.x, q.y, 0, 0]); }
    else if (mode === "axis") { setPending({ y: q.y - p.region[1] }); setPrice(""); }
    else if (mode.startsWith("color:")) {
      const im = imgRef.current!, c = canvas.current;
      c.width = im.naturalWidth; c.height = im.naturalHeight;
      const ctx = c.getContext("2d")!;
      ctx.drawImage(im, 0, 0);
      const d = ctx.getImageData(Math.round(q.px * im.naturalWidth / q.rc.width), Math.round(q.py * im.naturalHeight / q.rc.height), 1, 1).data;
      const key = mode.slice(6), rgb = [d[0], d[1], d[2]];
      if (key.startsWith("ema:")) set("ema_colors", { ...p.ema_colors, [key.slice(4)]: rgb }); else set(key, rgb);
      setMode("region");
    }
  };
  const move = (e: React.MouseEvent) => {
    if (!drag || mode !== "region") return;
    const q = pos(e);
    set("region", [Math.min(drag.x, q.x), Math.min(drag.y, q.y), Math.abs(q.x - drag.x), Math.abs(q.y - drag.y)]);
  };
  const up = () => setDrag(null);
  const addAxisPoint = () => {
    const v = Number(price);
    if (!pending || !Number.isFinite(v)) return;
    const pts = [...(p.axis_points || []), [pending.y, v]].slice(-2);
    setP((x: any) => ({ ...x, axis_points: pts, axis_mode: pts.length === 2 ? "manual" : x.axis_mode,
      axis_size: pts.length === 2 ? [x.region[2] || img?.w, x.region[3] || img?.h] : x.axis_size }));
    setPending(null);
    if (pts.length === 2) setMode("region");
  };
  const body = () => ({ ...p, window_hwnd: hwnd, window_size: img ? [img.w, img.h] : p.window_size,
    window_process: p.window_process ?? ((wins.data?.windows || []).find((w: any) => w.id === hwnd)?.process || null),
    capture_method: p.capture_method === "auto" && usedMethod ? usedMethod : p.capture_method,
    region: p.region.map((v: number) => Math.max(0, Math.round(v))) });
  const runTest = async () => {
    setMsg(null); setTest(null);
    try {
      if (file) {
        const fd = new FormData(); fd.append("file", file); fd.append("profile", JSON.stringify(body()));
        const r = await fetch("/api/visual/upload-read", { method: "POST", body: fd, headers: { "X-Study-Terminal": "1" } });
        const d = await r.json(); if (!r.ok) throw new Error(d.detail); setTest(d);
      } else setTest(await api("/visual/test-read", { method: "POST", json: { profile: body(), hwnd } }));
    } catch (e: any) { setMsg(e.message); }
  };
  const save = async () => {
    setMsg(null);
    try { const d = await api("/visual/profiles", { method: "POST", json: body() }); setP(d); profs.reload(); onSaved(); setMsg(`Saved "${d.name}".`); }
    catch (e: any) { setMsg(e.message); }
  };
  const del = async (id: string) => { await api(`/visual/profiles/${id}`, { method: "DELETE" }); profs.reload(); onSaved(); };

  const pct = (v: number, tot: number) => `${(100 * v) / tot}%`;
  const [rx, ry, rw, rh] = p.region;
  useEffect(() => { if (initial?.window_hwnd && hwnd == null) setHwnd(initial.window_hwnd); }, [initial]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="cols c-main">
      <div className="stack">
        <Panel title="1 · Pick the Microsoft Edge window with TopstepX" sub={wins.data?.window_capture_supported ? (wins.data?.wgc_available ? "Windows Graphics Capture available" : "Graphics Capture not installed: PrintWindow/screen only") : "window capture needs Windows"}>
          <div className="row">
            <select value={hwnd ?? ""} onChange={(e) => { setFile(null); setHwnd(e.target.value ? Number(e.target.value) : null); }} aria-label="Window">
              <option value="">Choose a window…</option>
              {(wins.data?.windows || []).map((w: any) => <option key={w.id} value={w.id}>{w.looks_like_topstepx ? "★ " : ""}{w.is_edge ? "[Edge] " : ""}{w.title}{w.process ? ` (${w.process})` : ""}</option>)}
            </select>
            <select value={p.capture_method || "auto"} onChange={(e) => set("capture_method", e.target.value)} aria-label="Capture method">
              {METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
            <button onClick={() => wins.reload()}>Refresh</button>
            <button onClick={loadPreview} disabled={hwnd == null && !file}>Refresh preview</button>
            <label className="small">or a saved screenshot <input type="file" accept="image/*" onChange={(e) => { setHwnd(null); setFile(e.target.files?.[0] || null); }} /></label>
          </div>
          {wins.data?.note && <div className="small faint">{wins.data.note}</div>}
          {usedMethod && <div className="small faint">Preview captured with: {usedMethod}. Saving pins this method so the region always lines up.</div>}
        </Panel>
        <Panel title="2 · Select the chart region" sub={mode === "region" ? "drag on the preview" : mode === "axis" ? "click a price-axis label's line" : "click the color"}>
          {!img ? <div className="muted small">Pick a window to see a preview.</div> :
            <div style={{ position: "relative", userSelect: "none", cursor: "crosshair" }} onMouseDown={down} onMouseMove={move} onMouseUp={up} onMouseLeave={up}>
              <img ref={imgRef} src={img.url} alt="Window preview (not stored)" style={{ width: "100%", display: "block" }} draggable={false} />
              {rw > 0 && rh > 0 && <div style={{ position: "absolute", left: pct(rx, img.w), top: pct(ry, img.h), width: pct(rw, img.w), height: pct(rh, img.h),
                border: "2px solid #e8b04a", boxShadow: "0 0 0 9999px rgba(0,0,0,.35)", pointerEvents: "none" }}>
                <div style={{ position: "absolute", left: 0, right: 0, top: `${p.plot_bottom * 100}%`, borderTop: "1px dashed #5aa9e6" }} title="volume pane starts here" />
                {(p.axis_points || []).map((a: any, i: number) => <div key={i} style={{ position: "absolute", left: 0, right: 0, top: pct(a[0], rh), borderTop: "1px solid #c678dd" }}>
                  <span className="small" style={{ background: "#c678dd", color: "#000", padding: "0 3px" }}>{a[1]}</span></div>)}
                {(test?.candles || []).map((c: any, i: number) => <div key={i} style={{ position: "absolute", left: pct(c.x0, rw), width: Math.max(1, (c.x1 - c.x0) / img.w * 100) + "%", bottom: 0, height: 6,
                  background: c.direction === "up" ? "#3fb68b" : "#e5534b" }} />)}
              </div>}
            </div>}
          {img && <div className="row small" style={{ marginTop: 6 }}>
            {["x", "y", "width", "height"].map((l, i) => <label key={l} className="f">{l}<input type="number" min={0} value={p.region[i]}
              onChange={(e) => set("region", p.region.map((v: number, j: number) => (j === i ? Number(e.target.value) : v)))} style={{ width: 80 }} /></label>)}
            <label className="f">Volume pane starts at<input type="range" min={0.5} max={1} step={0.01} value={p.plot_bottom} onChange={(e) => set("plot_bottom", Number(e.target.value))} /></label>
          </div>}
          <div className="small faint">The preview is a fresh capture of that window, shown here only. Nothing is saved except the region coordinates.</div>
        </Panel>
      </div>
      <div className="stack">
        <Panel title="3 · Instrument, timeframe, axis, colors">
          <div className="row small">
            <label className="f">Name<input value={p.name} onChange={(e) => set("name", e.target.value)} /></label>
            <label className="f">Window title contains<input value={p.window_title_contains} onChange={(e) => set("window_title_contains", e.target.value)} /></label>
          </div>
          <div className="row small">
            <label className="f">Instrument<select value={p.root} onChange={(e) => set("root", e.target.value)}>{ROOTS.map((r) => <option key={r}>{r}</option>)}</select></label>
            <label className="f">Timeframe<select value={p.timeframe} onChange={(e) => set("timeframe", e.target.value)}>{TFS.map((r) => <option key={r}>{r}</option>)}</select></label>
          </div>
          <div className="small">Price axis: <b>{p.axis_mode}</b>{p.axis_mode === "manual" ? ` (${p.axis_points.map((a: any) => a[1]).join(", ")})` : " (read from the axis labels; works with auto-scaling charts)"}</div>
          <div className="row small">
            <button onClick={() => { setMode("axis"); setP((x: any) => ({ ...x, axis_points: [] })); }}>Calibrate manually (2 clicks)</button>
            <button onClick={() => setP((x: any) => ({ ...x, axis_mode: "auto", axis_points: [] }))}>Use automatic axis</button>
          </div>
          {pending && <div className="row small"><span>Price at that line:</span><input autoFocus value={price} onChange={(e) => setPrice(e.target.value)} style={{ width: 110 }} />
            <button onClick={addAxisPoint}>Add point</button></div>}
          <div className="toggle-grid small" style={{ marginTop: 6 }}>{COLOR_KEYS.map(([k, l]) => {
            const v = k.startsWith("ema:") ? p.ema_colors?.[k.slice(4)] : p[k];
            return <div key={k} className="row" style={{ gap: 6 }}>
              <span style={{ width: 14, height: 14, display: "inline-block", border: "1px solid #555", background: hex(v) || "transparent" }} />
              <button className="small" onClick={() => setMode(`color:${k}`)}>{l}</button>
              {v && <button className="small ghost" onClick={() => { if (k.startsWith("ema:")) { const e = { ...p.ema_colors }; delete e[k.slice(4)]; set("ema_colors", e); } else set(k, null); }}>×</button>}
            </div>; })}</div>
          <div className="small faint">Candle colors are detected automatically if you leave them empty. Lines are only named VWAP/EMA because you pick their color.</div>
          <div className="row small">
            <label className="f">Capture every (s)<input type="number" min={0.5} max={60} step={0.5} value={p.capture_seconds} onChange={(e) => set("capture_seconds", Number(e.target.value))} style={{ width: 70 }} /></label>
            <label className="f">Stale after (s)<input type="number" value={p.stale_seconds} onChange={(e) => set("stale_seconds", Number(e.target.value))} style={{ width: 70 }} /></label>
            <label className="f">Frozen after (s)<input type="number" value={p.frozen_seconds} onChange={(e) => set("frozen_seconds", Number(e.target.value))} style={{ width: 70 }} /></label>
          </div>
          <div className="row"><button onClick={runTest} disabled={!img}>Test read</button><button className="primary" onClick={save} disabled={!img && !p.id}>Save profile</button></div>
          {msg && <div className="note small">{msg}</div>}
        </Panel>
        {test && <Panel title="Test read" sub={`confidence ${test.confidence}`}>
          <table className="small"><tbody>
            {(["instrument", "timeframe", "price", "bid", "ask"] as const).map((k) => <tr key={k}><td className="muted">{k}</td><td>{test[k].value ?? "—"}</td><td className="faint">{CLASS_TEXT[test[k].class]} · {test[k].confidence}</td></tr>)}
            <tr><td className="muted">candles</td><td>{test.candles.length}</td><td className="faint">confidence {test.candle_confidence} (marks under the region)</td></tr>
            <tr><td className="muted">axis</td><td>{test.axis ? `${test.axis.mode}, ${test.axis.labels} labels` : "not found"}</td><td /></tr>
          </tbody></table>
          {test.problems?.length > 0 && <div className="note warn small">{test.problems.join(" ")}</div>}
        </Panel>}
        <Panel title="Saved chart profiles" flush>
          <table className="small"><tbody>{(profs.data?.profiles || []).map((x: any) => <tr key={x.id}>
            <td>{x.name}</td><td className="faint">{x.root} · {x.timeframe} · "{x.window_title_contains}"</td>
            <td><button className="small" onClick={() => setP(x)}>Edit</button> <button className="small danger" onClick={() => del(x.id)}>Delete</button></td></tr>)}
            {!(profs.data?.profiles || []).length && <tr><td className="muted">None yet.</td></tr>}</tbody></table>
        </Panel>
      </div>
    </div>
  );
}

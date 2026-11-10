// Plain-language layer for the interface. The words come from backend/app/plain.py (exported to plain.json);
// a backend test fails if the two drift. Display only: nothing here changes a decision, a limit or stored data.
import { useEffect, useSyncExternalStore } from "react";
import words from "./plain.json";

type W = { actions: Record<string, { word: string; tone: string }>; statuses: Record<string, { word: string; level: string; explain: string }>;
  source_classes: Record<string, string>; terms: Record<string, { technical: string; simple: string; explain: string }>;
  simplify: string[][]; reasons: string[][] };
const P = words as unknown as W;
const js = (rep: string) => rep.replace(/\\(\d)/g, "$$$1");            // Python \1 -> JavaScript $1
const SIMPLIFY = P.simplify.map(([p, r, f]) => [new RegExp(p, f === "i" ? "gi" : "g"), js(r)] as [RegExp, string]);
const REASONS = P.reasons.map(([p, kind, head, todo]) => ({ rx: new RegExp(p, "i"), kind, head: js(head), todo }));

// ---------------- Simple / Advanced ----------------
export type UiMode = "simple" | "advanced";
let mode: UiMode = (() => { try { return localStorage.getItem("st.ui.mode") === "advanced" ? "advanced" : "simple"; } catch { return "simple"; } })();
const subs = new Set<() => void>();
export const uiMode = () => mode;
export function setUiMode(m: UiMode, persist = true) {
  if (m === mode) return;
  mode = m;
  try { localStorage.setItem("st.ui.mode", m); } catch { /* private mode: the server copy still applies */ }
  subs.forEach((f) => f());
  if (persist) fetch("/api/settings", { method: "PUT", headers: { "X-Study-Terminal": "1", "Content-Type": "application/json" }, body: JSON.stringify({ "ui.mode": m }) }).catch(() => {});
}
export function useUiMode(): UiMode { return useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, () => mode); }
export const isSimple = () => mode === "simple";

// ---------------- words ----------------
export const simplify = (t?: string | null) => SIMPLIFY.reduce((s, [rx, rep]) => s.replace(rx, rep), t || "");
/** Server sentences (alerts, errors): plain in Simple mode, untouched in Advanced. */
export const say = (t?: string | null) => (mode === "simple" ? simplify(t) : t || "");
export const actionWord = (a?: string | null) => P.actions[(a || "").toUpperCase().trim()] || { word: "WAIT", tone: "wait" };
export const statusWord = (s?: string | null) => P.statuses[(s || "").toLowerCase()] || { word: "No prices", level: "bad", explain: "No prices are arriving." };
export const sourceClass = (c?: string | null) => (mode === "simple" ? P.source_classes[c || ""] || c || "" : c || "");
export const term = (k: string) => P.terms[k];
/** Label for a term: everyday words in Simple mode, the trading term in Advanced. */
export const label = (k: string) => { const t = P.terms[k]; return t ? (mode === "simple" ? t.simple : t.technical) : k; };
export const confidenceWord = (x?: number | null) => (x == null ? "Unknown" : x >= 0.8 ? "High" : x >= 0.6 ? "Medium" : "Low");

export type Why = { headline: string; do: string; kind: string; original: string; matched: boolean };
export function explain(reason?: string | null): Why {
  const raw = (reason || "").trim();
  for (const r of REASONS) {
    const m = raw.match(r.rx);
    if (m) return { headline: r.head.replace(/\$(\d)/g, (_, i) => m[Number(i)] ?? ""), do: r.todo, kind: r.kind, original: raw, matched: true };
  }
  return { headline: simplify(raw) || "No reason was recorded.", do: "", kind: "other", original: raw, matched: false };
}

// ---------------- Home data (shared by the top bar and the Home screen) ----------------
type HomeState = { data: any | null; error: string | null; failures: number; loadedAt: number };
let home: HomeState = { data: null, error: null, failures: 0, loadedAt: 0 };
const homeSubs = new Set<() => void>();
let timer: number | null = null;
export async function reloadHome() {
  try {
    const res = await fetch("/api/home", { headers: { "X-Study-Terminal": "1" } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    home = { data, error: null, failures: 0, loadedAt: Date.now() };
    if (data.ui_mode && data.ui_mode !== mode && !localStorageHasMode()) setUiMode(data.ui_mode, false);
  } catch (e: any) {
    home = { ...home, error: e.message || "unreachable", failures: home.failures + 1 };
  }
  homeSubs.forEach((f) => f());
}
function localStorageHasMode() { try { return localStorage.getItem("st.ui.mode") != null; } catch { return false; } }
export function useHome(): HomeState {
  useEffect(() => {
    if (timer == null) { reloadHome(); timer = window.setInterval(reloadHome, 6000); }
  }, []);
  return useSyncExternalStore((f) => { homeSubs.add(f); return () => homeSubs.delete(f); }, () => home);
}

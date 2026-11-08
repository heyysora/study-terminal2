// API client, live WebSocket store, and formatting helpers.
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

export async function api<T = any>(path: string, opts: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = opts;
  const res = await fetch(`/api${path}`, {
    ...rest,
    // X-Study-Terminal marks the request as coming from this app (the backend refuses
    // state changes without it, so other web pages can't drive the local API).
    headers: { "X-Study-Terminal": "1", ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...((rest.headers as any) || {}) },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const d = data?.detail;
    const msg = typeof d === "string" ? d : d?.message || JSON.stringify(d ?? data);
    throw new ApiError(msg, res.status, data);
  }
  return data as T;
}
export class ApiError extends Error {
  constructor(msg: string, public status: number, public data: any) { super(msg); }
}

/** Fetch on mount + every `everyMs`. */
export function usePoll<T = any>(path: string | null, everyMs = 0, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const tick = useRef(0);
  const reload = async () => {
    if (!path) return;
    const my = ++tick.current;
    setLoading(true);
    try {
      const d = await api<T>(path);
      if (my === tick.current) { setData(d); setError(null); }
    } catch (e: any) {
      if (my === tick.current) setError(e.message);
    } finally {
      if (my === tick.current) setLoading(false);
    }
  };
  useEffect(() => {
    reload();
    if (!everyMs) return;
    const t = setInterval(reload, everyMs);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, everyMs, ...deps]);
  return { data, error, loading, reload, setData };
}

// ---------------- live store (WebSocket) ----------------
type Live = {
  connected: boolean;
  status: any;               // monitor status
  symbols: Record<string, any>; // symbol -> {last, label}
  paper: any;
  screen: any;
  signals: any;
  alerts: any[];
  toasts: any[];
  version: number;
};
const live: Live = { connected: false, status: null, symbols: {}, paper: null, screen: null, signals: null, alerts: [], toasts: [], version: 0 };
const subs = new Set<() => void>();
let snapshot = { ...live };
function emit() { live.version++; snapshot = { ...live }; subs.forEach((f) => f()); }

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/market`);
  ws.onopen = () => { live.connected = true; emit(); };
  ws.onclose = () => { live.connected = false; emit(); setTimeout(connect, 2000); };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    const d = m.data;
    switch (m.type) {
      case "hello":
        live.status = d.status; live.paper = d.paper_account;
        for (const s of d.symbols) live.symbols[s.symbol] = { last: s.last, label: s.label };
        break;
      case "tick":
        live.symbols[d.symbol] = { last: d, label: d.label };
        break;
      case "bar": {
        const cur = live.symbols[d.symbol] || {};
        if (!cur.last || cur.last.source !== "yahoo-stream") live.symbols[d.symbol] = { last: { ...d, price: d.close }, label: d.label };
        else live.symbols[d.symbol] = { ...cur, label: d.label };
        break;
      }
      case "freshness":
        for (const [s, lab] of Object.entries(d)) live.symbols[s] = { ...(live.symbols[s] || {}), label: lab };
        break;
      case "connection": live.status = d; break;
      case "paper_account": case "paper_reset": live.paper = d; break;
      case "screen": live.screen = d; break;
      case "signals": live.signals = d; break;
      case "alert":
        live.alerts = [d, ...live.alerts].slice(0, 200);
        if (d.severity === "high" || d.severity === "medium") {
          live.toasts = [d, ...live.toasts].slice(0, 3);
          setTimeout(() => { live.toasts = live.toasts.filter((t) => t !== d); emit(); }, 12000);
        }
        break;
      default: return;
    }
    emit();
  };
}
let started = false;
export function useLive(): Live {
  if (!started) { started = true; connect(); }
  return useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, () => snapshot);
}
export function dismissToast(t: any) { live.toasts = live.toasts.filter((x) => x !== t); emit(); }

// ---------------- formatting ----------------
export const money = (v: any, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? "—" :
  (v < 0 ? "-$" : "$") + Math.abs(Number(v)).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
export const num = (v: any, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
export const pct = (v: any, d = 2) => (v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(d)}%`);
export const sign = (v: any) => (v > 0 ? "up" : v < 0 ? "down" : "");
const etFmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false });
const etDay = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" });
export const etTime = (iso: string | number) => etFmt.format(typeof iso === "number" ? new Date(iso * 1000) : new Date(iso));
export const etDate = (iso: string | number) => etDay.format(typeof iso === "number" ? new Date(iso * 1000) : new Date(iso));

export const STATUS_LEVEL: Record<string, number> = {
  realtime: 5, near_realtime: 4, polling: 3, delayed: 2, historical: 1, cached: 1, stale: 1, unavailable: 0,
};
export const STATUS_TEXT: Record<string, string> = {
  realtime: "Real-time", near_realtime: "Near real-time", polling: "Polling", delayed: "Delayed",
  historical: "Historical", cached: "Cached copy", stale: "Stale", unavailable: "Unavailable",
};
const etSecFmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
export const etTimeSec = (iso: string) => etSecFmt.format(new Date(iso));
/** "4s", "3m", "2h" */
export const ago = (seconds?: number | null) => seconds == null ? "—" : seconds < 90 ? `${Math.round(seconds)}s` : seconds < 5400 ? `${Math.round(seconds / 60)}m` : `${Math.round(seconds / 3600)}h`;
export const SOURCE_TEXT: Record<string, string> = {
  "yahoo-stream": "Yahoo stream", "yahoo-poll": "Yahoo 1-min poll", "yahoo-history": "Yahoo history",
};
export function actionClass(a?: string) {
  if (!a) return "act";
  if (a === "STRONG BUY") return "act strong";
  if (a === "BUY") return "act buy";
  if (a === "SHORT") return "act short";
  if (a === "WAIT FOR CONFIRMATION" || a.startsWith("POTENTIAL")) return "act wait";
  if (a === "EXIT POSITION" || a === "SELL" || a === "COVER SHORT") return "act exit";
  return "act";
}
export const TIMEFRAMES = ["1Min", "2Min", "5Min", "15Min", "30Min", "1Hour", "4Hour", "1Day"];
export const tfShort = (t: string) => ({ "1Min": "1m", "2Min": "2m", "5Min": "5m", "15Min": "15m", "30Min": "30m", "1Hour": "1h", "4Hour": "4h", "1Day": "1D" } as Record<string, string>)[t] || t;

export function useHashRoute(): [string[], (to: string) => void] {
  const [h, setH] = useState(location.hash.slice(2) || "dashboard");
  useEffect(() => {
    const f = () => setH(location.hash.slice(2) || "dashboard");
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return [h.split("/"), (to: string) => { location.hash = `#/${to}`; }];
}

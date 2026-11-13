// Light / dark theme. "auto" follows the Windows setting. Applied before the first render so there's no flash.
import { useEffect, useSyncExternalStore } from "react";

export type ThemePref = "auto" | "light" | "dark";
const mq = typeof window !== "undefined" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
let pref: ThemePref = (() => { try { const v = localStorage.getItem("st.theme"); return v === "light" || v === "dark" ? v : "auto"; } catch { return "auto"; } })();
const subs = new Set<() => void>();
export const resolvedTheme = () => (pref === "auto" ? (mq?.matches ? "dark" : "light") : pref);
function apply() { document.documentElement.dataset.theme = resolvedTheme(); subs.forEach((f) => f()); }
apply();
mq?.addEventListener?.("change", () => { if (pref === "auto") apply(); });
export function setTheme(p: ThemePref) { pref = p; try { localStorage.setItem("st.theme", p); } catch { /* fine */ } apply(); }
export const themePref = () => pref;
export function useTheme(): { pref: ThemePref; theme: string } {
  const theme = useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, resolvedTheme);
  useEffect(() => {}, [theme]);
  return { pref, theme };
}

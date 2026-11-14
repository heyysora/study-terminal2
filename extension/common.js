// Shared by the background worker, popup and options page.
// Finding the app: Study Terminal normally listens on 8765, but moves to the next free port (up to 8804) if another program
// has 8765. The extension tries the port it used last; if nothing answers there (or something that isn't Study Terminal
// answers), it asks 127.0.0.1:8765-8804 "are you Study Terminal?" (/api/extension/hello, no secrets) and remembers the answer.
export const FIRST_PORT = 8765;
export const PORTS = Array.from({ length: 40 }, (_, i) => FIRST_PORT + i);

export async function config() {
  return chrome.storage.local.get({ port: FIRST_PORT, token: "", enabled: true, found_at: null });
}

function version() {
  try { return chrome.runtime.getManifest().version; } catch { return ""; }
}

async function isStudyTerminal(port, fetchImpl) {
  try {
    const r = await fetchImpl(`http://127.0.0.1:${port}/api/extension/hello`, { signal: AbortSignal.timeout(900) });
    if (!r.ok) return false;
    const j = await r.json();
    return j && j.app === "Study Terminal";
  } catch {
    return false;
  }
}

// Returns the port Study Terminal answers on, or null. Tries `preferred` first, then the rest ten at a time.
export async function findApp(preferred = FIRST_PORT, fetchImpl = fetch) {
  if (await isStudyTerminal(preferred, fetchImpl)) return preferred;
  const rest = PORTS.filter((p) => p !== preferred);
  for (let i = 0; i < rest.length; i += 10) {
    const batch = rest.slice(i, i + 10);
    const hits = await Promise.all(batch.map(async (p) => ((await isStudyTerminal(p, fetchImpl)) ? p : null)));
    const found = hits.find((p) => p !== null);
    if (found) return found;
  }
  return null;
}

// Looks for the app and saves the port it found. Returns the port or null.
export async function rediscover(fetchImpl = fetch) {
  const { port } = await config();
  const found = await findApp(port, fetchImpl);
  if (found) await chrome.storage.local.set({ port: found, found_at: new Date().toISOString() });
  return found;
}

async function request(port, token, path, method, body, fetchImpl) {
  return fetchImpl(`http://127.0.0.1:${port}/api/extension${path}`, {
    method, signal: AbortSignal.timeout(6000),        // a program on that port that never answers counts as "not there"
    headers: { "X-Study-Token": token, "X-Study-Extension": version(), ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
}

export async function call(path, { method = "GET", body } = {}, fetchImpl = fetch) {
  const { port, token } = await config();
  if (!token) throw new Error("Not paired. Open the extension's options and paste the pairing code from Study Terminal > Settings > Chrome extension.");
  let res = null;
  try { res = await request(port, token, path, method, body, fetchImpl); } catch { res = null; }
  // Nothing there, no answer in time, or a different program on that port: look for Study Terminal and try once more.
  if (res === null || res.status === 404 || res.status === 421) {
    const found = await rediscover(fetchImpl);
    if (!found) throw new Error("Can't find Study Terminal on this computer. Is it open?");
    try { res = await request(found, token, path, method, body, fetchImpl); } catch {
      throw new Error("Found Study Terminal but couldn't reach it. Try again in a few seconds.");
    }
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}
export const isChartTab = (url) => /^https:\/\/(www\.)?tradingview\.com\/(chart|symbols)(\/|$|\?)/.test(url || "");

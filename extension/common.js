// Shared by the background worker, popup and options page.
export async function config() {
  const c = await chrome.storage.local.get({ port: 8765, token: "", enabled: true });
  return c;
}
export async function call(path, { method = "GET", body } = {}) {
  const { port, token } = await config();
  if (!token) throw new Error("Not paired. Open the extension's options and paste the token from Study Terminal > Settings.");
  let res;
  try {
    res = await fetch(`http://127.0.0.1:${port}/api/extension${path}`, {
      method, headers: { "X-Study-Token": token, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new Error("Study Terminal isn't running (or uses a different port).");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}
export const isChartTab = (url) => /^https:\/\/(www\.)?tradingview\.com\/(chart|symbols)(\/|$|\?)/.test(url || "");

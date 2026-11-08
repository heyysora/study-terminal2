// Watches only TradingView chart tabs (the only sites this extension has access to) and sends the active
// tab's title + address to the local Study Terminal app. No screenshots, no page contents, no cookies.
import { call, config, isChartTab } from "./common.js";

let timer = null;
let lastSent = "";
let lastAt = 0;
const REFRESH_MS = 30000;   // live prices change the title constantly: re-send at most every 30 s for the same chart

function badge(text, color) {
  chrome.action.setBadgeText({ text });
  if (color) chrome.action.setBadgeBackgroundColor({ color });
}

async function send(tab) {
  if (!tab || !isChartTab(tab.url) || !tab.title) return;
  const { enabled } = await config();
  if (!enabled) return badge("off", "#5b6778");
  const hasPrice = /\d+\.\d+/.test(tab.title);
  const key = `${tab.url}|${tab.title.split(" ")[0]}|${hasPrice}`;   // new chart, or the price just appeared: send now
  if (key === lastSent && Date.now() - lastAt < REFRESH_MS) return;
  lastSent = key;
  lastAt = Date.now();
  try {
    const r = await call("/context", { method: "POST", body: { title: tab.title, url: tab.url } });
    const a = r.action || "";
    const short = a.startsWith("STRONG") ? a.replace("STRONG ", "S") : a === "NO TRADE" ? "—" : a.startsWith("POTENTIAL") ? "watch" : a.slice(0, 4);
    badge(short, r.tradeable ? "#3fb68b" : "#5b6778");
    await chrome.storage.session.set({ last: r, error: null });
  } catch (e) {
    lastSent = "";
    badge("!", "#e5534b");
    await chrome.storage.session.set({ error: e.message });
  }
}

function schedule(tab) {
  clearTimeout(timer);
  timer = setTimeout(() => send(tab), 1200);   // let TradingView finish updating the title
}

chrome.tabs.onUpdated.addListener((id, info, tab) => { if (tab.active && (info.title || info.url)) schedule(tab); });
chrome.tabs.onActivated.addListener(async ({ tabId }) => { try { schedule(await chrome.tabs.get(tabId)); } catch {} });
chrome.windows.onFocusChanged.addListener(async (w) => {
  if (w === chrome.windows.WINDOW_ID_NONE) return;
  const [tab] = await chrome.tabs.query({ active: true, windowId: w });
  schedule(tab);
});

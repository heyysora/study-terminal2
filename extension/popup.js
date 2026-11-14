import { call, config } from "./common.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function render() {
  $("open").onclick = async (e) => { e.preventDefault(); const { port } = await config(); chrome.tabs.create({ url: `http://127.0.0.1:${port}/#/copilot` }); };
  try {
    const s = await call("/status");
    $("conn").textContent = "connected";
    if (!s.symbol) { $("body").innerHTML = `<p class="muted">${esc(s.note || "Open a TradingView chart.")}</p>`; return; }
    $("body").innerHTML = `
      <div class="row"><span class="sym">${esc(s.symbol)}</span><span class="muted">${esc(s.timeframe || "")}</span>
        <span class="act ${s.tradeable ? "go" : ""}">${esc(s.action || "—")}</span></div>
      ${s.setup ? `<p>${esc(s.setup)} <span class="muted">(${esc(s.state)}${s.tradeable ? "" : ", watch only"})</span></p>` : ""}
      <p class="muted">Tab ${s.tab_price != null ? s.tab_price.toFixed(2) : "—"} · market data ${s.market_price != null ? s.market_price.toFixed(2) : "—"} (${esc(s.data_status || "no live quote")})</p>
      ${s.discrepancy ? `<p class="warn">${esc(s.discrepancy)}</p>` : ""}
      ${s.timeframe_note ? `<p class="muted small">${esc(s.timeframe_note)}</p>` : ""}
      ${(s.reasons || []).map((r) => `<p class="small">${esc(r)}</p>`).join("")}
      <p class="muted small">Analysis comes from the desktop app's market data, not from TradingView. Orders are paper only, placed in the app.</p>`;
  } catch (e) {
    $("conn").textContent = "";
    $("body").innerHTML = `<p class="warn">${esc(e.message)}</p>`;
  }
}
render();

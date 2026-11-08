import { call, config } from "./common.js";

const $ = (id) => document.getElementById(id);
(async () => {
  const c = await config();
  $("token").value = c.token; $("port").value = c.port; $("enabled").checked = c.enabled;
})();
$("save").onclick = async () => {
  await chrome.storage.local.set({ token: $("token").value.trim(), port: Number($("port").value) || 8765, enabled: $("enabled").checked });
  try { await call("/status"); $("msg").textContent = "Connected to Study Terminal."; }
  catch (e) { $("msg").textContent = e.message; }
};

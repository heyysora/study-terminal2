import { FIRST_PORT, call, config, rediscover } from "./common.js";

const $ = (id) => document.getElementById(id);
async function showWhere() {
  const c = await config();
  $("where").textContent = c.found_at ? `Last found on port ${c.port}.` : "";
}
(async () => {
  const c = await config();
  $("token").value = c.token; $("port").value = c.port; $("enabled").checked = c.enabled;
  showWhere();
})();
$("save").onclick = async () => {
  await chrome.storage.local.set({ token: $("token").value.trim(), port: Number($("port").value) || FIRST_PORT, enabled: $("enabled").checked });
  try { await call("/status"); $("msg").textContent = "Connected to Study Terminal."; }
  catch (e) { $("msg").textContent = e.message; }
  const c = await config(); $("port").value = c.port; showWhere();
};
$("find").onclick = async () => {
  $("msg").textContent = "Looking…";
  const p = await rediscover();
  $("msg").textContent = p ? `Found Study Terminal on port ${p}.` : "Can't find Study Terminal. Is it open?";
  if (p) $("port").value = p;
  showWhere();
};

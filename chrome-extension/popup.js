const $ = (id) => document.getElementById(id);
const statusEl = $("status");

async function load() {
  const c = await chrome.storage.local.get(["agentUrl", "token", "enabled", "igEnabled"]);
  $("agentUrl").value = c.agentUrl || "";
  $("token").value = c.token || "";
  $("enabled").checked = !!c.enabled;
  $("igEnabled").checked = !!c.igEnabled;
  const on = [];
  if (c.enabled) on.push("WhatsApp");
  if (c.igEnabled) on.push("Instagram");
  statusEl.textContent = on.length ? `Ativada ✅ — ${on.join(" + ")}.` : "Desativada.";
}

$("save").addEventListener("click", async () => {
  const agentUrl = $("agentUrl").value.trim();
  const token = $("token").value.trim();
  const enabled = $("enabled").checked;
  const igEnabled = $("igEnabled").checked;
  await chrome.storage.local.set({ agentUrl, token, enabled, igEnabled });
  const on = [];
  if (enabled) on.push("WhatsApp");
  if (igEnabled) on.push("Instagram");
  statusEl.textContent = on.length
    ? `Salvo. Ativada ✅ — ${on.join(" + ")}. Abra a aba do canal.`
    : "Salvo. Desativada.";
});

$("test").addEventListener("click", async () => {
  const agentUrl = $("agentUrl").value.trim();
  await chrome.storage.local.set({ agentUrl });
  statusEl.textContent = "Testando...";
  const resp = await chrome.runtime.sendMessage({ type: "PING_AGENT" });
  if (resp && resp.ok) {
    statusEl.textContent = "Conexão OK ✅";
  } else {
    statusEl.textContent = `Falha ❌: ${resp && resp.error ? resp.error : "sem resposta"}`;
  }
});

load();

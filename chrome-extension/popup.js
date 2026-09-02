const $ = (id) => document.getElementById(id);
const statusEl = $("status");

async function load() {
  const c = await chrome.storage.local.get(["agentUrl", "token", "enabled"]);
  $("agentUrl").value = c.agentUrl || "";
  $("token").value = c.token || "";
  $("enabled").checked = !!c.enabled;
  statusEl.textContent = c.enabled ? "Ativada ✅ — respondendo automaticamente." : "Desativada.";
}

$("save").addEventListener("click", async () => {
  const agentUrl = $("agentUrl").value.trim();
  const token = $("token").value.trim();
  const enabled = $("enabled").checked;
  await chrome.storage.local.set({
    agentUrl, token, enabled,
    minDelayMs: 1500, maxDelayMs: 4000,
  });
  statusEl.textContent = enabled
    ? "Salvo. Ativada ✅ — abra o WhatsApp Web."
    : "Salvo. Desativada.";
});

$("test").addEventListener("click", async () => {
  const agentUrl = $("agentUrl").value.trim();
  await chrome.storage.local.set({ agentUrl });
  statusEl.textContent = "Testando...";
  const resp = await chrome.runtime.sendMessage({ type: "PING_AGENT" });
  if (resp && resp.ok) {
    const inst = resp.body && resp.body.instance ? ` (instância: ${resp.body.instance})` : "";
    statusEl.textContent = `Conexão OK ✅${inst}`;
  } else {
    statusEl.textContent = `Falha ❌: ${resp && resp.error ? resp.error : "sem resposta"}`;
  }
});

load();

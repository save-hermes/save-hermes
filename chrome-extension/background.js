/*
 * background.js — service worker (Manifest V3)
 *
 * Recebe pedidos ASK_AGENT do content script, chama o endpoint /reply do agente
 * Vanessa e devolve a resposta. Centralizar aqui evita problemas de CORS/mixed
 * content na página do WhatsApp.
 */

// Defaults aplicados na instalação/atualização. Editáveis depois pelo popup.
// (Pré-configurado para não depender de digitar no popup.)
const DEFAULTS = {
  agentUrl: "https://wins-showers-provinces-cartoons.trycloudflare.com",
  token: "vQ-C2b71wFJKzL3rpzAfDGiBkK44TzlNX05W41_rMqk",
  enabled: false, // começa DESATIVADA por segurança; ligar no popup quando quiser
  igEnabled: false, // Instagram (Direct via navegador) — ligar no popup quando quiser
  minDelayMs: 1500,
  maxDelayMs: 4000,
  dailyLimit: 40, // teto diário de respostas no Instagram (anti-ban)
};

chrome.runtime.onInstalled.addListener(async () => {
  const cur = await chrome.storage.local.get(Object.keys(DEFAULTS));
  const patch = {};
  for (const [k, v] of Object.entries(DEFAULTS)) {
    if (cur[k] === undefined) patch[k] = v;
  }
  if (Object.keys(patch).length) await chrome.storage.local.set(patch);
});

async function askAgent(payload) {
  const { agentUrl, token } = await chrome.storage.local.get(["agentUrl", "token"]);
  if (!agentUrl || !token) {
    return { ok: false, error: "extensão não configurada (agentUrl/token)" };
  }
  const url = `${agentUrl.replace(/\/+$/, "")}/reply?token=${encodeURIComponent(token)}`;
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      return { ok: false, error: `HTTP ${r.status}` };
    }
    return await r.json();
  } catch (e) {
    return { ok: false, error: String(e && e.message) };
  }
}

async function askIg(payload) {
  const { agentUrl, token } = await chrome.storage.local.get(["agentUrl", "token"]);
  if (!agentUrl || !token) {
    return { ok: false, error: "extensão não configurada (agentUrl/token)" };
  }
  const url = `${agentUrl.replace(/\/+$/, "")}/ig/reply?token=${encodeURIComponent(token)}`;
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) return { ok: false, error: `HTTP ${r.status}` };
    return await r.json();
  } catch (e) {
    return { ok: false, error: String(e && e.message) };
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "ASK_AGENT") {
    askAgent(msg.payload).then(sendResponse);
    return true; // resposta assíncrona
  }
  if (msg && msg.type === "ASK_IG") {
    askIg(msg.payload).then(sendResponse);
    return true; // resposta assíncrona
  }
  if (msg && msg.type === "PING_AGENT") {
    (async () => {
      const { agentUrl } = await chrome.storage.local.get(["agentUrl"]);
      try {
        const r = await fetch(`${(agentUrl || "").replace(/\/+$/, "")}/`);
        sendResponse({ ok: r.ok, status: r.status, body: await r.json().catch(() => ({})) });
      } catch (e) {
        sendResponse({ ok: false, error: String(e && e.message) });
      }
    })();
    return true;
  }
});

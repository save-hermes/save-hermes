/*
 * content_instagram.js — roda dentro de https://www.instagram.com
 *
 * MODO REATIVO: a cada ciclo, a Vanessa
 *   1) na lista do Direct, acha conversas que precisam de resposta (última msg é
 *      do lead, não nossa),
 *   2) abre a conversa, lê a última mensagem recebida + o @username,
 *   3) pede a resposta ao agente (/ig/reply, kind="dm"),
 *   4) digita e envia como humano logado (sem Graph API → sem App Review).
 *
 * Seletores validados no layout do Instagram (set/2026) via CDP:
 *   - conversas na lista: div[role="button"] cujo texto contém "·" (tempo)
 *   - mensagens: div[dir="auto"] (balão à ESQUERDA = recebida; à DIREITA = nossa)
 *   - @username: link /usuario/ no header da conversa aberta
 *   - campo de digitar: div[role="textbox"][contenteditable="true"]
 * Falha SEGURA: na dúvida, não envia.
 */

let RUNNING = false;
let SENT_TODAY = 0;
let DAY = new Date().getDate();
let CONFIG = { agentUrl: "", token: "", igEnabled: false, minDelayMs: 3000, maxDelayMs: 9000, dailyLimit: 40 };
const processed = new Set();

function log(...a) { console.log("%c[Vanessa IG]", "color:#E4405F;font-weight:bold", ...a); }
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
function rand(min, max) { return Math.floor(Math.random() * (max - min + 1)) + min; }

async function loadConfig() {
  const c = await chrome.storage.local.get(
    ["agentUrl", "token", "igEnabled", "minDelayMs", "maxDelayMs", "dailyLimit"]);
  CONFIG = { ...CONFIG, ...c };
  return CONFIG;
}

function resetDailyIfNeeded() {
  const d = new Date().getDate();
  if (d !== DAY) { DAY = d; SENT_TODAY = 0; }
}

/* ---- Leitura do DOM ---------------------------------------------------- */

// Lista de conversas: div[role="button"] cujo texto tem "·" (marcador de tempo).
function listConversations() {
  return [...document.querySelectorAll('div[role="button"]')].filter((b) => {
    const t = b.innerText || "";
    return t.includes("·") && t.trim().length > 6 && t.length < 240;
  });
}

// Uma conversa "precisa de resposta" se a última linha de prévia NÃO é nossa.
// Prévia começando com "Você:" = nós respondemos por último → ignora.
function needsReply(convEl) {
  const t = convEl.innerText || "";
  if (/(^|\n)\s*Você:/i.test(t)) return false;      // nós fomos os últimos
  if (/enviou um (vídeo|anexo|áudio|story)/i.test(t)) return false; // mídia, não texto
  return true;
}

// Nome/prévia da conversa (para dedup e log).
function convSummary(convEl) {
  const lines = (convEl.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean);
  const name = lines[0] || "";
  const preview = lines.slice(1).find((l) => l && l !== "·" && !/^\d/.test(l)) || "";
  return { name, preview };
}

// @username do contato na conversa ABERTA (link de perfil no header).
function readOpenUsername() {
  // o header tem um link /usuario/ com o nome; pega o primeiro link de perfil
  // que não seja da própria conta nem de navegação.
  const skip = ["/reels/", "/explore/", "/direct/", "/saveeducacao.oficial/"];
  const links = [...document.querySelectorAll('a[href^="/"]')];
  for (const a of links) {
    const h = a.getAttribute("href") || "";
    if (h.split("/").length <= 3 && h.length > 1 && !skip.includes(h)) {
      // precisa ter texto (nome) — evita ícones
      if ((a.innerText || "").trim()) return h.replace(/\//g, "").trim();
    }
  }
  return "";
}

// Última mensagem RECEBIDA (balão à esquerda) da conversa aberta.
function readLastIncoming() {
  const msgs = [...document.querySelectorAll('div[dir="auto"]')].filter((e) => {
    const t = (e.innerText || "").trim();
    return t && t.length > 1 && !/^\d{1,2}:\d{2}$/.test(t) && !/indisponível/i.test(t);
  });
  const W = window.innerWidth;
  let lastIncoming = null;
  for (const e of msgs) {
    // sobe até o balão (ancestral com largura < 70% da janela)
    let box = e, found = null;
    for (let i = 0; i < 10 && box; i++) {
      const r = box.getBoundingClientRect();
      if (r.width > 10 && r.width < W * 0.7) found = r;
      if (r.width >= W * 0.7) break;
      box = box.parentElement;
    }
    if (!found) continue;
    const center = (found.left + found.right) / 2;
    const isOurs = center > W * 0.55; // nossas ficam à direita
    if (!isOurs) lastIncoming = (e.innerText || "").trim();
    else lastIncoming = lastIncoming; // mantém; se a última for nossa, tratamos abaixo
  }
  // se a ÚLTIMA mensagem da conversa for nossa, não há o que responder
  const lastMsgEl = msgs[msgs.length - 1];
  if (lastMsgEl) {
    let box = lastMsgEl, found = null;
    for (let i = 0; i < 10 && box; i++) {
      const r = box.getBoundingClientRect();
      if (r.width > 10 && r.width < W * 0.7) found = r;
      if (r.width >= W * 0.7) break;
      box = box.parentElement;
    }
    if (found && (found.left + found.right) / 2 > W * 0.55) return null; // última é nossa
  }
  return lastIncoming;
}

/* ---- Ações no DOM ------------------------------------------------------ */

function setEditable(el, value) {
  el.focus();
  try { document.execCommand("selectAll", false, null); } catch (e) {}
  try { document.execCommand("insertText", false, value); return true; } catch (e) {}
  return false;
}

async function typeAndSend(text) {
  const input = document.querySelector('div[role="textbox"][contenteditable="true"]')
    || document.querySelector("textarea");
  if (!input) { log("campo de digitação não encontrado"); return false; }
  setEditable(input, text);
  await sleep(rand(700, 1800));
  const enter = new KeyboardEvent("keydown", {
    bubbles: true, cancelable: true, key: "Enter", code: "Enter", keyCode: 13, which: 13,
  });
  input.dispatchEvent(enter);
  return true;
}

/* ---- Loop principal ---------------------------------------------------- */

async function tick() {
  if (RUNNING) return;
  RUNNING = true;
  try {
    await loadConfig();
    resetDailyIfNeeded();
    if (!CONFIG.igEnabled || !CONFIG.agentUrl || !CONFIG.token) return;
    if (SENT_TODAY >= CONFIG.dailyLimit) { log("limite diário atingido:", SENT_TODAY); return; }
    if (!location.pathname.startsWith("/direct/")) return; // precisa estar no Direct

    // 1) acha uma conversa que precisa de resposta
    const convs = listConversations();
    let target = null, summary = null;
    for (const c of convs) {
      if (!needsReply(c)) continue;
      const s = convSummary(c);
      const key = `${s.name}:${s.preview}`;
      if (processed.has(key)) continue;
      target = c; summary = s; target._key = key;
      break;
    }
    if (!target) return;

    log("conversa p/ responder:", summary.name, "->", summary.preview);
    target.click();
    await sleep(rand(1500, 3000)); // carrega a conversa

    const username = readOpenUsername();
    const lastMsg = readLastIncoming();
    if (!username || !lastMsg) { log("sem username/msg — pulando", {username, lastMsg}); RUNNING = false; return; }

    const key = `${username}:${lastMsg.slice(0, 40)}`;
    if (processed.has(key)) return;
    processed.add(key);
    processed.add(target._key);

    log("DM de @" + username, "->", lastMsg);

    const resp = await chrome.runtime.sendMessage({
      type: "ASK_IG",
      payload: { kind: "dm", id: key, username, text: lastMsg },
    });
    if (!resp || !resp.ok) { log("agente não respondeu:", resp && resp.error); return; }
    if (resp.dup) { log("duplicado — ignora"); return; }
    const answer = (resp.reply || "").trim();
    if (!answer) { log("resposta vazia — não envia"); return; }

    await sleep(rand(CONFIG.minDelayMs, CONFIG.maxDelayMs)); // ritmo humano
    const sent = await typeAndSend(answer);
    if (sent) { SENT_TODAY++; log("respondido ✅ (", SENT_TODAY, "hoje) ->", answer); }
    else log("falha ao enviar ❌");
  } catch (e) {
    log("erro no tick:", e && e.message);
  } finally {
    RUNNING = false;
  }
}

// Ciclo com intervalo aleatório (anti-ban). 45s–90s entre passadas.
function loop() {
  tick().finally(() => setTimeout(loop, rand(45000, 90000)));
}
loop();
log("content script IG carregado (v2 seletores 2026). Configure e ative igEnabled.");

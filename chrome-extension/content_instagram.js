/*
 * content_instagram.js — roda dentro de https://www.instagram.com
 *
 * MODO REATIVO (mais seguro): a cada ciclo, a Vanessa
 *   1) abre o Direct (mensagens), lê threads com mensagem NÃO LIDA,
 *   2) pega a última mensagem recebida + o @username,
 *   3) pede a resposta ao agente (/ig/reply, kind="dm"),
 *   4) digita e envia como um humano logado (sem Graph API → sem App Review).
 *
 * Comentários: quando a UI de notificações estiver aberta, também dá pra tratar,
 * mas o caminho estável é o Direct. Tudo falha de forma SEGURA: na dúvida, não envia.
 *
 * Anti-ban: intervalos aleatórios, 1 por ciclo, limite diário, ritmo humano.
 * O Instagram muda de layout com frequência — os seletores em SEL usam âncoras
 * estáveis (aria-label, role, href) e devem ser revisados se algo parar.
 */

const SEL = {
  // Link do Direct na navbar
  directLink: 'a[href^="/direct/"]',
  // Lista de threads no inbox do Direct
  threadRow: 'div[role="listitem"], a[href^="/direct/t/"]',
  // Marcador de não lida (bolinha azul / aria-label)
  unreadHint: '[aria-label*="não lida" i], [aria-label*="unread" i], [aria-label*="Não lida" i]',
  // Balões de mensagem na conversa aberta
  msgRow: 'div[role="row"]',
  // Campo de digitação do Direct
  msgInput: 'div[role="textbox"][contenteditable="true"], textarea[placeholder*="Mensagem" i], textarea[placeholder*="Message" i]',
  // Cabeçalho da conversa (tem o @username / nome)
  convHeader: 'header a[href^="/"], header span[dir="auto"]',
};

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

// @username da conversa aberta (via URL ou header)
function readOpenUser() {
  const header = document.querySelector('header');
  if (header) {
    const link = header.querySelector('a[href^="/"]');
    if (link) {
      const h = link.getAttribute("href") || "";
      const u = h.replace(/\//g, "").trim();
      if (u) return u;
    }
    const span = header.querySelector('span[dir="auto"]');
    if (span && span.innerText) return span.innerText.trim();
  }
  return "";
}

// Última mensagem recebida (não enviada por nós) da conversa aberta.
function readLastIncoming() {
  const rows = document.querySelectorAll(SEL.msgRow);
  if (!rows.length) return null;
  // Heurística: mensagens NOSSAS costumam estar alinhadas à direita.
  // Pegamos a última linha que tenha texto e NÃO seja claramente nossa.
  for (let i = rows.length - 1; i >= 0; i--) {
    const row = rows[i];
    const txt = (row.innerText || "").trim();
    if (!txt) continue;
    // linha "nossa" tende a ter o botão de reação à esquerda / estilo próprio.
    // Sem classe estável; usamos posição: se o conteúdo está mais à direita, é nossa.
    const rect = row.getBoundingClientRect();
    const mid = window.innerWidth / 2;
    const isOurs = rect.left > mid; // aproximação; ajuste se necessário
    if (!isOurs) {
      return { text: txt.slice(0, 500), rowIndex: i, lastIsIncoming: i === rows.length - 1 || true };
    }
  }
  return null;
}

/* ---- Ações no DOM ------------------------------------------------------ */

function setNativeValue(el, value) {
  el.focus();
  try { document.execCommand("selectAll", false, null); } catch (e) {}
  try { document.execCommand("insertText", false, value); return; } catch (e) {}
  // fallback textarea
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value");
  if (setter && setter.set) { setter.set.call(el, value); el.dispatchEvent(new Event("input", { bubbles: true })); }
}

async function typeAndSend(text) {
  const input = document.querySelector(SEL.msgInput);
  if (!input) { log("campo de digitação não encontrado"); return false; }
  setNativeValue(input, text);
  await sleep(rand(600, 1600));
  const enter = new KeyboardEvent("keydown", {
    bubbles: true, cancelable: true, key: "Enter", code: "Enter", keyCode: 13, which: 13,
  });
  input.dispatchEvent(enter);
  return true;
}

// Abre a primeira thread não lida do inbox. Retorna true se abriu alguma.
function openFirstUnreadThread() {
  const rows = document.querySelectorAll(SEL.threadRow);
  for (const row of rows) {
    if (row.querySelector(SEL.unreadHint) || /não lida|unread/i.test(row.getAttribute("aria-label") || "")) {
      const clickable = row.closest("a") || row.querySelector("a") || row;
      clickable.click();
      return true;
    }
  }
  return false;
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

    // Precisa estar na área do Direct.
    if (!location.pathname.startsWith("/direct/")) {
      const dl = document.querySelector(SEL.directLink);
      if (dl) { dl.click(); await sleep(rand(1500, 3000)); }
      else return; // não achou o Direct; espera próximo ciclo
    }

    const opened = openFirstUnreadThread();
    if (!opened) return;
    await sleep(rand(1200, 2600)); // deixa a conversa carregar

    const username = readOpenUser();
    const last = readLastIncoming();
    if (!username || !last || !last.text) return;

    const key = `${username}:${last.text.slice(0, 40)}`;
    if (processed.has(key)) return;
    processed.add(key);

    log("nova DM de", username, "->", last.text);

    const resp = await chrome.runtime.sendMessage({
      type: "ASK_IG",
      payload: { kind: "dm", id: key, username, text: last.text },
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

// Ciclo com intervalo aleatório longo (anti-ban). 45s–90s entre passadas.
function loop() {
  tick().finally(() => setTimeout(loop, rand(45000, 90000)));
}
loop();
log("content script IG carregado. Configure no popup e ative (igEnabled).");

/*
 * content.js — roda dentro de https://web.whatsapp.com
 *
 * Responsabilidade:
 *   1) Detectar conversas 1:1 com mensagem NÃO LIDA.
 *   2) Abrir a conversa, ler a última mensagem recebida (inbound).
 *   3) Pedir ao background a resposta do agente (Vanessa).
 *   4) Digitar e enviar a resposta no campo de texto.
 *
 * IMPORTANTE: o WhatsApp Web ofusca os nomes de classe. Usamos seletores
 * ESTÁVEIS (aria-label, role, data-*, contenteditable). Se o WhatsApp mudar o
 * layout, ajuste os seletores em SEL abaixo. Tudo foi escrito para falhar de
 * forma segura: na dúvida, NÃO envia.
 */

const SEL = {
  // Painel lateral de conversas
  chatList: '#pane-side',
  // Cada linha de conversa
  chatRow: '#pane-side [role="listitem"]',
  // Badge de mensagens não lidas (aria-label costuma conter "não lida"/"unread")
  unreadBadge: 'span[aria-label*="não lida" i], span[aria-label*="unread" i]',
  // Campo de digitação da mensagem (contenteditable dentro do footer)
  messageInput: 'footer div[contenteditable="true"][role="textbox"]',
  // Balões de mensagem recebida vs enviada
  incomingMsg: '.message-in',
  outgoingMsg: '.message-out',
  // Texto copiável dentro de um balão
  msgText: 'span.selectable-text, span._ao3e, span[dir="ltr"], span[dir="auto"]',
  // Cabeçalho da conversa aberta (tem o nome/numero do contato)
  convHeader: 'header [role="button"] span[title], header span[title]',
  // Marcador de grupo: presença de "assunto do grupo" ou ícone de grupo
};

let RUNNING = false;
let CONFIG = { agentUrl: "", token: "", enabled: false, minDelayMs: 1500, maxDelayMs: 4000 };
const processed = new Set(); // ids de mensagens já respondidas nesta sessão

function log(...a) { console.log("%c[Vanessa]", "color:#25D366;font-weight:bold", ...a); }

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
function rand(min, max) { return Math.floor(Math.random() * (max - min + 1)) + min; }

async function loadConfig() {
  const c = await chrome.storage.local.get(["agentUrl", "token", "enabled", "minDelayMs", "maxDelayMs"]);
  CONFIG = { ...CONFIG, ...c };
  return CONFIG;
}

/* ---- Leitura do DOM ---------------------------------------------------- */

// É uma conversa de grupo? (heurística: header sem número e com participantes)
function isGroupOpen() {
  // Grupos mostram uma lista de participantes no subtítulo do header.
  const sub = document.querySelector('header span[title]')?.parentElement?.parentElement?.innerText || "";
  // Heurística leve: se aparecer vírgula separando muitos nomes, tratamos como grupo.
  return /,\s*.+,\s*.+/.test(sub);
}

// Extrai o "número" do contato da conversa aberta a partir do cabeçalho.
function readOpenContact() {
  const el = document.querySelector(SEL.convHeader);
  const title = el?.getAttribute("title") || el?.innerText || "";
  const digits = (title.match(/\d/g) || []).join("");
  return { title: title.trim(), number: digits };
}

// Lê a última mensagem recebida (inbound) da conversa aberta.
function readLastIncoming() {
  const incoming = document.querySelectorAll(SEL.incomingMsg);
  if (!incoming.length) return null;
  const last = incoming[incoming.length - 1];
  // id estável do balão (data-id contém o message id do WhatsApp)
  const bubble = last.closest("[data-id]");
  const dataId = bubble?.getAttribute("data-id") || "";
  // pega o texto
  let text = "";
  const spans = last.querySelectorAll(SEL.msgText);
  spans.forEach((s) => { if (s.innerText) text += s.innerText; });
  text = text.trim();
  // Só considera "novo" se a última bolha da conversa for inbound (não já respondida)
  const allBubbles = document.querySelectorAll(`${SEL.incomingMsg}, ${SEL.outgoingMsg}`);
  const lastBubbleIsIncoming = allBubbles.length && allBubbles[allBubbles.length - 1].classList.contains("message-in");
  return { dataId, text, lastBubbleIsIncoming };
}

/* ---- Ações no DOM ------------------------------------------------------ */

function setNativeValue(el, value) {
  // Insere texto num contenteditable de forma que o React do WhatsApp perceba.
  el.focus();
  document.execCommand("selectAll", false, null);
  document.execCommand("insertText", false, value);
}

async function typeAndSend(text) {
  const input = document.querySelector(SEL.messageInput);
  if (!input) { log("campo de digitação não encontrado"); return false; }
  // digita de forma "humana": insere o texto e dispara Enter
  setNativeValue(input, text);
  await sleep(rand(400, 1200));
  const enter = new KeyboardEvent("keydown", {
    bubbles: true, cancelable: true, key: "Enter", code: "Enter", keyCode: 13, which: 13,
  });
  input.dispatchEvent(enter);
  return true;
}

// Abre a primeira conversa não lida do painel. Retorna true se abriu alguma.
function openFirstUnread() {
  const rows = document.querySelectorAll(SEL.chatRow);
  for (const row of rows) {
    const badge = row.querySelector(SEL.unreadBadge);
    if (badge) {
      const clickable = row.querySelector('[role="button"]') || row;
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
    if (!CONFIG.enabled || !CONFIG.agentUrl || !CONFIG.token) { return; }

    const opened = openFirstUnread();
    if (!opened) return;
    await sleep(rand(700, 1400)); // deixa a conversa carregar

    if (isGroupOpen()) { log("conversa é grupo — ignorando"); return; }

    const contact = readOpenContact();
    const last = readLastIncoming();
    if (!last || !last.text || !last.lastBubbleIsIncoming) return;
    if (!contact.number) { log("sem número no header — pulando por segurança"); return; }

    const key = `${contact.number}:${last.dataId || last.text.slice(0, 40)}`;
    if (processed.has(key)) return;
    processed.add(key);

    log("nova msg de", contact.title, "->", last.text);

    // pede a resposta ao agente (via background para evitar CORS/mixed content)
    const resp = await chrome.runtime.sendMessage({
      type: "ASK_AGENT",
      payload: {
        msg_id: last.dataId,
        number: contact.number,
        name: contact.title,
        text: last.text,
      },
    });

    if (!resp || !resp.ok) { log("agente não respondeu:", resp && resp.error); return; }
    if (resp.skipped) { log("agente pulou:", resp.skipped); return; }
    const answer = (resp.reply || "").trim();
    if (!answer) { log("resposta vazia — não envia"); return; }

    // ritmo humano antes de responder
    await sleep(rand(CONFIG.minDelayMs, CONFIG.maxDelayMs));
    const sent = await typeAndSend(answer);
    log(sent ? "respondido ✅" : "falha ao enviar ❌", "->", answer);
  } catch (e) {
    log("erro no tick:", e && e.message);
  } finally {
    RUNNING = false;
  }
}

// Polling leve. O intervalo real é controlado pelo background via alarms,
// mas mantemos um fallback local também.
setInterval(tick, 8000);
log("content script carregado. Configure no popup e ative.");

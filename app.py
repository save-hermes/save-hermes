"""
Agente de Vendas IA no WhatsApp — servidor de webhook.

Fluxo:
  Evolution (messages.upsert) -> /webhook?token=... -> Claude (playbook)
    -> resposta enviada pela Evolution -> estado do lead gravado no SQLite.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import config
import evolution
import store
from brain import reply

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

app = FastAPI(title="WhatsApp Sales Agent")

# A extensão do Chrome (WhatsApp Web) faz POST /reply de outra origem.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://web.whatsapp.com"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    store.init()
    missing = config.validate()
    if missing:
        log.warning("VARIÁVEIS FALTANDO no ambiente: %s", ", ".join(missing))
    else:
        log.info("Config OK. Instância=%s", config.EVOLUTION_INSTANCE)


@app.get("/")
def health():
    """Health check — o Easypanel usa para saber se o app subiu."""
    import knowledge
    state = evolution.connection_state()
    return {
        "service": "whatsapp-sales-agent",
        "instance": config.EVOLUTION_INSTANCE,
        "config_missing": config.validate(),
        "whatsapp": state,
        "knowledge_base": knowledge.status(),
    }


def _extract(data: dict) -> dict | None:
    """Normaliza o payload de messages.upsert da Evolution v2."""
    msg = data.get("data") or {}
    key = msg.get("key") or {}

    # Ignora mensagens que NÓS enviamos
    if key.get("fromMe"):
        return None

    remote_jid = key.get("remoteJid", "")
    # Ignora grupos e status broadcast — só conversas 1:1
    if not remote_jid or remote_jid.endswith("@g.us") or "status@broadcast" in remote_jid:
        return None

    # Extrai o texto de qualquer um dos formatos possíveis
    m = msg.get("message") or {}
    text = (
        m.get("conversation")
        or (m.get("extendedTextMessage") or {}).get("text")
        or (m.get("imageMessage") or {}).get("caption")
        or (m.get("videoMessage") or {}).get("caption")
        or ""
    ).strip()

    if not text:
        return None  # mídia sem texto / áudio / etc. — fora do MVP

    number = remote_jid.split("@")[0]
    return {
        "msg_id": key.get("id", ""),
        "jid": remote_jid,
        "number": number,
        "name": msg.get("pushName", ""),
        "text": text,
    }


def _process(info: dict, deliver: bool) -> dict:
    """Lógica central compartilhada pelos dois canais (Evolution e extensão).

    `deliver=True`  -> o agente ENVIA a resposta pela Evolution (canal webhook).
    `deliver=False` -> o agente NÃO envia; devolve o texto em `reply` para quem
                       chamou (a extensão do Chrome digita e envia no WhatsApp Web).

    Retorna sempre um dict serializável com o resultado.
    """
    # Idempotência — mesmo evento pode chegar 2x
    if store.already_processed(info["msg_id"]):
        return {"ok": True, "dup": True}

    jid = info["jid"]
    is_admin = config.is_admin_number(info["number"])
    who = "ADMIN" if is_admin else (info["name"] or info["number"])
    log.info("%s (%s): %s", who, jid, info["text"][:80])

    # Registra lead + mensagem do usuário
    store.get_or_create_lead(jid, info["number"], info["name"])
    store.add_message(jid, "user", info["text"])

    # Limite diário de envio (warming) — admin nunca é limitado.
    if not is_admin and config.DAILY_SEND_LIMIT > 0:
        sent_today = store.assistant_msgs_today()
        if sent_today >= config.DAILY_SEND_LIMIT:
            log.warning(
                "Limite diário atingido (%s/%s). Pulando resposta a %s.",
                sent_today, config.DAILY_SEND_LIMIT, info["number"],
            )
            return {"ok": True, "skipped": "daily_limit_reached"}

    # Cérebro (canal de admin usa prompt de bastidor)
    history = store.get_history(jid, limit=20)
    answer = reply(history, lead_name=info["name"], is_admin=is_admin)

    # Handoff (não se aplica ao próprio admin)
    handoff = (config.HANDOFF_MARKER in answer) and not is_admin
    if config.HANDOFF_MARKER in answer:
        answer = answer.replace(config.HANDOFF_MARKER, "").strip()

    # Entrega e gravação
    if deliver:
        evolution.send_text(info["number"], answer)
    store.add_message(jid, "assistant", answer)

    # Status + aviso ao dono se lead quente
    if is_admin:
        store.set_status(jid, "admin")
    elif handoff:
        store.set_status(jid, "quente")
        evolution.notify_owner(
            f"🔥 LEAD QUENTE / assumir conversa\n"
            f"Nome: {info['name'] or '—'}\n"
            f"Número: {info['number']}\n"
            f"Última msg do lead: {info['text'][:150]}"
        )
    else:
        store.set_status(jid, "qualificado")

    return {"ok": True, "reply": answer, "handoff": handoff, "admin": is_admin}


@app.post("/webhook")
async def webhook(request: Request):
    """Canal Evolution API: recebe messages.upsert e ENVIA a resposta sozinho."""
    if request.query_params.get("token") != config.WEBHOOK_TOKEN:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.json()
    event = body.get("event", "")
    if event not in ("messages.upsert", "MESSAGES_UPSERT"):
        return {"ignored": event}

    info = _extract(body)
    if not info:
        return {"ignored": "no-actionable-message"}

    result = _process(info, deliver=True)
    # No canal Evolution não devolvemos o texto (o agente já enviou)
    result.pop("reply", None)
    return result


@app.post("/reply")
async def reply_endpoint(request: Request):
    """Canal Extensão Chrome (WhatsApp Web): recebe a mensagem já normalizada e
    DEVOLVE o texto da resposta para a extensão digitar e enviar na página.

    Payload esperado (JSON):
      { "msg_id": "...", "number": "5547...", "name": "Fulano", "text": "oi" }
    Só conversas 1:1 — a extensão não deve enviar grupos.
    """
    if request.query_params.get("token") != config.WEBHOOK_TOKEN:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.json()
    text = (body.get("text") or "").strip()
    number = "".join(ch for ch in (body.get("number") or "") if ch.isdigit())
    if not text or not number:
        return {"ignored": "no-actionable-message"}

    # Segurança: rejeita grupos mesmo que a extensão mande por engano
    jid = body.get("jid") or f"{number}@s.whatsapp.net"
    if jid.endswith("@g.us") or "status@broadcast" in jid:
        return {"ignored": "group-or-broadcast"}

    info = {
        "msg_id": body.get("msg_id") or f"{number}:{hash(text) & 0xffffffff}",
        "jid": jid,
        "number": number,
        "name": (body.get("name") or "").strip(),
        "text": text,
    }
    return _process(info, deliver=False)

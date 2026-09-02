"""
Agente de Vendas IA no WhatsApp — servidor de webhook.

Fluxo:
  Evolution (messages.upsert) -> /webhook?token=... -> Claude (playbook)
    -> resposta enviada pela Evolution -> estado do lead gravado no SQLite.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import config
import evolution
import store
from brain import reply

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

app = FastAPI(title="WhatsApp Sales Agent")


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
    state = evolution.connection_state()
    return {
        "service": "whatsapp-sales-agent",
        "instance": config.EVOLUTION_INSTANCE,
        "config_missing": config.validate(),
        "whatsapp": state,
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


@app.post("/webhook")
async def webhook(request: Request):
    # 1) Autenticação simples por token na query string
    if request.query_params.get("token") != config.WEBHOOK_TOKEN:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.json()
    event = body.get("event", "")

    # Só nos importa mensagem recebida
    if event not in ("messages.upsert", "MESSAGES_UPSERT"):
        return {"ignored": event}

    info = _extract(body)
    if not info:
        return {"ignored": "no-actionable-message"}

    # 2) Idempotência — Evolution pode reenviar o mesmo evento
    if store.already_processed(info["msg_id"]):
        return {"ok": True, "dup": True}

    jid = info["jid"]
    log.info("Lead %s (%s): %s", info["name"] or info["number"], jid, info["text"][:80])

    # 3) Registra lead + mensagem do usuário
    store.get_or_create_lead(jid, info["number"], info["name"])
    store.add_message(jid, "user", info["text"])

    # 4) Chama o cérebro
    history = store.get_history(jid, limit=20)
    answer = reply(history, lead_name=info["name"])

    # 5) Detecta handoff
    handoff = config.HANDOFF_MARKER in answer
    if handoff:
        answer = answer.replace(config.HANDOFF_MARKER, "").strip()

    # 6) Responde ao lead e grava
    evolution.send_text(info["number"], answer)
    store.add_message(jid, "assistant", answer)

    # 7) Atualiza status e avisa o dono se for lead quente
    if handoff:
        store.set_status(jid, "quente")
        evolution.notify_owner(
            f"🔥 LEAD QUENTE / assumir conversa\n"
            f"Nome: {info['name'] or '—'}\n"
            f"Número: {info['number']}\n"
            f"Última msg do lead: {info['text'][:150]}"
        )
    else:
        store.set_status(jid, "qualificado")

    return {"ok": True, "handoff": handoff}

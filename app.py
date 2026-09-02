"""
Agente de Vendas IA no WhatsApp — servidor de webhook.

Fluxo:
  Evolution (messages.upsert) -> /webhook?token=... -> Claude (playbook)
    -> resposta enviada pela Evolution -> estado do lead gravado no SQLite.
"""
import logging
import hashlib
import hmac

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

import config
import evolution
import instagram
import email_client
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
        "instagram": instagram.status(),
        "email": {
            "configured": email_client.configured(),
            "address": config.EMAIL_ADDRESS or None,
            "send_provider": config.email_send_provider(),
            "sent_today": store.emails_sent_today(),
            "daily_limit": config.EMAIL_DAILY_LIMIT,
        },
        "followup": {
            "enabled": config.FOLLOWUP_ENABLED,
            "hours": config.FOLLOWUP_HOURS,
            "due_now": len(store.due_followups()),
        },
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
    if not is_admin:
        store.record_inbound(jid)  # lead respondeu -> zera régua de follow-up

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
        # Reabre a régua de follow-up: se o lead sumir, a Vanessa retoma (dia 1/3/7).
        try:
            import followup
            followup.arm(jid, from_stage=0)
        except Exception as e:  # noqa: BLE001
            log.error("Falha ao agendar follow-up p/ %s: %s", jid, e)

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


# ═══════════════════════════════════════════════════════════════════════════
# INSTAGRAM (Meta Graph API) — DMs e comentários
# ═══════════════════════════════════════════════════════════════════════════

def _ig_valid_signature(raw: bytes, header: str) -> bool:
    """Valida X-Hub-Signature-256 usando o App Secret. Se não houver secret
    configurado, não bloqueia (útil em testes), mas loga um aviso."""
    if not config.IG_APP_SECRET:
        log.warning("IG_APP_SECRET não configurado — pulando validação de assinatura.")
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        config.IG_APP_SECRET.encode(), raw, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header)


def _ig_process(kind: str, sender_id: str, text: str, name: str = "", comment_id: str = "") -> dict:
    """Cérebro compartilhado para eventos do Instagram.

    kind: 'dm' (mensagem no Direct) | 'comment' (comentário em post).
    Reusa Claude + playbook + base de conhecimento + admin gate. O admin do
    Instagram é identificado pelo IGSID configurado (ADMIN_NUMBER não se aplica a
    IG); por padrão, no IG ninguém é admin (ajuste se quiser um IGSID de admin).
    """
    jid = f"ig_{kind}:{sender_id or comment_id}"
    if store.already_processed(f"ig:{comment_id or sender_id}:{hash(text) & 0xffffffff}"):
        return {"ok": True, "dup": True}

    store.get_or_create_lead(jid, sender_id or comment_id, name)
    store.add_message(jid, "user", text)

    # Limite diário (warming vale para IG também)
    if config.DAILY_SEND_LIMIT > 0 and store.assistant_msgs_today() >= config.DAILY_SEND_LIMIT:
        log.warning("Limite diário atingido — pulando resposta IG a %s", jid)
        return {"ok": True, "skipped": "daily_limit_reached"}

    history = store.get_history(jid, limit=20)

    if kind == "comment":
        mode = config.IG_COMMENT_MODE
        # Resposta pública (curta) — se o modo inclui 'public'
        if mode in ("public", "both"):
            pub = reply(history, lead_name=name, channel="ig_comment_public")
            pub = pub.replace(config.HANDOFF_MARKER, "").strip()
            if comment_id and pub:
                instagram.reply_comment(comment_id, pub)
                store.add_message(jid, "assistant", f"[público] {pub}")
        # DM privado (detalhe) — se o modo inclui 'dm'
        if mode in ("dm", "both"):
            dm = reply(history, lead_name=name, channel="ig_comment_dm")
            dm = dm.replace(config.HANDOFF_MARKER, "").strip()
            if comment_id and dm:
                instagram.private_reply(comment_id, dm)
                store.add_message(jid, "assistant", f"[dm] {dm}")
        store.set_status(jid, "qualificado")
        return {"ok": True, "channel": "ig_comment", "mode": mode}

    # kind == 'dm'
    answer = reply(history, lead_name=name, channel="ig_dm")
    handoff = config.HANDOFF_MARKER in answer
    answer = answer.replace(config.HANDOFF_MARKER, "").strip()
    if sender_id and answer:
        instagram.send_dm(sender_id, answer)
    store.add_message(jid, "assistant", answer)
    if handoff:
        store.set_status(jid, "quente")
        evolution.notify_owner(
            f"🔥 LEAD QUENTE (Instagram DM)\nIGSID: {sender_id}\n"
            f"Última msg: {text[:150]}"
        )
    else:
        store.set_status(jid, "qualificado")
    return {"ok": True, "channel": "ig_dm", "handoff": handoff, "reply": answer}


@app.get("/instagram/webhook")
async def ig_verify(request: Request):
    """Handshake de verificação do webhook (Meta envia GET com hub.challenge)."""
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == config.IG_VERIFY_TOKEN:
        return PlainTextResponse(p.get("hub.challenge", ""))
    return JSONResponse({"error": "verification failed"}, status_code=403)


@app.post("/instagram/webhook")
async def ig_webhook(request: Request):
    """Recebe eventos do Instagram: mensagens (Direct) e comentários."""
    raw = await request.body()
    if not _ig_valid_signature(raw, request.headers.get("X-Hub-Signature-256", "")):
        return JSONResponse({"error": "bad signature"}, status_code=401)

    body = await request.json()
    if body.get("object") != "instagram":
        return {"ignored": body.get("object")}

    results = []
    for entry in body.get("entry", []):
        # 1) Mensagens do Direct
        for m in entry.get("messaging", []):
            sender = (m.get("sender") or {}).get("id", "")
            # ignora echoes (mensagens que NÓS enviamos)
            if (m.get("message") or {}).get("is_echo"):
                continue
            # ignora nossas próprias msgs pelo IG_USER_ID
            if sender and sender == config.IG_USER_ID:
                continue
            text = (m.get("message") or {}).get("text", "").strip()
            if not text:
                continue
            results.append(_ig_process("dm", sender_id=sender, text=text))

        # 2) Comentários (changes com field='comments')
        for ch in entry.get("changes", []):
            if ch.get("field") != "comments":
                continue
            v = ch.get("value") or {}
            # ignora comentários do próprio dono da conta
            frm = v.get("from") or {}
            if frm.get("id") and frm.get("id") == config.IG_USER_ID:
                continue
            comment_id = v.get("id", "")
            text = (v.get("text") or "").strip()
            name = frm.get("username", "")
            if not text or not comment_id:
                continue
            results.append(_ig_process("comment", sender_id=frm.get("id", ""), text=text, name=name, comment_id=comment_id))

    return {"ok": True, "processed": len(results), "results": results}


# ═══════════════════════════════════════════════════════════════════════════
# E-MAIL — prospecção (1º toque) e disparo manual do poll de caixa de entrada
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/email/outreach")
async def email_outreach(request: Request):
    """Inicia uma conversa por e-mail (prospecção) com um lead.

    Payload JSON: { "to": "lead@x.com", "name": "Fulano", "seed": "veio do anúncio Y" }
    Protegido pelo WEBHOOK_TOKEN (?token=...). Agenda o follow-up automaticamente.
    """
    if request.query_params.get("token") != config.WEBHOOK_TOKEN:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    to = (body.get("to") or "").strip()
    if not to or "@" not in to:
        return JSONResponse({"error": "invalid_recipient"}, status_code=400)
    import email_worker
    return email_worker.start_email_outreach(to, name=(body.get("name") or "").strip(), seed=(body.get("seed") or "").strip())


@app.post("/email/poll")
async def email_poll(request: Request):
    """Dispara UMA leitura da caixa de entrada (útil para teste/cron externo)."""
    if request.query_params.get("token") != config.WEBHOOK_TOKEN:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    import email_worker
    return email_worker.poll_inbox_once()


@app.post("/followup/run")
async def followup_run(request: Request):
    """Roda os follow-ups vencidos agora (útil para teste/cron externo)."""
    if request.query_params.get("token") != config.WEBHOOK_TOKEN:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    import followup, email_worker
    return followup.run_once(deliver_wa=email_worker.deliver_wa, deliver_email=email_worker.deliver_email)

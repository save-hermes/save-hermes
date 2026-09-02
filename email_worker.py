"""Trabalhador de e-mail + follow-up da Vanessa.

Une três coisas, todas fora do servidor web (rodam num loop próprio):
  1. Lê a caixa de entrada (IMAP) e responde e-mails novos com a Vanessa.
  2. Dispara e-mails de prospecção (1º toque) quando solicitado.
  3. Roda o motor de follow-up (WhatsApp + e-mail) na cadência configurada.

Reaproveita o cérebro (brain.reply), a persona (playbook) e o banco (store).
As entregas passam pelos freios de warming (limite diário de e-mail).
"""
import logging
import time

import config
import email_client
import evolution
import store
from brain import reply
from playbook import build_subject

log = logging.getLogger("email_worker")


# ───────────────────────── Entregas (callbacks) ─────────────────────────

def deliver_email(to_addr: str, subject: str, body: str, lead: dict | None = None,
                  in_reply_to: str | None = None, references: str | None = None) -> dict:
    """Envia um e-mail respeitando o limite diário (deliverability/anti-spam)."""
    if config.EMAIL_DAILY_LIMIT > 0 and store.emails_sent_today() >= config.EMAIL_DAILY_LIMIT:
        log.warning("Limite diário de e-mail atingido — não enviando para %s", to_addr)
        return {"ok": False, "error": "email_daily_limit"}
    r = email_client.send(to_addr, subject, body, in_reply_to=in_reply_to, references=references)
    # Registra o envio para casar com os eventos do webhook do Resend (métricas).
    if r.get("ok") and r.get("message_id"):
        jid = (lead or {}).get("jid", "") if lead else ""
        store.record_email_send(r["message_id"], to_addr, jid=jid, subject=subject)
    return r


def deliver_wa(number: str, text: str) -> dict:
    """Envia WhatsApp pela Evolution (já tem jitter de warming embutido)."""
    try:
        evolution.send_text(number, text)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        log.error("Falha ao enviar WhatsApp p/ %s: %s", number, e)
        return {"ok": False, "error": str(e)}


# ───────────────────────── E-mail recebido ─────────────────────────

def _jid_for_email(addr: str) -> str:
    return f"email:{addr.strip().lower()}"


def _inject_websave_context(jid: str, email: str) -> None:
    """Busca o prontuário do lead no WEBSAVE (MCP) e injeta no histórico como
    contexto de sistema, para a Vanessa personalizar o atendimento. Faz isso no
    máximo 1x por lead (marca via tabela processed) para não repetir/gastar.
    """
    try:
        import websave_mcp
        if not websave_mcp.configured():
            return
        if store.already_processed(f"websave_ctx:{jid}"):
            return
        perfil = websave_mcp.buscar_lead(email)
        historico = websave_mcp.historico_lead(email, limit=10)
        if perfil and "[erro" not in perfil:
            ctx = (
                "[CONTEXTO DO CRM WEBSAVE — dados internos deste lead, use para "
                "personalizar o atendimento; NÃO cite que veio de um sistema]\n"
                f"{perfil}\n\n{historico}"
            )
            store.add_message(jid, "user", ctx)
            log.info("Contexto WEBSAVE injetado para %s", email)
    except Exception as e:  # noqa: BLE001
        log.warning("Falha ao buscar contexto WEBSAVE p/ %s: %s", email, e)


def process_inbound_email(mail: dict) -> dict:
    """Processa UM e-mail recebido: gera a resposta da Vanessa e responde na thread."""
    addr = mail.get("from_addr", "")
    if not addr or addr == config.EMAIL_ADDRESS.lower():
        return {"ok": True, "skipped": "self_or_empty"}

    # Idempotência pelo Message-ID.
    if store.already_processed(f"email:{mail.get('message_id') or mail.get('uid')}"):
        return {"ok": True, "dup": True}

    jid = _jid_for_email(addr)
    name = mail.get("from_name", "")
    body = mail.get("body", "").strip()
    if not body:
        return {"ok": True, "skipped": "empty_body"}

    # Vincula a um lead existente (por e-mail) ou cria um novo.
    existing = store.find_lead_by_email(addr)
    if existing:
        jid = existing["jid"]
    else:
        store.get_or_create_lead(jid, addr, name)
    store.set_email(jid, addr)
    store.add_message(jid, "user", body)
    store.record_inbound(jid)  # respondeu -> zera régua de follow-up
    # respondeu -> sai do fluxo de nutrição de mkt (vira atendimento 1:1)
    import flows
    flows.on_lead_replied(jid)

    # Consulta o WEBSAVE (CRM) para enriquecer o atendimento com o prontuário do lead.
    _inject_websave_context(jid, addr)

    # Limite diário de e-mail.
    if config.EMAIL_DAILY_LIMIT > 0 and store.emails_sent_today() >= config.EMAIL_DAILY_LIMIT:
        return {"ok": True, "skipped": "email_daily_limit"}

    history = store.get_history(jid, limit=20)
    answer = reply(history, lead_name=name, channel="email")
    handoff = config.HANDOFF_MARKER in answer
    answer = answer.replace(config.HANDOFF_MARKER, "").strip()

    # Assunto: responde na thread (Re: assunto original) mantendo o threading.
    subj = mail.get("subject") or "Sobre a Pré-Especialização em Reforma Tributária"
    if not subj.lower().startswith("re:"):
        subj = f"Re: {subj}"

    r = deliver_email(
        addr, subj, answer, lead=existing,
        in_reply_to=mail.get("message_id") or None,
        references=mail.get("references") or None,
    )
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}

    store.add_message(jid, "assistant", answer)
    if handoff:
        store.set_status(jid, "quente")
        evolution.notify_owner(
            f"🔥 LEAD QUENTE (E-mail)\nDe: {name or ''} <{addr}>\n"
            f"Assunto: {mail.get('subject','')}\nÚltima msg: {body[:150]}"
        )
    else:
        store.set_status(jid, "qualificado")
    # Como respondemos, a Vanessa reabre a régua de follow-up (aguardando resposta).
    from followup import arm
    arm(jid, from_stage=0)
    log.info("E-mail respondido para %s (%s)", addr, subj)
    return {"ok": True, "reply": answer, "handoff": handoff}


# ───────────────────────── Prospecção (1º toque) ─────────────────────────

def start_email_outreach(to_addr: str, name: str = "", seed: str = "") -> dict:
    """Inicia uma conversa por e-mail (prospecção). `seed` é um contexto opcional
    do lead (ex.: 'veio do anúncio X', 'perguntou sobre parcelamento') para a
    Vanessa personalizar o primeiro contato. Agenda o follow-up automaticamente.
    """
    if not email_client.configured():
        return {"ok": False, "error": "email_not_configured"}
    jid = _jid_for_email(to_addr)
    lead = store.get_or_create_lead(jid, to_addr, name)
    store.set_email(jid, to_addr)
    store.set_status(jid, "abordado")

    seed_msg = seed or "Escreva o primeiro e-mail de contato apresentando o curso de forma breve e convidando para conversar."
    history = [{"role": "user", "content": f"[SISTEMA] {seed_msg}"}]
    body = reply(history, lead_name=name, channel="email")
    body = body.replace(config.HANDOFF_MARKER, "").strip()
    subject = build_subject(history + [{"role": "assistant", "content": body}], lead_name=name)

    r = deliver_email(to_addr, subject, body, lead=lead)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    store.add_message(jid, "assistant", body)
    from followup import arm
    arm(jid, from_stage=0)  # começa a régua: dia 1, dia 3, dia 7
    log.info("Prospecção iniciada por e-mail para %s (%s)", to_addr, subject)
    return {"ok": True, "subject": subject, "body": body}


# ───────────────────────── Loop principal ─────────────────────────

def poll_inbox_once() -> dict:
    mails = email_client.fetch_unseen(limit=20)
    results = [process_inbound_email(m) for m in mails]
    return {"read": len(mails), "answered": sum(1 for r in results if r.get("ok") and r.get("reply"))}


_last_intake_day = [None]


def _maybe_daily_intake() -> None:
    """Roda a captação priorizada do WEBSAVE 1x por dia (dentro do horário comercial)."""
    import datetime
    import websave_sync
    import websave_mcp
    if not websave_mcp.configured():
        return
    import followup
    if not followup.within_business_hours():
        return
    today = datetime.date.today().isoformat()
    if _last_intake_day[0] == today:
        return
    _last_intake_day[0] = today
    try:
        r = websave_sync.run_intake(dry_run=False)
        if r.get("captados"):
            log.info("Intake diário WEBSAVE: %s leads captados (teto %s)",
                     r["captados"], r.get("teto_dia"))
    except Exception as e:  # noqa: BLE001
        log.error("Falha no intake diário WEBSAVE: %s", e)


def run_loop(interval_s: int = 60) -> None:
    """Loop: a cada `interval_s`, lê a caixa e roda os follow-ups vencidos."""
    import followup, flows
    store.init()
    flows.ensure_default_flow()
    log.info(
        "email_worker iniciado. email_configured=%s followup_enabled=%s intervalo=%ss",
        email_client.configured(), config.FOLLOWUP_ENABLED, interval_s,
    )
    while True:
        try:
            # PRIORIDADE: receptivo (inbound) SEMPRE antes de ativo (outbound).
            # 1) Responder quem escreveu (leads que levantaram a mão são mais quentes).
            inbound_pendente = 0
            if email_client.configured():
                r = poll_inbox_once()
                inbound_pendente = r["read"]
                if r["read"]:
                    log.info("Inbox: %s lidos, %s respondidos", r["read"], r["answered"])
            # 2) Follow-up de quem já está em conversa.
            fr = followup.run_once(deliver_wa=deliver_wa, deliver_email=deliver_email)
            if fr.get("sent"):
                log.info("Follow-up: %s enviados (de %s vencidos)", fr["sent"], fr.get("due"))
            # 3) Nutrição dos leads já captados (fluxos em andamento).
            cr = flows.run_once(deliver_email=deliver_email)
            if cr.get("sent"):
                log.info("Fluxo mkt: %s e-mails enviados (de %s vencidos)", cr["sent"], cr.get("due"))
            # 4) ATIVO por último: captar leads NOVOS do WEBSAVE (1x/dia, teto).
            #    Só capta lead frio novo quando NÃO há receptivo pendente neste ciclo,
            #    para o receptivo sempre ter prioridade sobre o ativo.
            if inbound_pendente == 0:
                _maybe_daily_intake()
        except Exception as e:  # noqa: BLE001
            log.error("Erro no loop do email_worker: %s", e)
        time.sleep(interval_s)


if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_loop(interval_s=int(os.getenv("WORKER_INTERVAL_S", "60")))

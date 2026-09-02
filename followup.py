"""Motor de follow-up: acompanha leads que esfriaram e envia o próximo toque.

Cadência clássica (config.FOLLOWUP_HOURS = "24,72,168"):
  - estágio 0 -> 1: 24h após o último contato sem resposta  (dia 1)
  - estágio 1 -> 2: +72h                                     (dia 3)
  - estágio 2 -> 3: +168h                                    (dia 7)
  - depois disso: para (não insiste mais).

O follow-up sai no CANAL principal do lead (WhatsApp por padrão; e-mail se o
lead veio/prefere e-mail e tem endereço). Se o lead RESPONDER a qualquer momento,
store.record_inbound() zera a régua — quem respondeu não recebe cobrança.

Este módulo só decide e monta a mensagem; a ENTREGA é injetada (deliver_wa /
deliver_email) para reaproveitar os mesmos freios de warming do app.
"""
import logging
import time

import config
import store
from brain import reply

log = logging.getLogger("followup")


def _stages() -> list[int]:
    """Lista de offsets em segundos por transição de estágio."""
    hours = [float(x) for x in config.FOLLOWUP_HOURS.split(",") if x.strip()]
    return [int(h * 3600) for h in hours]


def within_business_hours(now: float | None = None) -> bool:
    import datetime
    h = datetime.datetime.fromtimestamp(now or time.time()).hour
    return config.FOLLOWUP_HOUR_START <= h < config.FOLLOWUP_HOUR_END


def arm(jid: str, from_stage: int = 0) -> None:
    """Agenda o PRÓXIMO follow-up de um lead a partir de `from_stage`.

    Chame depois que a Vanessa iniciar um contato (1º e-mail/msg) OU depois de
    enviar um follow-up, para programar o toque seguinte. Se não houver mais
    estágios, não agenda nada (a régua terminou).
    """
    stages = _stages()
    if from_stage >= len(stages):
        store.clear_followup(jid)
        return
    next_at = int(time.time()) + stages[from_stage]
    store.schedule_followup(jid, next_at=next_at, stage=from_stage)


def _channel_for(lead: dict) -> str:
    ch = (lead.get("channel") or "").strip()
    if ch:
        return ch
    # Heurística: se tem e-mail e o jid é de e-mail, é e-mail; senão WhatsApp.
    if (lead.get("jid") or "").startswith("email:"):
        return "email"
    return "whatsapp"


def run_once(deliver_wa=None, deliver_email=None) -> dict:
    """Processa todos os follow-ups vencidos. Devolve um resumo.

    deliver_wa(number, text) e deliver_email(to_addr, subject, body, lead) são
    callbacks de entrega. Se um canal não tiver callback, os leads daquele canal
    são pulados (reagendados para daqui a pouco).
    """
    if not config.FOLLOWUP_ENABLED:
        return {"enabled": False, "sent": 0}
    if not within_business_hours():
        return {"enabled": True, "sent": 0, "reason": "fora_do_horario"}

    stages = _stages()
    due = store.due_followups()
    sent = skipped = 0

    for lead in due:
        jid = lead["jid"]
        stage = int(lead.get("followup_stage") or 0)
        channel = _channel_for(lead)
        name = lead.get("name") or ""

        # Monta o histórico e pede o texto do follow-up à Vanessa.
        history = store.get_history(jid, limit=20)
        if not history:
            # Nada de contexto: não inventa follow-up do nada.
            store.clear_followup(jid)
            continue
        # Sinaliza ao modelo que é um follow-up (sem resposta do lead).
        prompt_channel = "email_followup" if channel == "email" else channel
        nudge = {
            "role": "user",
            "content": "[SISTEMA] O lead não respondeu ao último contato. "
                       "Escreva um follow-up curto e leve para retomar, conforme as regras do canal.",
        }
        try:
            text = reply(history + [nudge], lead_name=name, channel=prompt_channel)
        except Exception as e:  # noqa: BLE001
            log.error("Follow-up: falha ao gerar texto p/ %s: %s", jid, e)
            skipped += 1
            continue

        handoff = config.HANDOFF_MARKER in text
        text = text.replace(config.HANDOFF_MARKER, "").strip()

        ok = False
        if channel == "email" and deliver_email and lead.get("email"):
            subject = "Sobre a Pré-Especialização em Reforma Tributária"
            r = deliver_email(lead["email"], f"Re: {subject}", text, lead)
            ok = bool(r and r.get("ok"))
        elif channel != "email" and deliver_wa:
            number = lead.get("number") or jid.split("@")[0]
            r = deliver_wa(number, text)
            ok = bool(r and r.get("ok", True))
        else:
            # Sem callback para este canal: reagenda em 1h e segue.
            store.schedule_followup(jid, int(time.time()) + 3600, stage)
            skipped += 1
            continue

        if not ok:
            store.schedule_followup(jid, int(time.time()) + 1800, stage)  # tenta em 30min
            skipped += 1
            continue

        store.add_message(jid, "assistant", text)
        new_stage = stage + 1
        if new_stage < len(stages):
            arm(jid, from_stage=new_stage)
        else:
            store.clear_followup(jid)  # última tentativa, encerra a régua
        if handoff:
            store.set_status(jid, "handoff")
            store.clear_followup(jid)
        sent += 1
        log.info("Follow-up estágio %d enviado p/ %s via %s", new_stage, jid, channel)

    return {"enabled": True, "sent": sent, "skipped": skipped, "due": len(due)}

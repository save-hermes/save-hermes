"""Motor de fluxos de e-mail marketing + porta única de ingest de leads.

Torna a Vanessa AUTÔNOMA: um lead que entra (de lista, WhatsApp, formulário) é
inscrito num fluxo de nutrição, e a cada passo vencido a Vanessa GERA o e-mail
(com persona + base) e dispara pelo Resend. Gatilhos param o fluxo sozinhos:
- lead RESPONDE  -> cancela o fluxo (vira atendimento 1:1, não recebe mais mkt)
- lead COMPRA/opt-out -> cancela
- fluxo termina  -> status 'concluido'

Um passo = {delay_h, goal, subject}. `goal` é o objetivo do e-mail (o que a
Vanessa deve escrever); a IA gera o texto conforme a persona.
"""
import logging
import time

import config
import store
from brain import reply

log = logging.getLogger("flows")

# ─────────────────── Fluxo padrão de nutrição (dia 0/2/4/6) ───────────────────
# delay_h = horas após a INSCRIÇÃO (ou após o passo anterior, ver seed).
DEFAULT_FLOW_ID = "nutricao_reforma"
DEFAULT_FLOW_STEPS = [
    {"delay_h": 0,   "subject": "Bem-vindo(a) à Save Educação",
     "goal": "Boas-vindas calorosas e breves. Apresente-se como Vanessa, agradeça o interesse na área de Reforma Tributária e diga que nos próximos dias vai compartilhar conteúdo útil. NÃO venda ainda. Termine perguntando a área de atuação da pessoa."},
    {"delay_h": 48,  "subject": "O que mais muda com a Reforma (na prática)",
     "goal": "E-mail de CONTEÚDO/educação. Traga 1 ponto concreto e útil sobre a Reforma (ex.: transição CBS/IBS até 2033, ou o impacto do Split Payment) de forma clara. Entregue valor real, sem pedir nada. Termine com uma pergunta que gere resposta."},
    {"delay_h": 96,  "subject": "Como sair do conceito para o diagnóstico",
     "goal": "E-mail de PROVA/transformação. Mostre a dor de 'entender o conceito mas travar no caso real' e como a Pré-Especialização resolve isso (aplicação prática, diagnóstico de casos). Pode mencionar que é formação técnica de 40h. Convide para conhecer, sem forçar."},
    {"delay_h": 144, "subject": "Últimos detalhes da Pré-Especialização",
     "goal": "E-mail de OFERTA. Apresente a oferta com o preço da base (R$ 197, campanha, parcelável), ancorando no valor de mercado (cursos parecidos passam de R$ 3.000) e reforçando a garantia de 7 dias. Inclua o link de checkout. Chamada clara para a matrícula."},
]


def ensure_default_flow() -> None:
    """Garante que os fluxos padrão existem no banco (idempotente)."""
    if not store.get_flow(DEFAULT_FLOW_ID):
        store.upsert_flow(DEFAULT_FLOW_ID, "Nutrição — Reforma Tributária", DEFAULT_FLOW_STEPS)
        log.info("Fluxo padrão '%s' criado.", DEFAULT_FLOW_ID)
    if not store.get_flow(MQL_FLOW_ID):
        store.upsert_flow(MQL_FLOW_ID, "MQL — leads qualificados (quiz)", MQL_FLOW_STEPS)
    if not store.get_flow(POSWEBINAR_FLOW_ID):
        store.upsert_flow(POSWEBINAR_FLOW_ID, "Pós-webinário — aquecimento", POSWEBINAR_FLOW_STEPS)
    if not store.get_flow(PARCERIA_FLOW_ID):
        store.upsert_flow(PARCERIA_FLOW_ID, "Parceria — qualificação + handoff", PARCERIA_FLOW_STEPS)


# Fluxo MQL (lead veio de quiz, já demonstrou intenção): aborda direto, mais consultivo.
MQL_FLOW_ID = "mql_quiz"
MQL_FLOW_STEPS = [
    {"delay_h": 0,   "subject": "Sobre o seu diagnóstico",
     "goal": "O lead respondeu um quiz/diagnóstico da Save (é um MQL, já demonstrou intenção). Aborde reconhecendo isso de forma consultiva: comente que viu o interesse dele no tema e pergunte qual a maior dificuldade prática hoje. NÃO empurre venda ainda; entenda o momento dele."},
    {"delay_h": 48,  "subject": "Como resolver isso na prática",
     "goal": "Conecte a dor típica de quem fez o diagnóstico à solução (Pré-Especialização: aplicação prática, diagnóstico de casos reais). Traga 1 argumento técnico forte. Convide a conhecer, sem forçar."},
    {"delay_h": 120, "subject": "Detalhes da Pré-Especialização",
     "goal": "E-mail de OFERTA. Apresente a oferta (R$ 197, campanha, parcelável), ancorando no valor de mercado e na garantia de 7 dias. Inclua o link de checkout. Chamada clara para a matrícula."},
]

# Fluxo pós-webinário: o lead se inscreveu num webinário cuja DATA JÁ PASSOU.
# Primeiro aquece perguntando como foi a aula; só depois tenta vender.
POSWEBINAR_FLOW_ID = "pos_webinario"
POSWEBINAR_FLOW_STEPS = [
    {"delay_h": 0,   "subject": "E aí, como foi a aula?",
     "goal": "O lead se inscreveu num webinário/aula da Save que JÁ ACONTECEU. Aborde de forma leve e genuína perguntando o que ele achou da aula, se conseguiu assistir e se ficou alguma dúvida sobre o tema. NÃO venda nada aqui; é só aquecer e abrir conversa."},
    {"delay_h": 72,  "subject": "Um passo além do que vimos na aula",
     "goal": "Conecte o conteúdo do webinário à necessidade de ir além (do conceito para a prática). Apresente a Pré-Especialização como o próximo passo natural de quem gostou da aula. Argumento técnico, convite leve."},
    {"delay_h": 168, "subject": "Condição da Pré-Especialização",
     "goal": "E-mail de OFERTA para quem veio de webinário. Apresente a oferta (R$ 197, campanha, parcelável) com ancoragem de valor e garantia de 7 dias, incluindo o link de checkout. Chamada clara."},
]

# Fluxo PARCERIA: lead veio de LP de captação de parceiro (NÃO é comprador de curso).
# A Vanessa qualifica com leveza e faz HANDOFF para um humano — nunca oferece curso.
PARCERIA_FLOW_ID = "parceria"
PARCERIA_FLOW_STEPS = [
    {"delay_h": 0, "subject": "Sobre a parceria com a Save",
     "goal": "O lead demonstrou interesse em ser PARCEIRO da Save (não é comprador de curso). Cumprimente, agradeça o interesse na parceria e faça 1 ou 2 perguntas de qualificação (área de atuação, se já atende clientes na área, o que busca com a parceria). Tom profissional. NÃO ofereça curso nem preço. Ao final, sinalize que um responsável vai dar sequência. Emita o marcador de handoff."},
]


def within_business_hours(now: float | None = None) -> bool:
    import datetime
    h = datetime.datetime.fromtimestamp(now or time.time()).hour
    return config.FOLLOWUP_HOUR_START <= h < config.FOLLOWUP_HOUR_END


# ─────────────────── Porta única de ingest de leads ───────────────────

def ingest_lead(email: str = "", name: str = "", number: str = "",
                source: str = "manual", flow_id: str | None = DEFAULT_FLOW_ID,
                seed: str = "") -> dict:
    """Ponto ÚNICO de entrada de um lead novo (lista, formulário, WhatsApp, etc.).

    Cria/atualiza o lead e, se tiver e-mail, inscreve no fluxo de nutrição — a
    Vanessa passa a atender/nutrir sozinha. Idempotente por lead.
    """
    email = (email or "").strip().lower()
    number = "".join(ch for ch in (number or "") if ch.isdigit())
    if not email and not number:
        return {"ok": False, "error": "sem_email_nem_numero"}

    # jid canônico: e-mail se houver, senão WhatsApp.
    if email:
        jid = f"email:{email}"
    else:
        jid = f"{number}@s.whatsapp.net"

    lead = store.get_or_create_lead(jid, number or email, name)
    if email:
        store.set_email(jid, email)
    # grava a origem
    with store._conn() as c:
        c.execute("UPDATE leads SET source=?, channel=?, updated_at=? WHERE jid=?",
                  (source, "email" if email else "whatsapp", int(time.time()), jid))

    enrolled = False
    if email and flow_id:
        f = store.get_flow(flow_id)
        if f and f.get("enabled"):
            first_delay = (f["steps"][0].get("delay_h", 0) if f["steps"] else 0)
            enrolled = store.enroll_in_flow(jid, flow_id, first_delay_h=first_delay)
            if enrolled:
                store.set_status(jid, "abordado")
    log.info("Ingest lead jid=%s source=%s enrolled=%s", jid, source, enrolled)
    return {"ok": True, "jid": jid, "enrolled": enrolled}


def on_lead_replied(jid: str) -> None:
    """Chamado quando um lead RESPONDE em qualquer canal: cancela fluxos de mkt.

    Quem respondeu vira atendimento 1:1 — não deve continuar recebendo a
    sequência automatizada de nutrição.
    """
    store.cancel_flows_for(jid, reason="respondeu")


# ─────────────────── Processamento dos passos vencidos ───────────────────

def run_once(deliver_email=None) -> dict:
    """Dispara todos os passos de fluxo vencidos. deliver_email(to, subj, body, lead)."""
    if not within_business_hours():
        return {"sent": 0, "reason": "fora_do_horario"}
    due = store.due_flow_steps()
    sent = skipped = 0

    for enr in due:
        jid = enr["jid"]
        flow = store.get_flow(enr["flow_id"])
        if not flow or not flow.get("enabled"):
            store.advance_flow(enr["id"], enr["step"], None, status="cancelado")
            continue
        steps = flow["steps"]
        step_idx = int(enr["step"])
        if step_idx >= len(steps):
            store.advance_flow(enr["id"], step_idx, None, status="concluido")
            continue

        lead = store.lead_detail(jid) or {}
        if lead.get("opted_out"):
            store.advance_flow(enr["id"], step_idx, None, status="cancelado")
            continue
        email = lead.get("email")
        if not email or not deliver_email:
            store.advance_flow(enr["id"], step_idx, int(time.time()) + 3600, status="ativo")
            skipped += 1
            continue

        step = steps[step_idx]
        # Descobre o PRODUTO certo pela origem/LP do lead (não empurra sempre a Pré-Espec.).
        produto_ctx = ""
        try:
            import products_map
            src = (lead.get("source") or "")
            slug = src.split("lp:", 1)[1] if "lp:" in src else ""
            if slug:
                info = products_map.lookup(slug)
                produto_ctx = (f"[PRODUTO/INTENÇÃO DESTE LEAD] Este lead veio da LP de "
                               f"'{info['produto']}'. Promova ESTE produto (foi o que ele "
                               f"demonstrou interesse). Intenção: {info['intencao']}.")
            else:
                # Sem LP clara: postura consultiva, produto mais acessível como ponto de partida.
                produto_ctx = (f"[PRODUTO/INTENÇÃO DESTE LEAD] Origem não aponta um produto "
                               f"específico. Seja consultiva: entenda a necessidade antes de "
                               f"ofertar. Em igualdade, comece pelo mais acessível "
                               f"('{products_map.PRODUTO_ENTRADA}'). Não abra com preço.")
        except Exception:  # noqa: BLE001
            pass

        # A Vanessa gera o texto do e-mail conforme o objetivo do passo + produto certo.
        history = store.get_history(jid, limit=10)
        parts = [f"[OBJETIVO DESTE E-MAIL DO FLUXO] {step.get('goal','')}"]
        if produto_ctx:
            parts.append(produto_ctx)
        instr = {"role": "user", "content": "\n".join(parts)}
        try:
            body = reply(history + [instr], lead_name=lead.get("name", ""), channel="email_campaign")
        except Exception as e:  # noqa: BLE001
            log.error("Fluxo: falha ao gerar passo %s p/ %s: %s", step_idx, jid, e)
            store.advance_flow(enr["id"], step_idx, int(time.time()) + 1800, status="ativo")
            skipped += 1
            continue
        handoff = config.HANDOFF_MARKER in body
        body = body.replace(config.HANDOFF_MARKER, "").strip()
        subject = step.get("subject") or "Save Educação"

        r = deliver_email(email, subject, body, lead)
        if not (r and r.get("ok")):
            store.advance_flow(enr["id"], step_idx, int(time.time()) + 1800, status="ativo")
            skipped += 1
            continue

        store.add_message(jid, "assistant", f"[fluxo:{flow['id']}#{step_idx}] {body}")

        # Handoff (ex.: fluxo de parceria) -> avisa o dono e encerra o fluxo.
        if handoff:
            store.set_status(jid, "handoff")
            store.advance_flow(enr["id"], step_idx + 1, None, status="convertido")
            try:
                import evolution
                evolution.notify_owner(
                    f"🤝 LEAD DE PARCERIA / assumir\nNome: {lead.get('name') or '—'}\n"
                    f"E-mail: {email}\nOrigem: {lead.get('source') or '—'}"
                )
            except Exception:  # noqa: BLE001
                pass
            sent += 1
            continue

        # agenda o próximo passo
        nxt = step_idx + 1
        if nxt < len(steps):
            delay_h = steps[nxt].get("delay_h", 48)
            store.advance_flow(enr["id"], nxt, int(time.time()) + int(delay_h * 3600), status="ativo")
        else:
            store.advance_flow(enr["id"], nxt, None, status="concluido")
        sent += 1
        log.info("Fluxo %s passo %s enviado p/ %s", flow["id"], step_idx, email)

    return {"sent": sent, "skipped": skipped, "due": len(due)}

"""Testes do fluxo de e-mail + follow-up (sem rede: SMTP/IMAP e Claude mockados)."""
import os
import tempfile
import time
import types

# DB isolado + credenciais fake ANTES de importar os módulos.
_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmp, "leads.db")
os.environ["EMAIL_ADDRESS"] = "vanessa@saveeducacao.com.br"
os.environ["EMAIL_APP_PASSWORD"] = "fake-app-password"
os.environ["ANTHROPIC_API_KEY"] = "sk-fake"
os.environ["FOLLOWUP_HOURS"] = "24,72,168"
os.environ["FOLLOWUP_HOUR_START"] = "0"
os.environ["FOLLOWUP_HOUR_END"] = "24"

import config  # noqa: E402
import store  # noqa: E402
import email_client  # noqa: E402
import followup  # noqa: E402
import email_worker  # noqa: E402
import brain  # noqa: E402
import playbook  # noqa: E402

store.init()

# ── Mocks ──────────────────────────────────────────────────────────────
_sent = []


def _fake_send(to_addr, subject, body, in_reply_to=None, references=None):
    _sent.append({"to": to_addr, "subject": subject, "body": body, "irt": in_reply_to})
    return {"ok": True, "message_id": f"<{len(_sent)}@test>"}


email_client.send = _fake_send  # type: ignore

# brain.reply mockado — devolve texto determinístico por canal.
_reply_calls = []


def _fake_reply(history, lead_name="", is_admin=False, channel="whatsapp"):
    _reply_calls.append({"channel": channel, "n": len(history)})
    if channel == "email_followup":
        return "Passando rapidinho pra saber se ainda faz sentido pra você. Quer que eu te mande os detalhes?"
    if channel == "email":
        return f"Oi {lead_name or 'tudo bem'}, sou a Vanessa da Save. Posso te explicar a Pré-Especialização?"
    return "Resposta padrão da Vanessa."


brain.reply = _fake_reply  # type: ignore
email_worker.reply = _fake_reply  # type: ignore
followup.reply = _fake_reply  # type: ignore
playbook.build_subject = lambda history, lead_name="": "Sobre a Pré-Especialização"  # type: ignore
email_worker.build_subject = playbook.build_subject  # type: ignore


def _reset():
    _sent.clear()
    _reply_calls.clear()


results = []


def check(name, cond):
    results.append((name, cond))
    print(("OK  " if cond else "FAIL") + "  " + name)


# ── 1. Prospecção (1º toque) envia e-mail e agenda follow-up ─────────────
_reset()
r = email_worker.start_email_outreach("lead1@example.com", name="Ana", seed="veio do anúncio")
check("outreach envia e-mail", r.get("ok") and len(_sent) == 1)
check("outreach usa canal email", any(c["channel"] == "email" for c in _reply_calls))
lead = store.find_lead_by_email("lead1@example.com")
check("outreach cria lead com e-mail", lead and lead["email"] == "lead1@example.com")
check("outreach agenda follow-up (stage 0)", lead and lead["next_followup_at"] is not None and lead["followup_stage"] == 0)

# ── 2. Follow-up vencido dispara e avança o estágio ──────────────────────
_reset()
# força o vencimento: puxa next_followup_at para o passado
with store._conn() as c:
    c.execute("UPDATE leads SET next_followup_at=? WHERE email=?", (int(time.time()) - 10, "lead1@example.com"))
fr = followup.run_once(deliver_wa=None, deliver_email=email_worker.deliver_email)
check("followup envia 1 e-mail", fr.get("sent") == 1 and len(_sent) == 1)
check("followup usa canal email_followup", any(c["channel"] == "email_followup" for c in _reply_calls))
lead = store.find_lead_by_email("lead1@example.com")
check("followup avança para stage 1", lead and lead["followup_stage"] == 1)
check("followup reagenda proximo toque", lead and lead["next_followup_at"] is not None)

# ── 3. Lead que RESPONDE zera a régua ────────────────────────────────────
_reset()
mail = {
    "from_addr": "lead1@example.com", "from_name": "Ana",
    "subject": "Re: Sobre a Pré-Especialização", "body": "Oi! Tenho interesse sim, quanto custa?",
    "message_id": "<inbound-1@example.com>", "in_reply_to": "", "references": "", "uid": "1",
}
r = email_worker.process_inbound_email(mail)
check("inbound responde e-mail", r.get("ok") and r.get("reply") and len(_sent) == 1)
check("inbound responde na thread (Re:)", _sent[0]["subject"].lower().startswith("re:"))
lead = store.find_lead_by_email("lead1@example.com")
# record_inbound zera o stage; depois arm(0) reagenda a partir do 0
check("inbound zera stage p/ 0", lead and lead["followup_stage"] == 0)

# ── 4. Idempotência: mesmo e-mail não é respondido 2x ────────────────────
_reset()
r2 = email_worker.process_inbound_email(mail)
check("inbound idempotente (dup)", r2.get("dup") is True and len(_sent) == 0)

# ── 5. Opt-out cancela follow-up ─────────────────────────────────────────
_reset()
store.opt_out(lead["jid"])
with store._conn() as c:
    c.execute("UPDATE leads SET next_followup_at=? WHERE jid=?", (int(time.time()) - 10, lead["jid"]))
fr = followup.run_once(deliver_wa=None, deliver_email=email_worker.deliver_email)
check("opt-out nao recebe follow-up", fr.get("sent") == 0)

# ── 6. Régua termina após o último estágio (dia 7) ───────────────────────
_reset()
store.get_or_create_lead("email:lead2@example.com", "lead2@example.com", "Beto")
store.set_email("email:lead2@example.com", "lead2@example.com")
store.add_message("email:lead2@example.com", "assistant", "primeiro contato")
followup.arm("email:lead2@example.com", from_stage=2)  # último estágio (index 2 de 3)
with store._conn() as c:
    c.execute("UPDATE leads SET next_followup_at=? WHERE email=?", (int(time.time()) - 10, "lead2@example.com"))
fr = followup.run_once(deliver_wa=None, deliver_email=email_worker.deliver_email)
lead2 = store.find_lead_by_email("lead2@example.com")
check("ultimo estagio envia e encerra régua", fr.get("sent") == 1 and lead2["next_followup_at"] is None)

# ── 7. Limite diário de e-mail barra o envio ─────────────────────────────
_reset()
config.EMAIL_DAILY_LIMIT = 1  # só 1 e-mail/dia
# já enviamos vários hoje -> deve barrar
r = email_worker.deliver_email("x@y.com", "Assunto", "Corpo")
check("limite diário de e-mail barra", r.get("ok") is False and r.get("error") == "email_daily_limit")
config.EMAIL_DAILY_LIMIT = 50

# ── 8. Canal email_followup existe no prompt ─────────────────────────────
p = playbook.build_system_prompt(lead_name="Ana", channel="email_followup")
# (build_subject foi mockado, mas build_system_prompt é real)
check("prompt email_followup tem regra de follow-up", "FOLLOW-UP" in p.upper())

print("\n" + "=" * 40)
passed = sum(1 for _, c in results if c)
print(f"{passed}/{len(results)} testes passaram")
raise SystemExit(0 if passed == len(results) else 1)

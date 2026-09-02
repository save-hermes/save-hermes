"""Testes do motor de fluxos de e-mail marketing (ingest + sequência + gatilhos)."""
import os
import tempfile
import time

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "flows.db")
os.environ["ANTHROPIC_API_KEY"] = "sk-fake"
os.environ["FOLLOWUP_HOUR_START"] = "0"
os.environ["FOLLOWUP_HOUR_END"] = "24"

import config  # noqa: E402
import store  # noqa: E402
import flows  # noqa: E402
import brain  # noqa: E402

store.init()
flows.ensure_default_flow()

# mock do cérebro: devolve texto por passo (sem chamar a API)
_calls = []
def _fake_reply(history, lead_name="", is_admin=False, channel="whatsapp"):
    goal = ""
    for m in history:
        if isinstance(m.get("content"), str) and "OBJETIVO DESTE E-MAIL" in m["content"]:
            goal = m["content"][:40]
    _calls.append({"channel": channel, "goal": goal})
    return f"E-mail gerado pela Vanessa (canal {channel})."
brain.reply = _fake_reply
flows.reply = _fake_reply

# mock de envio
_sent = []
def _deliver(to, subj, body, lead=None):
    _sent.append({"to": to, "subj": subj, "body": body}); return {"ok": True, "message_id": f"id-{len(_sent)}"}

results = []
def check(name, cond):
    results.append((name, cond)); print(("OK  " if cond else "FAIL")+"  "+name)

def _reset():
    _sent.clear(); _calls.clear()

# ── 1. Fluxo padrão existe com 4 passos ──
f = store.get_flow(flows.DEFAULT_FLOW_ID)
check("fluxo padrão existe", f is not None)
check("fluxo tem 4 passos", len(f["steps"]) == 4)

# ── 2. Ingest de lead de lista inscreve no fluxo ──
_reset()
r = flows.ingest_lead(email="lead1@x.com", name="Ana", source="lista")
check("ingest ok + inscrito", r["ok"] and r["enrolled"])
lead = store.find_lead_by_email("lead1@x.com")
check("lead criado com source=lista", lead and lead["source"] == "lista")
check("status virou abordado", lead["status"] == "abordado")

# ── 3. Ingest duplicado NÃO reinscreve ──
r2 = flows.ingest_lead(email="lead1@x.com", name="Ana", source="lista")
check("ingest idempotente (não reinscreve)", r2["enrolled"] is False)

# ── 4. Passo 0 (delay 0) dispara já ──
_reset()
res = flows.run_once(deliver_email=_deliver)
check("passo 0 disparou 1 e-mail", res["sent"] == 1 and len(_sent) == 1)
check("usou canal email_campaign", _calls and _calls[0]["channel"] == "email_campaign")
check("assunto do passo 0 (boas-vindas)", "Bem-vindo" in _sent[0]["subj"])

# ── 5. Não dispara de novo antes do delay do passo 1 (48h) ──
_reset()
res = flows.run_once(deliver_email=_deliver)
check("nada vence ainda", res["sent"] == 0)

# ── 6. Forçar vencimento do passo 1 -> dispara e agenda passo 2 ──
_reset()
with store._conn() as c:
    c.execute("UPDATE flow_enrollments SET next_at=? WHERE jid=?", (int(time.time())-10, lead["jid"]))
res = flows.run_once(deliver_email=_deliver)
check("passo 1 disparou", res["sent"] == 1)
check("assunto do passo 1 (conteúdo)", "muda com a Reforma" in _sent[0]["subj"])

# ── 7. Lead RESPONDE -> cancela o fluxo ──
_reset()
flows.on_lead_replied(lead["jid"])
st = store.flow_stats()
check("fluxo cancelado ao responder", st.get("respondeu", 0) >= 1)
# não deve mais disparar
with store._conn() as c:
    c.execute("UPDATE flow_enrollments SET next_at=? WHERE jid=?", (int(time.time())-10, lead["jid"]))
res = flows.run_once(deliver_email=_deliver)
check("não envia após responder", res["sent"] == 0)

# ── 8. Fluxo completo até o fim -> concluido ──
_reset()
flows.ingest_lead(email="lead2@x.com", name="Beto", source="formulario")
l2 = store.find_lead_by_email("lead2@x.com")
for _ in range(6):  # roda vários ciclos, forçando vencimento
    with store._conn() as c:
        c.execute("UPDATE flow_enrollments SET next_at=? WHERE jid=? AND status='ativo'", (int(time.time())-10, l2["jid"]))
    flows.run_once(deliver_email=_deliver)
enr = [e for e in store.due_flow_steps(now=int(time.time())+10**9)]
st2 = store.flow_stats()
check("lead2 recebeu os 4 passos", len([s for s in _sent if s["to"]=="lead2@x.com"]) == 4)
check("fluxo concluido ao fim", st2.get("concluido", 0) >= 1)

# ── 9. Ingest sem e-mail (só WhatsApp) cria lead mas não inscreve em fluxo de e-mail ──
_reset()
r = flows.ingest_lead(number="5547999998888", name="Carlos", source="whatsapp")
check("ingest whatsapp ok", r["ok"])
check("whatsapp não entra em fluxo de e-mail", r["enrolled"] is False)

print("\n" + "="*40)
p = sum(1 for _, c in results if c)
print(f"{p}/{len(results)} testes passaram")
raise SystemExit(0 if p == len(results) else 1)

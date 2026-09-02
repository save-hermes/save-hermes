"""Teste E2E da cadeia do webhook, com Claude e Evolution mockados."""
import os
import tempfile

# Configura ambiente ANTES de importar os módulos
os.environ.update({
    "EVOLUTION_URL": "https://fake.example.com",
    "EVOLUTION_INSTANCE": "educacao_teste",
    "EVOLUTION_API_KEY": "fake-key",
    "ANTHROPIC_API_KEY": "fake-anthropic",
    "WEBHOOK_TOKEN": "secret123",
    "OWNER_NOTIFY_NUMBER": "5511999998888",
    "DB_PATH": os.path.join(tempfile.gettempdir(), "test_leads.db"),
})
# banco limpo
try:
    os.remove(os.environ["DB_PATH"])
except FileNotFoundError:
    pass

from unittest.mock import patch
from fastapi.testclient import TestClient
import app as appmod

sent = []          # mensagens que "enviamos" ao lead/dono
brain_replies = [] # respostas que o "Claude" devolve


def fake_send_text(number, text):
    sent.append((number, text))
    return True


def make_payload(text, msg_id, from_me=False):
    return {
        "event": "messages.upsert",
        "instance": "educacao_teste",
        "data": {
            "key": {"remoteJid": "5511911112222@s.whatsapp.net", "fromMe": from_me, "id": msg_id},
            "pushName": "João Teste",
            "message": {"conversation": text},
        },
    }


client = TestClient(appmod.app)
appmod.store.init()  # startup não roda sem 'with TestClient(...)'; init manual
results = []

with patch.object(appmod.evolution, "send_text", side_effect=fake_send_text), \
     patch.object(appmod, "reply", side_effect=lambda h, lead_name: brain_replies.pop(0)):

    # 1) Token errado -> 401
    r = client.post("/webhook?token=WRONG", json=make_payload("oi", "m1"))
    results.append(("token errado bloqueia (401)", r.status_code == 401))

    # 2) Mensagem normal do lead -> responde
    brain_replies.append("Oi João! Que bom te ver por aqui 😊 Como posso ajudar?")
    r = client.post("/webhook?token=secret123", json=make_payload("Quero saber do curso", "m2"))
    ok = r.status_code == 200 and r.json().get("ok") and len(sent) == 1
    results.append(("responde ao lead", ok))
    results.append(("resposta foi pro numero certo", sent and sent[0][0] == "5511911112222"))

    # 3) Idempotência -> mesmo msg_id não responde de novo
    before = len(sent)
    r = client.post("/webhook?token=secret123", json=make_payload("Quero saber do curso", "m2"))
    results.append(("dedup: nao responde 2x o mesmo id", r.json().get("dup") is True and len(sent) == before))

    # 4) fromMe (nossa própria msg) -> ignora
    r = client.post("/webhook?token=secret123", json=make_payload("mensagem nossa", "m3", from_me=True))
    results.append(("ignora mensagens fromMe", r.json().get("ignored") is not None))

    # 5) Handoff -> remove marcador e avisa o dono
    brain_replies.append("Perfeito! Vou te passar pro nosso especialista finalizar 🙌\n[[HANDOFF]]")
    before = len(sent)
    r = client.post("/webhook?token=secret123", json=make_payload("Quero comprar agora!", "m4"))
    j = r.json()
    lead_msg = sent[before]        # msg pro lead
    owner_msg = sent[before + 1]   # aviso pro dono
    results.append(("handoff detectado", j.get("handoff") is True))
    results.append(("marcador removido da msg do lead", "[[HANDOFF]]" not in lead_msg[1]))
    results.append(("dono foi avisado", owner_msg[0] == "5511999998888" and "LEAD QUENTE" in owner_msg[1]))

    # 6) Grupo -> ignora
    grp = make_payload("oi grupo", "m5")
    grp["data"]["key"]["remoteJid"] = "123456@g.us"
    r = client.post("/webhook?token=secret123", json=grp)
    results.append(("ignora grupos", r.json().get("ignored") is not None))

print()
allok = True
for name, ok in results:
    print(f"  [{'PASS' if ok else 'FALHOU'}] {name}")
    allok = allok and ok
print()
print("RESULTADO:", "TODOS PASSARAM ✅" if allok else "HÁ FALHAS ❌")

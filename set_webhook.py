"""
Liga o webhook da Evolution API v2 ao agente. Rodar UMA vez.

Faz um POST em /webhook/set/{instance} dizendo à Evolution:
"toda vez que chegar mensagem (MESSAGES_UPSERT), me avise em AGENT_URL/webhook?token=..."

Uso (do seu PC, com as variáveis preenchidas):

  EVOLUTION_URL=https://marketing-evolution-api.icoeqn.easypanel.host \
  EVOLUTION_INSTANCE=educacao_teste \
  EVOLUTION_API_KEY=<sua key> \
  AGENT_URL=https://SEU-APP.easypanel.host \
  WEBHOOK_TOKEN=<o mesmo segredo do deploy> \
  python set_webhook.py
"""
import os
import sys

import httpx


def _clean(u: str) -> str:
    return (u or "").strip().rstrip("/")


EVOLUTION_URL = _clean(os.getenv("EVOLUTION_URL", ""))
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "").strip()
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "").strip()
AGENT_URL = _clean(os.getenv("AGENT_URL", ""))
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "").strip()


def main() -> int:
    missing = [
        name
        for name, val in [
            ("EVOLUTION_URL", EVOLUTION_URL),
            ("EVOLUTION_INSTANCE", EVOLUTION_INSTANCE),
            ("EVOLUTION_API_KEY", EVOLUTION_API_KEY),
            ("AGENT_URL", AGENT_URL),
            ("WEBHOOK_TOKEN", WEBHOOK_TOKEN),
        ]
        if not val
    ]
    if missing:
        print("ERRO: faltam variáveis de ambiente:", ", ".join(missing))
        return 1

    webhook_url = f"{AGENT_URL}/webhook?token={WEBHOOK_TOKEN}"
    endpoint = f"{EVOLUTION_URL}/webhook/set/{EVOLUTION_INSTANCE}"
    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}

    # Formato Evolution API v2 (objeto "webhook" aninhado).
    payload = {
        "webhook": {
            "enabled": True,
            "url": webhook_url,
            "byEvents": False,
            "base64": False,
            "events": ["MESSAGES_UPSERT"],
        }
    }

    print(f"Configurando webhook da instância '{EVOLUTION_INSTANCE}'...")
    print(f"  -> {webhook_url}")
    try:
        r = httpx.post(endpoint, json=payload, headers=headers, timeout=30)
    except Exception as e:  # noqa: BLE001
        print("ERRO de rede:", e)
        return 1

    print("Status:", r.status_code)
    print("Resposta:", r.text[:600])

    if r.status_code >= 400:
        # Fallback: algumas builds v2 aceitam o payload achatado (sem "webhook").
        print("\nTentando formato alternativo (payload achatado)...")
        flat = {
            "enabled": True,
            "url": webhook_url,
            "webhookByEvents": False,
            "webhookBase64": False,
            "events": ["MESSAGES_UPSERT"],
        }
        r2 = httpx.post(endpoint, json=flat, headers=headers, timeout=30)
        print("Status:", r2.status_code)
        print("Resposta:", r2.text[:600])
        return 0 if r2.status_code < 400 else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

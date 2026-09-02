"""O cérebro do agente: monta a persona + playbook e chama o Claude."""
import logging

from anthropic import Anthropic

import config
from playbook import build_system_prompt

log = logging.getLogger("brain")

_client = Anthropic(api_key=config.ANTHROPIC_API_KEY)


def reply(history: list[dict], lead_name: str, is_admin: bool = False, channel: str = "whatsapp",
          extra_context: str = "") -> str:
    """Recebe o histórico [{'role','content'}...] e devolve a resposta do vendedor IA."""
    system = build_system_prompt(lead_name=lead_name, is_admin=is_admin, channel=channel,
                                 extra_context=extra_context)
    try:
        resp = _client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=config.ANTHROPIC_MAX_TOKENS,
            system=system,
            messages=history,
        )
        # Concatena blocos de texto
        parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        return "".join(parts).strip()
    except Exception as e:  # noqa: BLE001
        log.error("Erro ao chamar Claude: %s", e)
        # Fallback seguro — nunca deixa o lead no vácuo
        return (
            "Opa, tive uma instabilidade rápida aqui. Pode repetir a última mensagem? 🙏"
        )

"""Cliente da Evolution API v2 — enviar texto e checar conexão."""
import logging
import time

import httpx

import config

log = logging.getLogger("evolution")


def _headers() -> dict:
    return {"apikey": config.EVOLUTION_API_KEY, "Content-Type": "application/json"}


def _sanitize(text: str) -> str:
    """Remove travessões/hífens longos das mensagens enviadas ao lead.

    O cliente pediu que a IA nunca use travessão. O prompt já orienta isso,
    mas aqui garantimos no código, cobrindo casos que o modelo deixar passar:
      "texto — texto"  -> "texto, texto"   (travessão entre espaços vira vírgula)
      "texto—texto"    -> "texto, texto"   (travessão colado também)
      "— texto"        -> "texto"          (travessão de abertura some)
    """
    if not text:
        return text
    import re

    # 1) Travessões longos (— – ―) SEMPRE viram vírgula, colados ou com espaço.
    #    São sempre uso de travessão, nunca palavra composta.
    text = re.sub(r"\s*[—–―]\s*", ", ", text)
    # 2) Hífen longo escrito como 2+ hifens ASCII (-- ou ---) vira vírgula.
    text = re.sub(r"\s*-{2,}\s*", ", ", text)
    # 3) Hífen ASCII cercado de espaços (" - ") é uso de travessão -> vírgula.
    #    Hífen colado (guarda-chuva, IBS-CBS) é preservado.
    text = re.sub(r"\s+-\s+", ", ", text)
    # 4) Hífen de abertura de linha ("- item") some.
    text = re.sub(r"(?m)^\s*-\s+", "", text)
    # 5) Limpa vírgulas duplicadas/sobras.
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"\s+,", ",", text)
    # 6) Remove vírgula/pontuação órfã no início de cada linha e do texto.
    text = re.sub(r"(?m)^\s*,\s*", "", text)
    return text.strip()


def send_text(number: str, text: str) -> bool:
    """Envia uma mensagem de texto. `number` = só dígitos (ex.: 5511999998888)."""
    text = _sanitize(text)
    url = f"{config.EVOLUTION_URL}/message/sendText/{config.EVOLUTION_INSTANCE}"
    payload = {"number": number, "text": text}
    if config.SEND_DELAY_MS > 0:
        payload["delay"] = config.SEND_DELAY_MS
    try:
        r = httpx.post(url, json=payload, headers=_headers(), timeout=30)
        if r.status_code >= 400:
            log.error("Falha ao enviar (%s): %s", r.status_code, r.text[:300])
            return False
        return True
    except Exception as e:  # noqa: BLE001
        log.error("Erro de rede ao enviar: %s", e)
        return False


def notify_owner(text: str) -> None:
    """Avisa o dono (você) num lead quente, se OWNER_NOTIFY_NUMBER estiver setado."""
    if config.OWNER_NOTIFY_NUMBER:
        send_text(config.OWNER_NOTIFY_NUMBER, text)


def connection_state() -> dict:
    """Estado da conexão da instância (open = conectado ao WhatsApp)."""
    url = f"{config.EVOLUTION_URL}/instance/connectionState/{config.EVOLUTION_INSTANCE}"
    try:
        r = httpx.get(url, headers=_headers(), timeout=15)
        return r.json()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}

"""Cliente da Instagram Graph API (Meta) — DMs e comentários.

Três operações:
  - send_dm(igsid, text): responde uma mensagem no Direct (janela de 24h).
  - reply_comment(comment_id, text): responde publicamente no próprio comentário.
  - private_reply(comment_id, text): manda um DM privado disparado por um comentário.

Todas usam o token de longa duração (config.IG_ACCESS_TOKEN). Falham de forma
segura: logam o erro e retornam False, nunca derrubam o webhook.
"""
import logging

import httpx

import config

log = logging.getLogger("instagram")


def _base() -> str:
    return f"https://graph.facebook.com/{config.IG_GRAPH_VERSION}"


def _sanitize(text: str) -> str:
    """Remove travessões (mesma regra do WhatsApp) — a persona não usa travessão."""
    if not text:
        return text
    import re
    text = re.sub(r"\s*[—–―]\s*", ", ", text)
    text = re.sub(r"\s*-{2,}\s*", ", ", text)
    text = re.sub(r"\s+-\s+", ", ", text)
    text = re.sub(r"(?m)^\s*-\s+", "", text)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r"(?m)^\s*,\s*", "", text)
    return text.strip()


def _post(path: str, payload: dict) -> bool:
    url = f"{_base()}/{path}"
    params = {"access_token": config.IG_ACCESS_TOKEN}
    try:
        r = httpx.post(url, params=params, json=payload, timeout=30)
        if r.status_code >= 400:
            log.error("IG API falhou (%s) em %s: %s", r.status_code, path, r.text[:300])
            return False
        return True
    except Exception as e:  # noqa: BLE001
        log.error("Erro de rede na IG API (%s): %s", path, e)
        return False


def send_dm(igsid: str, text: str) -> bool:
    """Envia DM para um usuário (IG-scoped ID). Respeita a janela de 24h da Meta."""
    text = _sanitize(text)
    return _post(
        f"{config.IG_USER_ID}/messages",
        {"recipient": {"id": igsid}, "message": {"text": text}},
    )


def reply_comment(comment_id: str, text: str) -> bool:
    """Responde publicamente no próprio comentário."""
    text = _sanitize(text)
    return _post(f"{comment_id}/replies", {"message": text})


def private_reply(comment_id: str, text: str) -> bool:
    """Dispara um DM privado a partir de um comentário (private reply)."""
    text = _sanitize(text)
    return _post(
        f"{config.IG_USER_ID}/messages",
        {"recipient": {"comment_id": comment_id}, "message": {"text": text}},
    )


def get_user_profile(igsid: str) -> dict:
    """Busca o perfil de quem mandou DM — SOMENTE os campos que a Meta libera.

    A API de mensagens do Instagram expõe apenas: name, username, follower_count,
    is_user_follow_business, is_business_follow_user, is_verified_user, profile_pic.
    NÃO existe acesso a posts, bio ou interesses da pessoa (privacidade da Meta).
    Falha de forma segura: retorna {} em erro.
    """
    if not igsid:
        return {}
    url = f"{_base()}/{igsid}"
    fields = ("name,username,profile_pic,follower_count,is_verified_user,"
              "is_user_follow_business,is_business_follow_user")
    try:
        r = httpx.get(url, params={"fields": fields, "access_token": config.IG_ACCESS_TOKEN},
                      timeout=20)
        if r.status_code >= 400:
            log.warning("Perfil IG %s indisponível (%s): %s", igsid, r.status_code, r.text[:150])
            return {}
        return r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("Erro ao buscar perfil IG %s: %s", igsid, e)
        return {}


def hide_comment(comment_id: str, hide: bool = True) -> bool:
    """Oculta/reexibe um comentário (útil para spam/hostil). Não usar sozinho."""
    url = f"{_base()}/{comment_id}"
    params = {"access_token": config.IG_ACCESS_TOKEN, "hide": str(hide).lower()}
    try:
        r = httpx.post(url, params=params, timeout=30)
        return r.status_code < 400
    except Exception as e:  # noqa: BLE001
        log.error("Erro ao ocultar comentário: %s", e)
        return False


def status() -> dict:
    """Resumo de configuração para o health check (sem expor segredos)."""
    return {
        "configured": bool(config.IG_ACCESS_TOKEN and config.IG_USER_ID),
        "ig_user_id": config.IG_USER_ID or None,
        "graph_version": config.IG_GRAPH_VERSION,
        "comment_mode": config.IG_COMMENT_MODE,
    }

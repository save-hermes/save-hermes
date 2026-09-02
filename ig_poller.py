"""
ig_poller.py — Polling de comentários do Instagram (funciona sem App Review).

Enquanto o webhook de mensagens/comentários em tempo real depende de App Review
aprovado, este poller consulta a Graph API periodicamente:
  1. lista as mídias recentes da conta,
  2. pega os comentários de cada uma,
  3. para cada comentário NOVO (não visto e não da própria conta), chama o mesmo
     cérebro do agente (via app._ig_process) para responder público + DM.

Uso:
  python ig_poller.py            # roda em loop
  POLL_INTERVAL_S=45 python ig_poller.py

Idempotência: usa a tabela `processed` do store (mesma do resto do agente).
"""
import os
import time
import logging

import httpx

import config
import store

log = logging.getLogger("ig_poller")

G = f"https://graph.facebook.com/{config.IG_GRAPH_VERSION}"
POLL_INTERVAL_S = int(os.getenv("POLL_INTERVAL_S", "60"))
MEDIA_LOOKBACK = int(os.getenv("IG_MEDIA_LOOKBACK", "10"))


def _get(path, **params):
    params["access_token"] = config.IG_ACCESS_TOKEN
    r = httpx.get(f"{G}/{path}", params=params, timeout=30)
    if r.status_code >= 400:
        log.warning("GET %s falhou (%s): %s", path, r.status_code, r.text[:200])
        return {}
    return r.json()


def poll_once() -> int:
    """Uma passada: retorna quantos comentários novos foram processados."""
    from app import _ig_process  # import tardio para reusar o cérebro

    processed = 0
    media = _get(f"{config.IG_USER_ID}/media",
                 fields="id,comments_count", limit=str(MEDIA_LOOKBACK)).get("data", [])
    for m in media:
        if not m.get("comments_count"):
            continue
        comments = _get(f"{m['id']}/comments",
                        fields="id,text,username,from,timestamp", limit="50").get("data", [])
        for c in comments:
            cid = c.get("id", "")
            text = (c.get("text") or "").strip()
            frm = c.get("from") or {}
            # ignora comentários da própria conta
            if frm.get("id") and frm.get("id") == config.IG_USER_ID:
                continue
            if not cid or not text:
                continue
            # dedup pela tabela processed
            if store.already_processed(f"igpoll:{cid}"):
                continue
            name = c.get("username") or frm.get("username", "")
            log.info("Comentário novo de @%s: %s", name, text[:60])
            _ig_process("comment", sender_id=frm.get("id", ""), text=text,
                        name=name, comment_id=cid)
            processed += 1
    return processed


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    store.init()
    if not (config.IG_ACCESS_TOKEN and config.IG_USER_ID):
        log.error("IG não configurado (IG_ACCESS_TOKEN/IG_USER_ID). Abortando.")
        return
    log.info("Poller de comentários IG iniciado. Intervalo=%ss, conta=%s",
             POLL_INTERVAL_S, config.IG_USER_ID)
    while True:
        try:
            n = poll_once()
            if n:
                log.info("Processados %d comentário(s) novo(s).", n)
        except Exception as e:  # noqa: BLE001
            log.error("Erro no ciclo de polling: %s", e)
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()

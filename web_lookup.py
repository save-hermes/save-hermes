"""Consulta contexto PÚBLICO de uma pessoa na web (grátis, seguro).

Usado para enriquecer o rapport da Vanessa no Instagram sem tocar no instagram.com
(evita risco de ban da conta). Busca o @username / nome no DuckDuckGo e devolve os
snippets públicos indexados (bio, profissão, site, outras redes) — só o que já é
público e aparece em buscador.

NÃO faz scraping do Instagram. Falha de forma segura: retorna "" em qualquer erro.
"""
import html
import logging
import re

import httpx

log = logging.getLogger("web_lookup")

_TAG = re.compile(r"<[^>]+>")
_UISH = re.compile(r"instagram\.com|facebook\.com|linkedin\.com|threads\.net", re.I)


def _clean(s: str) -> str:
    return html.unescape(_TAG.sub("", s or "")).strip()


def buscar_pessoa(username: str = "", nome: str = "", max_snippets: int = 4) -> str:
    """Busca contexto público da pessoa. Devolve um texto curto ou "".

    Combina @username (Instagram) e nome, se houver. Retorna snippets do buscador,
    priorizando bio/perfis públicos. Nunca inventa: só o que o buscador retorna.
    """
    termos = []
    if username:
        termos.append(f"{username} instagram")
    if nome:
        termos.append(nome)
    if not termos:
        return ""
    query = termos[0] if len(termos) == 1 else f"{username} {nome}".strip()

    try:
        r = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=15,
            follow_redirects=True,
        )
        if r.status_code >= 400:
            return ""
        # extrai título + snippet de cada resultado
        titulos = re.findall(r'class="result__a"[^>]*>(.*?)</a>', r.text, re.S)
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', r.text, re.S)
        out, seen = [], set()
        for i, snip in enumerate(snippets):
            titulo = titulos[i] if i < len(titulos) else ""
            t, s = _clean(titulo), _clean(snip)
            if not s or s in seen:
                continue
            seen.add(s)
            marca = "· " if _UISH.search(titulo) else "- "
            out.append(f"{marca}{t}: {s}" if t else f"{marca}{s}")
            if len(out) >= max_snippets:
                break
        if not out:
            return ""
        return "Menções públicas na web (não confirmadas — use com cautela, não como fato):\n" + "\n".join(out)
    except Exception as e:  # noqa: BLE001
        log.warning("web_lookup falhou p/ %s: %s", username or nome, e)
        return ""

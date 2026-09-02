"""Cliente do MCP do WEBSAVE (save-educacao-mcp-server).

A Vanessa consulta o CRM/leads do sistema de webinars (webnairs.saveeducacao.com.br)
por aqui: perfil consolidado de um lead, prontuário (histórico de eventos),
listagem de leads/webinários/quizzes/landing pages. Também é a fonte das LPs de
produto que rodam tráfego (para abordar/ofertar) e dos dados que personalizam a
comunicação (e-mail/WhatsApp/e-mail mkt).

SPEC (oficial): POST JSON-RPC, protocolVersion 2025-06-18, SEM stream SSE.
Headers mínimos: Content-Type: application/json + Authorization: Bearer <token>.
NÃO envie 'text/event-stream' no Accept — isso aciona o caminho SSE e o servidor
responde 500 {"error":"Only HTML requests are supported here"}.
"""
import json
import logging

import httpx

import config

log = logging.getLogger("websave_mcp")

_URL = config.WEBSAVE_MCP_URL
_TOKEN = config.WEBSAVE_MCP_TOKEN
_PROTO = "2025-06-18"

# Headers mínimos da spec oficial (sem event-stream, sem hack de navegador).
_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {_TOKEN}",
    "Accept": "application/json",
}

_id = 0


def configured() -> bool:
    return bool(_URL and _TOKEN)


def _rpc(method: str, params: dict | None = None, timeout: int = 30) -> dict:
    global _id
    _id += 1
    body = {"jsonrpc": "2.0", "id": _id, "method": method}
    if params is not None:
        body["params"] = params
    r = httpx.post(_URL, headers=_HEADERS, json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _call_text(tool: str, args: dict | None = None) -> str:
    """Chama uma tool e devolve o texto (as tools retornam markdown pronto)."""
    j = _rpc("tools/call", {"name": tool, "arguments": args or {}})
    if "error" in j:
        return f"[erro MCP: {j['error'].get('message', j['error'])}]"
    content = (j.get("result") or {}).get("content", [])
    parts = [c.get("text", "") for c in content if c.get("type") == "text"]
    return "\n".join(parts).strip() or json.dumps(j.get("result", {}), ensure_ascii=False)


def list_tools() -> list[dict]:
    j = _rpc("tools/list", {})
    return (j.get("result") or {}).get("tools", [])


# ─────────── Atalhos de alto nível (o que a Vanessa mais usa) ───────────

def buscar_lead(email: str) -> str:
    """Perfil consolidado do lead: nome, WhatsApp, tags, quizzes/LPs/webinários."""
    return _call_text("save_buscar_lead", {"email": email})


def historico_lead(email: str, limit: int = 15) -> str:
    """Prontuário: linha do tempo de eventos do lead (inscrições, quizzes, etc.)."""
    return _call_text("save_historico_lead", {"email": email, "limit": limit})


def listar_leads(origem: str = "", desde: str = "", limit: int = 20, offset: int = 0) -> str:
    args = {"limit": limit, "offset": offset}
    if origem:
        args["origem"] = origem
    if desde:
        args["desde"] = desde
    return _call_text("save_listar_leads", args)


def listar_webinarios(status: str = "", limit: int = 20, offset: int = 0) -> str:
    args = {"limit": limit, "offset": offset}
    if status:
        args["status"] = status
    return _call_text("save_listar_webinarios", args)


def buscar_webinario(identificador: str) -> str:
    return _call_text("save_buscar_webinario", {"identificador": identificador})


def listar_quizzes(status: str = "", limit: int = 20, offset: int = 0) -> str:
    args = {"limit": limit, "offset": offset}
    if status:
        args["status"] = status
    return _call_text("save_listar_quizzes", args)


def listar_landing_pages(status: str = "", limit: int = 20, offset: int = 0) -> str:
    args = {"limit": limit, "offset": offset}
    if status:
        args["status"] = status
    return _call_text("save_listar_landing_pages", args)


def status() -> dict:
    """Health do MCP para o /health do agente."""
    if not configured():
        return {"configured": False}
    try:
        tools = list_tools()
        return {"configured": True, "tools": len(tools),
                "tool_names": [t["name"] for t in tools]}
    except Exception as e:  # noqa: BLE001
        return {"configured": True, "error": str(e)[:120]}


# ─────────── Parsing dos leads (as tools devolvem markdown) ───────────

import re as _re

_LEAD_LINE = _re.compile(r"-\s+\*\*(?P<nome>.+?)\*\*\s+<(?P<email>[^>]+)>")
_TOTAL = _re.compile(r"Mostrando\s+\d+\s+de\s+(\d+)")


def parse_leads(md: str) -> list[dict]:
    """Extrai [{nome,email}] de uma resposta markdown de save_listar_leads."""
    out = []
    for m in _LEAD_LINE.finditer(md or ""):
        out.append({"nome": m.group("nome").strip(), "email": m.group("email").strip().lower()})
    return out


def total_leads(md: str) -> int:
    m = _TOTAL.search(md or "")
    return int(m.group(1)) if m else 0


def fetch_leads_page(origem: str = "lp", limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    """Devolve (leads_da_pagina, total). origem: lp | quiz | webinario."""
    md = listar_leads(origem=origem, limit=limit, offset=offset)
    return parse_leads(md), total_leads(md)

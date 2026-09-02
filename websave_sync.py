"""Captação PRIORIZADA de leads do WEBSAVE para a nutrição da Vanessa.

Regra de negócio (definida com o usuário):
  Tier 1 — leads recentes de WhatsApp + Landing Pages de produto → fluxo de
           nutrição de venda (nutricao_reforma). Prioridade máxima.
  Tier 2 — MQL: leads de quiz (já qualificados) → fluxo consultivo (mql_quiz).
  Tier 3 — leads de webinário → fluxo pós-webinário (pos_webinario), abordagem
           "como foi a aula?" antes de vender.

Teto: no máximo WEBSAVE_DAILY_INTAKE leads NOVOS por dia (padrão 20), mesmo que
haja milhares na fila. Os tiers são consumidos em ordem: só desce pro tier
seguinte quando o de cima esgota (ou não tem lead novo).

SEGURANÇA: dry_run=True por padrão. O envio em si continua governado pelo motor
de fluxos (horário comercial + EMAIL_DAILY_LIMIT), então a saída é gradual.
"""
import logging

import config
import websave_mcp
import store
import flows

log = logging.getLogger("websave_sync")

# origem no WEBSAVE -> (flow_id da Vanessa, label do tier)
TIERS = [
    ("lp",        flows.DEFAULT_FLOW_ID,      "Tier 1 · LP de produto"),
    ("quiz",      flows.MQL_FLOW_ID,          "Tier 2 · MQL (quiz)"),
    ("webinario", flows.POSWEBINAR_FLOW_ID,   "Tier 3 · pós-webinário"),
]


def _collect_new(origem: str, need: int, page_size: int = 50) -> list[dict]:
    """Coleta até `need` leads da origem que AINDA NÃO são leads nossos (novos)."""
    out, offset, total = [], 0, 1
    seen = set()
    while len(out) < need and offset < max(total, 1):
        page, total = websave_mcp.fetch_leads_page(origem=origem, limit=page_size, offset=offset)
        if not page:
            break
        for lead in page:
            e = lead.get("email", "")
            if not e or "@" not in e or e in seen:
                continue
            seen.add(e)
            # "novo" = ainda não existe como lead com e-mail no nosso CRM
            if store.find_lead_by_email(e) is None:
                out.append(lead)
                if len(out) >= need:
                    break
        offset += page_size
    return out


def _route_lp_lead(email: str) -> tuple[str, str]:
    """Descobre a LP de origem do lead e devolve (flow_id, source_com_slug).

    Consulta o WEBSAVE (buscar_lead) para achar o slug da LP; usa products_map
    para escolher o fluxo (parceria vs. nutrição) e registrar o produto certo.
    """
    import products_map
    import re
    slug = ""
    try:
        perfil = websave_mcp.buscar_lead(email)
        # A LP aparece no perfil; tentamos extrair um slug conhecido do mapa.
        low = (perfil or "").lower()
        for known in products_map.LP_MAP:
            if known in low:
                slug = known
                break
    except Exception:  # noqa: BLE001
        pass
    info = products_map.lookup(slug)
    if info["intencao"] == "parceria":
        flow_id = flows.PARCERIA_FLOW_ID
    else:
        flow_id = flows.DEFAULT_FLOW_ID
    source = f"websave_lp:{slug}" if slug else "websave_lp"
    return flow_id, source


def run_intake(daily_cap: int | None = None, dry_run: bool = True) -> dict:
    """Capta leads novos respeitando a prioridade dos tiers e o teto diário.

    Consome Tier 1 → 2 → 3 até atingir o teto de leads novos do dia.
    """
    if not websave_mcp.configured():
        return {"ok": False, "error": "mcp_nao_configurado"}
    flows.ensure_default_flow()

    cap = daily_cap if daily_cap is not None else config.WEBSAVE_DAILY_INTAKE
    ja_hoje = store.intake_today()
    restante = max(0, cap - ja_hoje)
    resumo = {"ok": True, "dry_run": dry_run, "teto_dia": cap,
              "ja_captados_hoje": ja_hoje, "vagas": restante, "tiers": [], "captados": 0}

    if restante <= 0:
        resumo["motivo"] = "teto_diario_atingido"
        return resumo

    total_captados = 0
    for origem, flow_id, label in TIERS:
        if restante <= 0:
            break
        novos = _collect_new(origem, need=restante)
        info = {"tier": label, "origem": origem, "flow_id": flow_id,
                "encontrados_novos": len(novos), "captados": 0,
                "amostra": [l["email"] for l in novos[:5]]}
        if not dry_run:
            for lead in novos:
                # Tier 1 (LP): roteia por LP/intenção (parceria vs. nutrição do produto certo).
                if origem == "lp":
                    fid, src = _route_lp_lead(lead["email"])
                else:
                    fid, src = flow_id, f"websave_{origem}"
                r = flows.ingest_lead(email=lead["email"], name=lead.get("nome", ""),
                                      source=src, flow_id=fid)
                if r.get("enrolled"):
                    info["captados"] += 1
                    total_captados += 1
                    restante -= 1
                    if restante <= 0:
                        break
        else:
            take = min(len(novos), restante)
            info["captados"] = take  # quantos SERIAM captados
            restante -= take
        resumo["tiers"].append(info)

    resumo["captados"] = total_captados if not dry_run else sum(t["captados"] for t in resumo["tiers"])
    if not dry_run:
        log.info("Intake WEBSAVE: %s leads captados (teto %s, já %s)", total_captados, cap, ja_hoje)
    return resumo


# Compat: sync simples de uma origem (mantém o endpoint antigo funcionando).
def sync_leads(origem: str = "lp", max_leads: int = 100, dry_run: bool = True,
               flow_id: str | None = None) -> dict:
    flows.ensure_default_flow()
    flow_id = flow_id or {
        "lp": flows.DEFAULT_FLOW_ID, "quiz": flows.MQL_FLOW_ID,
        "webinario": flows.POSWEBINAR_FLOW_ID,
    }.get(origem, flows.DEFAULT_FLOW_ID)
    novos = _collect_new(origem, need=max_leads)
    enrolled = 0
    if not dry_run:
        for lead in novos:
            r = flows.ingest_lead(email=lead["email"], name=lead.get("nome", ""),
                                  source=f"websave_{origem}", flow_id=flow_id)
            if r.get("enrolled"):
                enrolled += 1
    return {"ok": True, "dry_run": dry_run, "origem": origem, "flow_id": flow_id,
            "novos_encontrados": len(novos), "inscritos": enrolled,
            "seriam_inscritos": len(novos) if dry_run else None,
            "amostra": [l["email"] for l in novos[:10]]}

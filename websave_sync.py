"""Sincroniza leads do WEBSAVE (MCP) para a nutrição da Vanessa.

Puxa os leads capturados no sistema de webinars (LP/quiz/webinário) e os
INSCREVE no fluxo de nutrição — a Vanessa passa a trabalhá-los por e-mail para
descobrir quem tem interesse real nos produtos da Save.

SEGURANÇA (anti-queima de domínio):
- `dry_run=True` por padrão: só mostra o que FARIA, não inscreve nem envia.
- `max_leads` limita o lote (não puxa 8 mil de uma vez).
- A inscrição é idempotente (lead já inscrito não entra de novo).
- O ENVIO em si continua governado pelo motor de fluxos: horário comercial +
  `EMAIL_DAILY_LIMIT`. Ou seja, mesmo inscrevendo 500, sai aos poucos por dia.

Uso típico (via endpoint /websave/sync ou direto):
    preview = sync_leads(origem="lp", max_leads=100, dry_run=True)
    real    = sync_leads(origem="lp", max_leads=100, dry_run=False)
"""
import logging

import websave_mcp
import store
import flows

log = logging.getLogger("websave_sync")


def sync_leads(origem: str = "lp", max_leads: int = 100, dry_run: bool = True,
               flow_id: str | None = None, page_size: int = 50) -> dict:
    """Puxa leads do WEBSAVE e (se dry_run=False) inscreve na nutrição.

    origem: 'lp' | 'quiz' | 'webinario'.
    Retorna um resumo com amostra, total disponível e quantos seriam/foram inscritos.
    """
    if not websave_mcp.configured():
        return {"ok": False, "error": "mcp_nao_configurado"}
    flow_id = flow_id or flows.DEFAULT_FLOW_ID
    flows.ensure_default_flow()

    collected: list[dict] = []
    total = 0
    offset = 0
    seen = set()
    while len(collected) < max_leads:
        page, total = websave_mcp.fetch_leads_page(origem=origem, limit=page_size, offset=offset)
        if not page:
            break
        for lead in page:
            e = lead.get("email", "")
            if e and e not in seen and "@" in e:
                seen.add(e)
                collected.append(lead)
                if len(collected) >= max_leads:
                    break
        offset += page_size
        if offset >= total:
            break

    enrolled = skipped_existing = 0
    if not dry_run:
        for lead in collected:
            r = flows.ingest_lead(
                email=lead["email"], name=lead.get("nome", ""),
                source=f"websave_{origem}", flow_id=flow_id,
            )
            if r.get("enrolled"):
                enrolled += 1
            else:
                skipped_existing += 1
        log.info("Sync WEBSAVE origem=%s: %s inscritos, %s já existentes (de %s)",
                 origem, enrolled, skipped_existing, len(collected))

    return {
        "ok": True,
        "dry_run": dry_run,
        "origem": origem,
        "total_no_websave": total,
        "coletados": len(collected),
        "inscritos": enrolled if not dry_run else 0,
        "ja_existiam": skipped_existing if not dry_run else 0,
        "seriam_inscritos": len(collected) if dry_run else None,
        "amostra": collected[:10],
        "flow_id": flow_id,
    }

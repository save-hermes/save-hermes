"""Mapa das Landing Pages do WEBSAVE -> produto/intenção.

Cada LP roda tráfego para um objetivo diferente. Quando um lead vem de uma LP
(descoberto via websave_mcp.buscar_lead), a Vanessa deve oferecer o PRODUTO CERTO,
não sempre a Pré-Especialização. LPs de captação de parceiro NÃO são venda de curso.

intencao:
  venda_curso   -> nutrir e ofertar o curso/produto indicado
  lead_magnet   -> veio de isca (diagnóstico/aula/semana); aquecer e levar ao produto-âncora
  parceria      -> NÃO ofertar curso; é candidato a parceiro (fluxo/handoff próprio)
  conteudo      -> veio de conteúdo/replay; aquecer para o produto-âncora
"""

# slug da LP (após /lp/) -> config
LP_MAP = {
    "diagnostico-ibs-cbs-escritorios-contabeis": {
        "produto": "Pré-Especialização em Reforma Tributária", "intencao": "lead_magnet"},
    "aula-transacao-tributaria": {
        "produto": "Semana Prática de Transação Tributária", "intencao": "lead_magnet"},
    "semana-pratica-transacao-tributaria": {
        "produto": "Semana Prática de Transação Tributária", "intencao": "venda_curso"},
    "planejamento-tributario-replay": {
        "produto": "Pré-Especialização em Reforma Tributária", "intencao": "conteudo"},
    "papo-estrategista": {
        "produto": "Pré-Especialização em Reforma Tributária", "intencao": "conteudo"},
    "planejamento-tributario": {
        "produto": "Pré-Especialização em Reforma Tributária", "intencao": "conteudo"},
    "pre-especializacao": {
        "produto": "Pré-Especialização em Reforma Tributária", "intencao": "venda_curso"},
    "passaporte-tributario": {
        "produto": "Passaporte Tributário", "intencao": "venda_curso"},
    "combo-pos": {
        "produto": "Combo 2 Pós-Graduações (Direito Tributário + Recuperação de Créditos)",
        "intencao": "venda_curso"},
    # Captação de PARCEIROS — não é venda de curso.
    "save-partners": {"produto": "Programa de Parceiros Save", "intencao": "parceria"},
    "saveid-parceiro": {"produto": "Save ID — Parceiro Certificador", "intencao": "parceria"},
}

# Produto-âncora quando não há mapeamento específico.
PRODUTO_ANCORA = "Pré-Especialização em Reforma Tributária"


def lookup(lp_slug: str) -> dict:
    """Devolve {produto, intencao} para um slug de LP (ou o âncora, venda_curso)."""
    if not lp_slug:
        return {"produto": PRODUTO_ANCORA, "intencao": "venda_curso"}
    key = lp_slug.strip().lower().lstrip("/").removeprefix("lp/")
    return LP_MAP.get(key, {"produto": PRODUTO_ANCORA, "intencao": "venda_curso"})

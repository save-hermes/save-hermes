"""
knowledge.py — Base de conhecimento de produtos (vault Obsidian).

A Vanessa NUNCA responde dado factual de produto (preço, garantia, módulos,
formato, carga horária, certificação) de memória. Antes de responder, ela
consulta as notas da pasta "Produtos da save Educação" do vault. Este módulo lê
essas notas em tempo de requisição (com cache por data de modificação, então
editar uma nota reflete sem reiniciar o servidor) e as entrega para o prompt.

Se a pasta/nota não existir, degrada com segurança: retorna vazio e o prompt
instrui a Vanessa a dizer que vai confirmar, em vez de inventar.
"""
import logging
import os
from pathlib import Path

log = logging.getLogger("knowledge")

# Pasta das notas de produto. Configurável por env (KB_DIR). Default: vault local.
KB_DIR = os.getenv(
    "KB_DIR",
    r"C:\Users\mkt\Documents\Hermes Brain\Produtos da save Educação",
).strip()

_cache = {"sig": None, "text": "", "titles": []}


def _scan() -> list[Path]:
    d = Path(KB_DIR)
    if not d.is_dir():
        return []
    return sorted(d.glob("*.md"))


def _signature(files: list[Path]) -> tuple:
    # Assinatura = nome + mtime + tamanho de cada arquivo. Muda se editar/incluir.
    return tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in files)


def load() -> dict:
    """Retorna {'text': <base concatenada>, 'titles': [...], 'available': bool}.

    Relê do disco só quando algum arquivo muda (cache por assinatura).
    """
    files = _scan()
    if not files:
        _cache.update(sig=None, text="", titles=[])
        return {"text": "", "titles": [], "available": False}

    sig = _signature(files)
    if sig != _cache["sig"]:
        blocks, titles = [], []
        for f in files:
            try:
                content = f.read_text(encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                log.warning("Falha ao ler nota %s: %s", f.name, e)
                continue
            title = f.stem
            titles.append(title)
            blocks.append(f"===== PRODUTO: {title} =====\n{content}")
        _cache.update(sig=sig, text="\n\n".join(blocks), titles=titles)
        log.info("Base de conhecimento recarregada: %d nota(s) -> %s", len(titles), ", ".join(titles))

    return {"text": _cache["text"], "titles": list(_cache["titles"]), "available": bool(_cache["text"])}


def status() -> dict:
    """Resumo para o health check."""
    data = load()
    return {
        "kb_dir": KB_DIR,
        "available": data["available"],
        "produtos": data["titles"],
    }

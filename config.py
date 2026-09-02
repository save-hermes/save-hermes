"""Configuração central — lê tudo do ambiente (.env no Easypanel)."""
import os


def _clean_url(u: str) -> str:
    return (u or "").strip().rstrip("/")


# Evolution
EVOLUTION_URL = _clean_url(os.getenv("EVOLUTION_URL", ""))
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "").strip()
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "").strip()

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514").strip()
ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "1024"))

# Segurança
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "").strip()

# Comportamento
AGENT_NAME = os.getenv("AGENT_NAME", "Vanessa").strip()
OWNER_NOTIFY_NUMBER = os.getenv("OWNER_NOTIFY_NUMBER", "").strip()
SEND_DELAY_MS = int(os.getenv("SEND_DELAY_MS", "1200"))
DB_PATH = os.getenv("DB_PATH", "/data/leads.db").strip()
# Link de checkout/pagamento do curso (para a IA fechar a venda). Se vazio, a IA
# faz handoff quando o lead quiser pagar.
CHECKOUT_URL = os.getenv("CHECKOUT_URL", "").strip()

# Marcador que o modelo emite quando quer passar a conversa para um humano
HANDOFF_MARKER = "[[HANDOFF]]"


def validate() -> list[str]:
    """Retorna lista de variáveis obrigatórias que faltam."""
    missing = []
    if not EVOLUTION_URL:
        missing.append("EVOLUTION_URL")
    if not EVOLUTION_INSTANCE:
        missing.append("EVOLUTION_INSTANCE")
    if not EVOLUTION_API_KEY:
        missing.append("EVOLUTION_API_KEY")
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not WEBHOOK_TOKEN:
        missing.append("WEBHOOK_TOKEN")
    return missing

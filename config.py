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
# Número do administrador/superior. SÓ este número pode ajustar comportamento,
# tom, regras ou discutir a configuração interna do agente. Qualquer outro número
# é tratado exclusivamente como atendimento (lead/cliente/aluno), mesmo que alegue
# ser admin/dono/dev. Formato internacional só dígitos (ex.: 5547996810630).
ADMIN_NUMBER = os.getenv("ADMIN_NUMBER", "").strip()
SEND_DELAY_MS = int(os.getenv("SEND_DELAY_MS", "1200"))
DB_PATH = os.getenv("DB_PATH", "/data/leads.db").strip()

# === Aquecimento (warming) — reduz risco de ban do número ===
# Limite de mensagens que a Vanessa envia por dia. Comece BAIXO num número novo
# (ex.: 30) e suba gradualmente ao longo de semanas. 0 = sem limite.
DAILY_SEND_LIMIT = int(os.getenv("DAILY_SEND_LIMIT", "40"))
# Delay aleatório extra (ms) antes de enviar, além do SEND_DELAY_MS, para o ritmo
# parecer humano (não responder sempre no mesmo tempo exato).
SEND_JITTER_MIN_MS = int(os.getenv("SEND_JITTER_MIN_MS", "800"))
SEND_JITTER_MAX_MS = int(os.getenv("SEND_JITTER_MAX_MS", "3500"))
# Link de checkout/pagamento do curso (para a IA fechar a venda). Se vazio, a IA
# faz handoff quando o lead quiser pagar.
CHECKOUT_URL = os.getenv("CHECKOUT_URL", "").strip()

# Marcador que o modelo emite quando quer passar a conversa para um humano
HANDOFF_MARKER = "[[HANDOFF]]"

# === Instagram (Meta Graph API) ===
# Token de acesso de longa duração (Page/IG). Cole no ambiente, nunca no código.
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN", "").strip()
# ID da conta do Instagram Business (IG User ID) — numérico.
IG_USER_ID = os.getenv("IG_USER_ID", "").strip()
# Token de verificação do webhook (VOCÊ inventa; a Meta ecoa no handshake GET).
IG_VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN", "").strip()
# App Secret da Meta — usado para validar a assinatura X-Hub-Signature-256.
IG_APP_SECRET = os.getenv("IG_APP_SECRET", "").strip()
# Versão da Graph API.
IG_GRAPH_VERSION = os.getenv("IG_GRAPH_VERSION", "v23.0").strip()
# Se True, ao receber um comentário a Vanessa também manda um DM privado (private
# reply) além (ou em vez) de responder publicamente. Ver IG_COMMENT_MODE.
# Modos: "public" (só responde no comentário), "dm" (só private reply),
#        "both" (responde curtinho no comentário E manda DM com o detalhe).
IG_COMMENT_MODE = os.getenv("IG_COMMENT_MODE", "both").strip()

# === E-mail (Google Workspace via SMTP/IMAP) ===
# Endereço que a Vanessa usa para enviar/receber (ex.: vanessa@saveeducacao.com.br).
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "").strip()
# Nome exibido no "De:" (From). Ex.: "Vanessa | Save Educação".
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", f"{AGENT_NAME} | Save Educação").strip()
# Senha de App do Google (16 caracteres, gerada em myaccount.google.com/apppasswords).
# NÃO é a senha normal da conta. Exige verificação em 2 etapas ativada.
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "").strip()
# Servidores (padrões do Google Workspace / Gmail).
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com").strip()
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
# Assinatura anexada ao final dos e-mails da Vanessa (texto puro).
EMAIL_SIGNATURE = os.getenv(
    "EMAIL_SIGNATURE",
    f"{AGENT_NAME}\nSave Educação",
).strip()
# Limite diário de e-mails enviados (deliverability/anti-spam). 0 = sem limite.
EMAIL_DAILY_LIMIT = int(os.getenv("EMAIL_DAILY_LIMIT", "50"))

# === Resend (provedor de ENVIO de e-mail — opcional) ===
# Se RESEND_API_KEY estiver preenchida, o envio usa a API do Resend (deliverability
# alta + logs de entrega/abertura). Caso contrário, cai no SMTP da caixa (híbrido:
# a LEITURA continua sempre por IMAP). Chave em resend.com/api-keys.
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
# Remetente usado no Resend (precisa ser de um domínio verificado no Resend).
# Se vazio, usa EMAIL_ADDRESS. Ex.: "Vanessa | Save Educação <vanessa@saveeducacao.com.br>".
RESEND_FROM = os.getenv("RESEND_FROM", "").strip()
# Signing secret do webhook do Resend (começa com "whsec_"). Valida a assinatura
# Svix dos eventos (entregue/aberto/clicado/bounce/reclamação). resend.com/webhooks
RESEND_WEBHOOK_SECRET = os.getenv("RESEND_WEBHOOK_SECRET", "").strip()


def email_send_provider() -> str:
    """Qual provedor de envio está ativo agora: 'resend' se houver chave, senão 'smtp'."""
    return "resend" if RESEND_API_KEY else "smtp"

# === WEBSAVE MCP (CRM/leads do sistema de webinars) ===
# Endpoint do MCP interno do WEBSAVE (Streamable HTTP). Barra final é obrigatória.
WEBSAVE_MCP_URL = os.getenv(
    "WEBSAVE_MCP_URL",
    "https://webnairs.saveeducacao.com.br/api/internal/mcp/vanessa/",
).strip()
# Token do MCP (guardado no app_settings do WEBSAVE como mcp_vanessa_token).
WEBSAVE_MCP_TOKEN = os.getenv("WEBSAVE_MCP_TOKEN", "").strip()

# === Follow-up (cadência de acompanhamento) ===
# Ativa/desativa o motor de follow-up.
FOLLOWUP_ENABLED = os.getenv("FOLLOWUP_ENABLED", "true").strip().lower() in ("1", "true", "yes", "sim")
# Cadência clássica: horas após o ÚLTIMO contato sem resposta para cada toque.
# Estágio 0 -> 1 (24h), 1 -> 2 (72h = dia 3), 2 -> 3 (168h = dia 7). Depois para.
FOLLOWUP_HOURS = os.getenv("FOLLOWUP_HOURS", "24,72,168").strip()
# Só dispara follow-up dentro do horário comercial (evita mandar de madrugada).
FOLLOWUP_HOUR_START = int(os.getenv("FOLLOWUP_HOUR_START", "9"))   # 09h
FOLLOWUP_HOUR_END = int(os.getenv("FOLLOWUP_HOUR_END", "20"))      # 20h


def _digits(n: str) -> str:
    return "".join(ch for ch in (n or "") if ch.isdigit())


def _br_variants(digits: str) -> set[str]:
    """Gera variantes de um número BR com/sem o 9º dígito do celular.

    Ex.: 5547996810630 <-> 554796810630. Cobre a divergência comum entre
    como o número é cadastrado e como a Evolution/WhatsApp entrega o remoteJid.
    """
    out = {digits}
    # Formato: 55 (país) + DD (área, 2) + assinante
    if digits.startswith("55") and len(digits) >= 12:
        cc, ddd, rest = digits[:2], digits[2:4], digits[4:]
        if len(rest) == 9 and rest.startswith("9"):
            out.add(cc + ddd + rest[1:])      # remove o 9 extra
        elif len(rest) == 8:
            out.add(cc + ddd + "9" + rest)    # adiciona o 9 extra
    return out


def is_admin_number(number: str) -> bool:
    """True somente se `number` for o ADMIN_NUMBER (comparação por dígitos,
    tolerante ao 9º dígito). Nunca confia em texto/alegação da mensagem."""
    if not ADMIN_NUMBER:
        return False
    a = _digits(number)
    b = _digits(ADMIN_NUMBER)
    if not a or not b:
        return False
    return bool(_br_variants(a) & _br_variants(b))


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

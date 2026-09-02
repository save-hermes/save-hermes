"""Cliente de e-mail da Vanessa: envia (SMTP) e lê (IMAP) via Google Workspace.

Autenticação por Senha de App do Google (config.EMAIL_APP_PASSWORD), que exige
verificação em 2 etapas ativada na conta. Nada de OAuth aqui — a senha de app é
o caminho simples e estável para SMTP/IMAP.
"""
import email
import imaplib
import logging
import smtplib
import ssl
import time
from email.header import decode_header, make_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid, parseaddr

import config

log = logging.getLogger("email_client")


def configured() -> bool:
    return bool(config.EMAIL_ADDRESS and config.EMAIL_APP_PASSWORD)


# ─────────────────────────── Envio (SMTP) ───────────────────────────

def send(
    to_addr: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> dict:
    """Envia um e-mail de texto. Devolve {ok, message_id, error}.

    in_reply_to/references mantêm o threading quando é uma RESPOSTA a um e-mail
    existente (o cliente do lead agrupa na mesma conversa).
    """
    if not configured():
        return {"ok": False, "error": "email_not_configured"}
    if not to_addr:
        return {"ok": False, "error": "no_recipient"}

    # Anexa a assinatura, se ainda não estiver no corpo.
    full_body = body.rstrip()
    if config.EMAIL_SIGNATURE and config.EMAIL_SIGNATURE not in full_body:
        full_body = f"{full_body}\n\n{config.EMAIL_SIGNATURE}"

    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((config.EMAIL_FROM_NAME, config.EMAIL_ADDRESS))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg_id = make_msgid(domain=config.EMAIL_ADDRESS.split("@")[-1] or None)
    msg["Message-ID"] = msg_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = (references + " " if references else "") + in_reply_to
    msg.attach(MIMEText(full_body, "plain", "utf-8"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.login(config.EMAIL_ADDRESS, config.EMAIL_APP_PASSWORD)
            s.sendmail(config.EMAIL_ADDRESS, [to_addr], msg.as_string())
        log.info("E-mail enviado para %s (subj=%r)", to_addr, subject)
        return {"ok": True, "message_id": msg_id}
    except Exception as e:  # noqa: BLE001
        log.error("Falha ao enviar e-mail para %s: %s", to_addr, e)
        return {"ok": False, "error": str(e)}


# ─────────────────────────── Leitura (IMAP) ───────────────────────────

def _decode(s) -> str:
    if not s:
        return ""
    try:
        return str(make_header(decode_header(s)))
    except Exception:  # noqa: BLE001
        return str(s)


def _extract_body(msg) -> str:
    """Extrai o texto plano do e-mail (ignora anexos; cai para HTML se preciso)."""
    if msg.is_multipart():
        # Preferir text/plain
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ctype == "text/plain" and "attachment" not in disp:
                return _payload_text(part)
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return _strip_html(_payload_text(part))
        return ""
    return _payload_text(msg)


def _payload_text(part) -> str:
    try:
        raw = part.get_payload(decode=True)
        if raw is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def _strip_html(html: str) -> str:
    import re
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _quote_stripped(body: str) -> str:
    """Remove a parte citada (histórico) de uma resposta, ficando só o texto novo."""
    import re
    lines = body.splitlines()
    out = []
    for ln in lines:
        # Linhas típicas de início de citação
        if re.match(r"^\s*>", ln):
            break
        if re.match(r"(?i)^\s*(em .*escreveu:|on .*wrote:|-{2,} ?forwarded|de:\s|from:\s)", ln):
            break
        out.append(ln)
    return "\n".join(out).strip() or body.strip()


def fetch_unseen(limit: int = 20) -> list[dict]:
    """Lê e-mails NÃO lidos do INBOX e os marca como lidos.

    Devolve lista de dicts: from_addr, from_name, subject, body (texto novo,
    sem citação), message_id, in_reply_to, references, uid, ts.
    """
    if not configured():
        return []
    out: list[dict] = []
    try:
        M = imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT)
        M.login(config.EMAIL_ADDRESS, config.EMAIL_APP_PASSWORD)
        M.select("INBOX")
        typ, data = M.search(None, "UNSEEN")
        if typ != "OK":
            M.logout()
            return []
        ids = data[0].split()
        for num in ids[:limit]:
            typ, msg_data = M.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            from_name, from_addr = parseaddr(_decode(msg.get("From")))
            body = _quote_stripped(_extract_body(msg))
            out.append({
                "uid": num.decode() if isinstance(num, bytes) else str(num),
                "from_addr": (from_addr or "").strip().lower(),
                "from_name": from_name or "",
                "subject": _decode(msg.get("Subject")),
                "body": body,
                "message_id": (msg.get("Message-ID") or "").strip(),
                "in_reply_to": (msg.get("In-Reply-To") or "").strip(),
                "references": (msg.get("References") or "").strip(),
                "ts": int(time.time()),
            })
            # Marca como lido (evita reprocessar).
            M.store(num, "+FLAGS", "\\Seen")
        M.logout()
    except Exception as e:  # noqa: BLE001
        log.error("Falha ao ler IMAP: %s", e)
    return out


def check_connection() -> dict:
    """Testa login SMTP e IMAP. Usado por diagnósticos/health."""
    result = {"smtp": False, "imap": False, "error": None}
    if not configured():
        result["error"] = "email_not_configured"
        return result
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            s.ehlo(); s.starttls(context=ctx)
            s.login(config.EMAIL_ADDRESS, config.EMAIL_APP_PASSWORD)
        result["smtp"] = True
    except Exception as e:  # noqa: BLE001
        result["error"] = f"smtp: {e}"
    try:
        M = imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT)
        M.login(config.EMAIL_ADDRESS, config.EMAIL_APP_PASSWORD)
        M.select("INBOX")
        M.logout()
        result["imap"] = True
    except Exception as e:  # noqa: BLE001
        result["error"] = (result["error"] + " | " if result["error"] else "") + f"imap: {e}"
    return result

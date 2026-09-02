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
    # Envio: Resend (chave) OU SMTP (caixa). Leitura: sempre IMAP (caixa).
    has_send = bool(config.RESEND_API_KEY) or bool(config.EMAIL_ADDRESS and config.EMAIL_APP_PASSWORD)
    return bool(config.EMAIL_ADDRESS) and has_send


# ─────────────────────────── Envio (roteia Resend/SMTP) ───────────────────────────

def send(
    to_addr: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    references: str | None = None,
    lead_name: str = "",
    html: bool | None = None,
) -> dict:
    """Envia um e-mail. Usa Resend se houver RESEND_API_KEY, senão SMTP.

    Se config.EMAIL_HTML (ou html=True), embrulha o corpo no template branded da
    Save e envia multipart (HTML + texto). in_reply_to/references mantêm o
    threading quando é RESPOSTA a um e-mail existente.
    """
    if not to_addr:
        return {"ok": False, "error": "no_recipient"}

    # Anexa a assinatura ao TEXTO puro, se ainda não estiver.
    full_body = body.rstrip()
    if config.EMAIL_SIGNATURE and config.EMAIL_SIGNATURE not in full_body:
        full_body = f"{full_body}\n\n{config.EMAIL_SIGNATURE}"

    # Gera a versão HTML branded (usada quando habilitado).
    use_html = config.EMAIL_HTML if html is None else html
    html_body = None
    if use_html:
        try:
            import email_template
            html_body = email_template.render(body, subject=subject, lead_name=lead_name)
        except Exception as e:  # noqa: BLE001
            log.warning("Falha ao renderizar HTML, caindo p/ texto: %s", e)
            html_body = None

    if config.RESEND_API_KEY:
        return _send_resend(to_addr, subject, full_body, in_reply_to, references, html_body)
    return _send_smtp(to_addr, subject, full_body, in_reply_to, references, html_body)


def _send_resend(to_addr, subject, full_body, in_reply_to, references, html_body=None) -> dict:
    """Envio via API do Resend (HTTP). Deliverability alta + logs no painel Resend."""
    import httpx
    frm = config.RESEND_FROM or formataddr((config.EMAIL_FROM_NAME, config.EMAIL_ADDRESS))
    payload = {
        "from": frm,
        "to": [to_addr],
        "subject": subject,
        "text": full_body,
    }
    if html_body:
        payload["html"] = html_body
    headers = {}
    if in_reply_to:
        headers["In-Reply-To"] = in_reply_to
        headers["References"] = (references + " " if references else "") + in_reply_to
    if headers:
        payload["headers"] = headers
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {config.RESEND_API_KEY}",
                     "Content-Type": "application/json"},
            json=payload, timeout=30,
        )
        if r.status_code >= 300:
            log.error("Resend recusou (%s): %s", r.status_code, r.text[:200])
            return {"ok": False, "error": f"resend_{r.status_code}: {r.text[:150]}"}
        data = r.json()
        log.info("E-mail enviado via Resend para %s (id=%s)", to_addr, data.get("id"))
        return {"ok": True, "message_id": data.get("id"), "provider": "resend"}
    except Exception as e:  # noqa: BLE001
        log.error("Falha Resend para %s: %s", to_addr, e)
        return {"ok": False, "error": f"resend: {e}"}


def _send_smtp(to_addr, subject, full_body, in_reply_to, references, html_body=None) -> dict:
    """Envio via SMTP da caixa do domínio (fallback quando não há Resend)."""
    if not (config.EMAIL_ADDRESS and config.EMAIL_APP_PASSWORD):
        return {"ok": False, "error": "email_not_configured"}
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
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.login(config.EMAIL_ADDRESS, config.EMAIL_APP_PASSWORD)
            s.sendmail(config.EMAIL_ADDRESS, [to_addr], msg.as_string())
        log.info("E-mail enviado via SMTP para %s (subj=%r)", to_addr, subject)
        return {"ok": True, "message_id": msg_id, "provider": "smtp"}
    except Exception as e:  # noqa: BLE001
        log.error("Falha SMTP para %s: %s", to_addr, e)
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

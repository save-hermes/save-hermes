"""Template HTML de e-mail com a identidade visual da Save Educação.

A Vanessa gera o CORPO em texto (com a persona); este módulo embrulha esse texto
num HTML responsivo e branded (header com gradiente + logo, corpo formatado, CTA,
rodapé com suporte e descadastro). O e-mail é enviado como multipart: text + HTML.

Uso: html = render(body_text, subject, lead_name=..., unsubscribe_url=...)
"""
import html as _html
import re

import config

# Paleta Save (do material de referência).
_INK = "#0F1820"
_INK2 = "#22344A"
_ACCENT = "#4B79A1"
_BG = "#EAEEEF"
_TEXT = "#374151"

_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_URL = re.compile(r"(https?://[^\s<>\")]+)")
_CHECKOUT_HINT = re.compile(r"(checkout|/pay/|matricul|inscri|comprar|adquirir)", re.I)


def _esc(s: str) -> str:
    return _html.escape(s or "", quote=False)


def _inline_format(text: str) -> str:
    """Escapa, aplica **negrito** -> <strong> e transforma URLs em links."""
    out = _esc(text)
    out = _MD_BOLD.sub(rf'<strong style="color:{_INK}">\1</strong>', out)
    out = _URL.sub(r'<a href="\1" style="color:%s;text-decoration:underline">\1</a>' % _ACCENT, out)
    return out


def _extract_cta(body: str) -> tuple[str, str | None]:
    """Se houver um link de checkout no corpo, remove-o e devolve como CTA (botão)."""
    cta_url = None
    for m in _URL.finditer(body):
        if _CHECKOUT_HINT.search(m.group(1)):
            cta_url = m.group(1)
            break
    if cta_url:
        # tira a linha do link (evita duplicar link + botão)
        body = "\n".join(l for l in body.splitlines() if cta_url not in l).strip()
    return body, cta_url


def _paragraphs(body: str) -> str:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]
    out = []
    for b in blocks:
        inner = _inline_format(b).replace("\n", "<br>")
        out.append(
            f'<p style="color:{_TEXT};font-size:15px;line-height:1.7;margin:0 0 18px 0">{inner}</p>'
        )
    return "\n".join(out)


def render(body_text: str, subject: str = "", lead_name: str = "",
           unsubscribe_url: str = "", eyebrow: str = "Save Educação") -> str:
    """Devolve o HTML completo do e-mail branded."""
    # separa CTA (checkout) do corpo, se houver
    body_text = (body_text or "").strip()
    # remove assinatura de texto puro (o rodapé HTML já assina)
    if config.EMAIL_SIGNATURE and config.EMAIL_SIGNATURE in body_text:
        body_text = body_text.replace(config.EMAIL_SIGNATURE, "").strip()
    body_wo_cta, cta_url = _extract_cta(body_text)
    corpo = _paragraphs(body_wo_cta)

    logo = config.EMAIL_LOGO_URL
    logo_html = (
        f'<img src="{logo}" alt="Save Educação" width="200" '
        f'style="display:inline-block;max-width:200px;height:auto;border:0;margin:0 auto 16px auto" />'
        if logo else
        f'<div style="color:#fff;font-size:22px;font-weight:800;letter-spacing:.02em;margin-bottom:12px">'
        f'Save Educação</div>'
    )
    cta_html = ""
    if cta_url:
        cta_html = f"""
      <div style="text-align:center;margin:28px 0 4px 0">
        <a href="{cta_url}" style="display:inline-block;background:linear-gradient(135deg,{_INK},{_INK2});color:#fff;padding:15px 34px;border-radius:10px;text-decoration:none;font-size:15px;font-weight:700;box-shadow:0 4px 12px rgba(15,24,32,.25)">Quero garantir minha vaga →</a>
      </div>"""

    unsub = ""
    if unsubscribe_url:
        unsub = (f'<p style="color:#CBD5E1;font-size:10px;margin:10px 0 0 0">'
                 f'Não quer mais receber? <a href="{unsubscribe_url}" style="color:#94A3B8">Descadastrar</a>.</p>')

    saud = f'<p style="color:{_INK};font-size:16px;line-height:1.7;margin:0 0 18px 0">Olá, <strong>{_esc(lead_name)}</strong>!</p>' if lead_name else ""

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{_esc(subject)}</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;margin:0;padding:0;background:{_BG}">
<div style="max-width:600px;margin:0 auto;padding:24px 16px">
  <div style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 16px rgba(15,24,32,.12)">
    <div style="background:linear-gradient(135deg,{_INK} 0%,#1E2D3D 60%,{_ACCENT} 100%);padding:32px 28px;text-align:center">
      {logo_html}
      <p style="color:#86EFAC;font-size:11px;font-weight:700;letter-spacing:.18em;text-transform:uppercase;margin:0">{_esc(eyebrow)}</p>
    </div>
    <div style="padding:34px 28px">
      {saud}
      {corpo}
      {cta_html}
    </div>
    <div style="height:1px;background:linear-gradient(90deg,transparent,#E2E8F0,transparent);margin:0 28px"></div>
    <div style="background:#F8FAFC;padding:22px 28px;text-align:center">
      <p style="color:{_TEXT};font-size:13px;margin:0 0 6px 0;font-weight:600">{_esc(config.EMAIL_FROM_NAME)}</p>
      <a href="{config.EMAIL_SUPPORT_URL}" style="color:{_ACCENT};font-size:13px;text-decoration:underline;font-weight:600">Falar com o Suporte Save Educação →</a>
      <p style="color:#94A3B8;font-size:11px;margin:14px 0 0 0">© 2026 Save Educação</p>
      {unsub}
    </div>
  </div>
</div></body></html>"""

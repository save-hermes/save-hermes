# 🚀 Vanessa — Guia Operacional

Como subir, operar e finalizar a configuração da Vanessa (agente de IA da Save
Educação nos canais digitais). Este arquivo é o ponto de partida único.

Escopo completo e decisões: veja no Obsidian
`20 - Projetos/Vanessa - Escopo, Canais e Operação`.

---

## ▶️ Subir tudo (1 comando)

```bash
python run_all.py
```
Sobe, no mesmo `.env` e banco:
- **Agente** (webhooks WhatsApp/Instagram/Resend + e-mail) → http://127.0.0.1:8000/
- **Worker** de e-mail + follow-up (lê a caixa, dispara a cadência)
- **Painel/CRM** (Stripe) → http://127.0.0.1:8777/

`Ctrl+C` encerra todos. Se uma porta estiver ocupada, feche o processo antigo
(o `run_all` derruba os demais de propósito — fail-fast).

Rodar isolado, se precisar:
```bash
python run_local.py       # só o agente
python email_worker.py    # só o worker de e-mail/follow-up
python run_dashboard.py   # só o painel
```

---

## 🩺 Verificar saúde

`GET http://127.0.0.1:8000/` mostra tudo:
```json
{
  "whatsapp":  {"instance": {"state": "open|close"}},
  "knowledge_base": {"available": true, "produtos": [...]},
  "instagram": {"configured": true, "comment_mode": "both"},
  "email":     {"configured": true, "send_provider": "resend", "sent_today": N},
  "followup":  {"enabled": true, "hours": "24,72,168", "due_now": N}
}
```

---

## 📡 Canais e estados (02/09/2026)

| Canal | Estado | O que falta |
|---|---|---|
| WhatsApp (Evolution + extensão) | ✅ pronto | número reconectar (`state: open`) |
| Instagram (DM + comentários) | 🟡 código pronto | **App Review** da Meta (botão destrava ~24h) |
| E-mail 1:1 (enviar/ler/responder) | ✅ funcionando | — |
| Follow-up (WhatsApp + e-mail) | ✅ funcionando | — |
| CRM + Painel (Stripe) | ✅ funcionando | — |
| Envio via Resend | ✅ enviando | — |
| Métricas (webhook Resend) | ✅ código pronto | cadastrar URL + `RESEND_WEBHOOK_SECRET` |

---

## ✅ O que SÓ VOCÊ pode concluir (checklist)

1. **WhatsApp** — reconectar o número na instância `Vanessa` (Evolution) até
   `state: open`. Depois é automático.
2. **Instagram / App Review** — quando o botão "Solicitar acesso avançado"
   destravar (~24h após a chamada de teste), submeter usando as justificativas
   já prontas em `APP_REVIEW_INSTAGRAM.md` + gravar o vídeo screencast.
3. **Resend / métricas** — no painel do Resend → Webhooks → Add Webhook:
   - URL: `https://SEU_DOMINIO_PUBLICO/resend/webhook`
   - Eventos: `email.delivered`, `email.opened`, `email.clicked`,
     `email.bounced`, `email.complained`
   - Copiar o **Signing Secret** (`whsec_...`) → colocar em `RESEND_WEBHOOK_SECRET` no `.env`.
4. **Segurança (higiene)** — rotacionar credenciais que passaram pelo chat:
   `RESEND_API_KEY` e a senha da caixa `vanessa@` (opcional, mas recomendado).
5. **Deploy 24/7** (produção) — subir num servidor (Easypanel/VPS) com URL pública,
   para não depender do PC ligado + túnel temporário. Aí os webhooks (Instagram e
   Resend) usam o domínio fixo em vez do túnel.

---

## 🧪 Testes

```bash
python test_email_followup.py   # 16 testes: e-mail, follow-up, opt-out, limite, métricas
python test_e2e.py              # 9 testes: WhatsApp (admin, injeção, grupos, handoff)
```

---

## 📤 Prospecção e ações por API (protegidas por ?token=WEBHOOK_TOKEN)

```
POST /email/outreach   {"to":"lead@x.com","name":"Ana","seed":"veio do anúncio"}
POST /email/poll        # lê a caixa uma vez
POST /followup/run      # dispara follow-ups vencidos agora
```

---

## 📚 Documentos do projeto

- `EMAIL_FOLLOWUP.md` — e-mail + cadência de follow-up.
- `APP_REVIEW_INSTAGRAM.md` — submissão do App Review (justificativas + vídeo).
- `VERIFICACAO_NEGOCIOS.md` — verificação Meta (já feita).
- `INSTAGRAM.md`, `WARMING.md` — canal Instagram e aquecimento anti-ban.

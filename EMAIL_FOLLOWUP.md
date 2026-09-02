# 📧 E-mail + Follow-up da Vanessa

A Vanessa agora também **envia e-mail para leads**, **lê e responde e-mails** e faz
**follow-up automático** (acompanha quem não respondeu) tanto no **WhatsApp** quanto
por **e-mail**. Reaproveita o mesmo cérebro (Claude + persona + base de conhecimento).

---

## 1) O que você precisa configurar (Google Workspace)

A conexão SMTP/IMAP usa uma **Senha de App** do Google (não a senha normal).

1. Escolha o endereço da Vanessa (ex.: `vanessa@saveeducacao.com.br`).
2. Nessa conta, ative a **Verificação em 2 etapas**:
   → myaccount.google.com/security → "Verificação em duas etapas".
3. Gere a **Senha de App** (16 caracteres):
   → myaccount.google.com/apppasswords → nomeie "Vanessa" → copie a senha.
4. Confirme que o **IMAP está ativado** no Gmail:
   → Gmail → ⚙️ → Ver todas as configurações → "Encaminhamento e POP/IMAP" →
   "Ativar IMAP" → Salvar.
5. Preencha no `.env` (nunca no código):
   ```
   EMAIL_ADDRESS=vanessa@saveeducacao.com.br
   EMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx   # a senha de app de 16 chars
   EMAIL_FROM_NAME=Vanessa | Save Educação
   ```
   Os servidores (`smtp.gmail.com:587`, `imap.gmail.com:993`) já vêm como padrão.

Teste a conexão:
```bash
python -c "import email_client, json; print(json.dumps(email_client.check_connection()))"
# esperado: {"smtp": true, "imap": true, "error": null}
```

---

## 2) Como funciona

### Ler e responder e-mail
O `email_worker.py` roda um loop que lê a caixa (IMAP), gera a resposta da Vanessa
no **canal `email`** (formato de e-mail, não de chat) e responde **na mesma thread**
(`Re: assunto`, com `In-Reply-To`). Idempotente por `Message-ID`.

### Prospecção (1º toque)
```bash
curl -X POST "http://SEU_HOST/email/outreach?token=SEU_WEBHOOK_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"to":"lead@x.com","name":"Ana","seed":"veio do anúncio de Reforma Tributária"}'
```
Envia o primeiro e-mail e **já agenda o follow-up**.

### Follow-up automático (cadência clássica)
Régua a partir do último contato **sem resposta**:
- **Dia 1** (24h) → 1º follow-up
- **Dia 3** (72h) → 2º
- **Dia 7** (168h) → último; depois **para**.

Regras:
- Vale para **WhatsApp e e-mail** (usa o canal principal do lead).
- Se o lead **responder** a qualquer momento, a régua **zera** (não recebe cobrança).
- **Opt-out**: quem pede para parar nunca mais recebe follow-up.
- Só dispara em **horário comercial** (`FOLLOWUP_HOUR_START`..`END`, padrão 9h–20h).
- Configurável: `FOLLOWUP_HOURS=24,72,168` (mude os intervalos como quiser).

---

## 3) Como rodar o worker

O servidor web (`app.py`) trata WhatsApp/Instagram. O e-mail + follow-up rodam
num **processo separado** (loop), ou por **cron** batendo nos endpoints.

**Opção A — loop dedicado (recomendado):**
```bash
python email_worker.py            # lê caixa + roda follow-ups a cada 60s
WORKER_INTERVAL_S=120 python email_worker.py   # intervalo custom
```

**Opção B — cron externo batendo nos endpoints (todos exigem ?token=):**
```
POST /email/poll?token=...     # lê a caixa uma vez
POST /followup/run?token=...   # dispara follow-ups vencidos
POST /email/outreach?token=... # inicia prospecção (body: to/name/seed)
```

Deploy: no Easypanel, suba **um segundo serviço** com o mesmo código e comando
`python email_worker.py` (compartilhando o mesmo volume `/data/leads.db`).

---

## 4) Freios (deliverability / anti-spam)

- `EMAIL_DAILY_LIMIT=50` — teto de e-mails/dia. Comece BAIXO em domínio novo.
- E-mail em massa pra lista fria tem risco de spam/bloqueio de domínio (análogo ao
  ban do WhatsApp). Cuidados: SPF/DKIM/DMARC no domínio (o Workspace já ajuda),
  volume gradual, conteúdo relevante, sempre com opção de sair.

---

## 5) Health check

`GET /` agora inclui:
```json
{
  "email":    {"configured": true, "address": "vanessa@...", "sent_today": 3, "daily_limit": 50},
  "followup": {"enabled": true, "hours": "24,72,168", "due_now": 2}
}
```

## 6) Testes
```bash
python test_email_followup.py    # 16 testes: prospecção, thread, cadência, opt-out, limite
```

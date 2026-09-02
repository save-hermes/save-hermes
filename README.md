# 🤖 WhatsApp Sales Agent

Agente de vendas com IA (Claude) que atende leads no WhatsApp via Evolution API v2.
Recebe mensagens por webhook, responde seguindo um playbook de vendas com guardrails,
registra cada lead num banco SQLite e avisa você quando um lead fica "quente".

## Arquitetura

```
Lead no WhatsApp → Evolution API (messages.upsert)
   → POST /webhook?token=... (este serviço)
   → Claude (persona + playbook)
   → resposta enviada pela Evolution
   → estado do lead gravado no SQLite
   → se handoff: avisa o dono
```

## Arquivos

| Arquivo | Função |
|---|---|
| `app.py` | Servidor FastAPI + webhook (o orquestrador) |
| `brain.py` | Chamada ao Claude |
| `playbook.py` | **Persona, oferta, roteiro e guardrails** (edite aqui!) |
| `evolution.py` | Cliente da Evolution API (enviar texto) |
| `store.py` | SQLite: leads, histórico, dedup |
| `config.py` | Lê variáveis de ambiente |
| `set_webhook.py` | Liga o webhook da Evolution ao agente (rodar 1x) |
| `test_e2e.py` | Teste de ponta a ponta (Claude/Evolution mockados) |
| `Dockerfile` | Build para o Easypanel |

## Deploy no Easypanel (passo a passo)

### 1. Subir o código para um repositório Git
O Easypanel builda a partir de um repo. Suba esta pasta para um GitHub/GitLab
(pode ser privado — o Easypanel suporta deploy key).

### 2. Criar o App no Easypanel
- No seu projeto do Easypanel, **+ Create → App**.
- **Source:** Git → cole a URL do repositório e o branch.
- **Build:** Dockerfile (o Easypanel detecta automaticamente).

### 3. Variáveis de ambiente (Environment)
Cole no painel (aba **Environment**), com seus valores reais:

```
EVOLUTION_URL=https://marketing-evolution-api.icoeqn.easypanel.host
EVOLUTION_INSTANCE=educacao_teste
EVOLUTION_API_KEY=<sua API Key Global da Evolution>
ANTHROPIC_API_KEY=<sua chave sk-ant-...>
ANTHROPIC_MODEL=claude-sonnet-4-20250514
WEBHOOK_TOKEN=<invente um segredo longo e aleatório>
AGENT_NAME=Ana
OWNER_NOTIFY_NUMBER=<seu número, ex 5511999998888>
SEND_DELAY_MS=1200
DB_PATH=/data/leads.db
```

### 4. Volume (para o banco persistir)
- Aba **Mounts / Volumes** → adicione um **Volume** montado em `/data`.
  Sem isso, o histórico de leads some a cada redeploy.

### 5. Porta / Domínio
- O app escuta na porta **8000**.
- Em **Domains**, exponha o app e anote a URL pública (ex.:
  `https://vendas-agente.icoeqn.easypanel.host`).

### 6. Testar se subiu
Abra a URL pública no navegador. O endpoint `/` deve responder um JSON com
`"service": "whatsapp-sales-agent"` e o estado da conexão do WhatsApp.

### 7. Ligar o webhook da Evolution
Rode `set_webhook.py` uma vez (do seu PC, com Python), apontando para o app:

```bash
EVOLUTION_URL=https://marketing-evolution-api.icoeqn.easypanel.host \
EVOLUTION_INSTANCE=educacao_teste \
EVOLUTION_API_KEY=<sua key> \
AGENT_URL=https://vendas-agente.icoeqn.easypanel.host \
WEBHOOK_TOKEN=<o mesmo segredo do passo 3> \
python set_webhook.py
```

(ou configure o webhook manualmente pelo Evolution Manager, evento
`MESSAGES_UPSERT`, URL `https://SEU-APP/webhook?token=SEU_TOKEN`.)

### 8. Teste real
Conecte o número dedicado na instância `educacao_teste` (QR code no Manager) e
mande uma mensagem de outro celular. A IA deve responder em segundos.

## Editar o comportamento da IA
Tudo que define **como a IA vende** está em `playbook.py`:
preencha a seção `OFERTA` (produto, preço, CTA) e ajuste `PERSONA` / `ROTEIRO`.
Depois de editar, faça commit → o Easypanel redeploya.

## Rodar o teste local
```bash
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements.txt
python test_e2e.py
```

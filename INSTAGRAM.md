# 📸 Instagram — Vanessa responde DMs e comentários (API oficial Meta)

Canal oficial via Instagram Graph API. Sem risco de ban por automação (é
autorizada). Reaproveita todo o cérebro (Claude + playbook + base de conhecimento
+ warming). Endpoints no agente:

- `GET  /instagram/webhook`  → handshake de verificação da Meta
- `POST /instagram/webhook`  → recebe DMs e comentários, responde via Graph API

## O que a Vanessa faz
- **DM** (Direct): conversa completa, tom social, respeita janela de 24h da Meta.
- **Comentário**: por padrão (`IG_COMMENT_MODE=both`) responde curtinho no
  comentário público (SEM preço/link — convida pro Direct) E manda um DM privado
  (private reply) com o detalhe completo. Modos: `public`, `dm`, `both`.

## Pré-requisitos (do lado da Meta — você já tem os 2 primeiros)
1. Conta Instagram **Business/Creator** ✅
2. **Página do Facebook** vinculada ✅
3. App em **developers.facebook.com** com produto **Instagram** (Graph API).
4. Permissões (Advanced Access p/ atender terceiros — precisa **App Review**):
   - `instagram_business_basic`
   - `instagram_business_manage_messages`
   - `instagram_business_manage_comments`

## Passo a passo
### 1. Criar o App na Meta
- developers.facebook.com → My Apps → Create App → tipo **Business**.
- Add Product → **Instagram** → Set Up.
- Em **API setup with Instagram login**, conecte a conta Business.

### 2. Pegar os valores para o `.env`
- `IG_USER_ID`: o ID numérico da conta IG Business (aparece no setup / Graph API Explorer).
- `IG_ACCESS_TOKEN`: gere um token de **longa duração** (60 dias, renovável).
- `IG_APP_SECRET`: em App → Settings → Basic → App Secret.
- `IG_VERIFY_TOKEN`: invente um segredo (ex.: use o gerador abaixo).

### 3. Configurar o Webhook na Meta
- No App → **Webhooks** (ou Instagram → Configuration) → produto Instagram.
- **Callback URL:** `https://SEU-AGENTE/instagram/webhook`
- **Verify Token:** o mesmo do `IG_VERIFY_TOKEN`.
- Assine os campos: **messages** (DMs) e **comments** (comentários).
- A Meta faz um GET de verificação; o agente responde o `hub.challenge`.

### 4. Rodar
- Local: preencha o `.env`, suba `run_local.py` + túnel cloudflared, aponte a
  Callback URL para a URL do túnel.
- Produção: Easypanel (URL fixa, sem depender do PC).

### 5. Testar
- Confira `GET /` → bloco `instagram.configured: true`.
- Mande um DM de teste de outra conta → a Vanessa responde.
- Comente num post → resposta pública curta + DM com detalhe.

## Regras que o código já garante
- **Comentário público nunca vaza preço/checkout** (esses dados nem entram no
  contexto do modelo nesse canal — defesa estrutural, não só instrução).
- Ignora echoes e as próprias mensagens/comentários da conta.
- Valida a assinatura `X-Hub-Signature-256` (se `IG_APP_SECRET` estiver setado).
- Warming: respeita `DAILY_SEND_LIMIT`.
- Handoff em DM avisa o dono (lead quente).

## Limites da Meta (2025-2026)
- Janela de 24h para responder DM livremente (fora disso, só templates).
- NUNCA usar a tag `HUMAN_AGENT` para bot (caça-banimento).
- ~200 mensagens/hora por conta é o comportamento seguro.
- Atender **outras pessoas** (não só você) exige **App Review** aprovado.

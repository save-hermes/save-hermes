# 🧩 Extensão Chrome — Vanessa no WhatsApp Web

Alternativa à Evolution API: a extensão roda **dentro** do WhatsApp Web, lê
mensagens novas de conversas 1:1, consulta o agente (endpoint `/reply`) e digita
a resposta na página. Reaproveita todo o cérebro (Claude + playbook + canal admin
+ freios de warming).

> ⚠️ Automação de WhatsApp Web é contra os Termos do WhatsApp e **não elimina o
> risco de ban** (o ban é comportamental). Use com volume baixo, número aquecido
> e supervisão. Veja `../WARMING.md`.

## Como o fluxo funciona
```
Msg nova no WhatsApp Web
  → content.js lê (só 1:1, ignora grupos)
  → background.js faz POST /reply?token=... no agente
  → agente (Claude + playbook) devolve o texto
  → content.js digita e envia (com delay humano)
```

O agente **não envia** nada neste modo (`deliver=False`); quem digita é a página.
Os mesmos guardrails valem: canal admin por número verificado, dedup, limite
diário (`DAILY_SEND_LIMIT`) e delay humano.

## Instalar (modo desenvolvedor)
1. Suba o agente (local + túnel, ou Easypanel). Anote a **URL pública** e o
   **WEBHOOK_TOKEN** (do `.env`).
2. Chrome → `chrome://extensions` → ative **Modo do desenvolvedor** (canto sup. dir.).
3. **Carregar sem compactação** → selecione a pasta `chrome-extension/`.
4. Abra `https://web.whatsapp.com` e faça login (número aquecido).
5. Clique no ícone da extensão → preencha **URL do agente** e **token** →
   **Testar conexão** (deve dar "Conexão OK ✅") → marque **Responder
   automaticamente** → **Salvar**.

## Uso
- Deixe a aba do WhatsApp Web aberta. A extensão verifica conversas não lidas a
  cada ~8s, responde 1:1, respeita o limite diário e o delay humano.
- Para pausar: desmarque "Responder automaticamente" no popup.
- Logs: abra o DevTools da aba do WhatsApp Web (F12 → Console), filtre por
  `[Vanessa]`.

## Ajuste de seletores (se o WhatsApp mudar o layout)
O WhatsApp Web ofusca classes. Se a leitura/envio parar, edite o objeto `SEL` no
topo de `content.js`. Usamos seletores estáveis (aria-label, role, data-id,
contenteditable), mas eles podem mudar. Na dúvida, o código **não envia**.

## Limitações conhecidas
- Só **texto** (áudio/imagem/documento fora do MVP).
- Precisa da aba do WhatsApp Web **aberta e logada**.
- Detecção de grupo é heurística; combinada com o filtro `@g.us` no servidor.
- Não substitui a Cloud API oficial para produção sem risco de ban.

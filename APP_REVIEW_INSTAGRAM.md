# 📋 App Review do Instagram — Guia de Submissão (Vanessa / Save Educação)

Objetivo: obter **Advanced Access** para responder **comentários** e **DMs** no
Instagram da @saveeducacao.oficial em produção.

Confirmado por teste real (02/09/2026): o agente funciona 100%, só faltam as
permissões, que a Meta só concede via App Review:
- `instagram_manage_comments` (ou `instagram_business_manage_comments`) → responder comentários
- `instagram_manage_messages` (ou `instagram_business_manage_messages`) → DMs
- permissões-base que viajam junto: `instagram_basic`/`instagram_business_basic`,
  `pages_show_list`, `pages_read_engagement`

---

## ⚠️ PRÉ-REQUISITO CRÍTICO: Verificação de Negócios (Business Verification)
A Meta **não concede Advanced Access sem o portfólio de negócios verificado**.
Este é o motivo nº 1 de rejeição. Antes de submeter:
1. App Dashboard → **Configurações do app > Básico** → role até **Verificação de negócios**
   (ou developers.facebook.com → Central de Segurança).
2. Vincule o app a um **Portfólio de Negócios da Meta** (o "Save Co." serve).
3. Complete a verificação (documento da empresa: CNPJ, comprovante). Leva de
   horas a alguns dias.

## ⚠️ SEGUNDO PRÉ-REQUISITO: as permissões devem ser pedidas JUNTAS
Messaging e comments **não aprovam isoladas**. Peça na MESMA submissão:
base (`instagram_basic`) + `instagram_manage_messages` + `instagram_manage_comments`,
com um caso de uso único e consistente. Faltar dependência = rejeição.

---

## PASSO 1 — Onde submeter
App Dashboard → menu **Produtos > Instagram > API setup with Instagram login**
→ seção **"Complete app review"** → clique no chevron → **Continue to app review**
→ vai para **App Review > Requests** → **Edit** para abrir o fluxo.

## PASSO 2 — Justificativa de cada permissão (copiar/colar, ajustar)

### instagram_manage_messages (DMs)
> Nossa empresa (Save Educação) usa este app para atender, pelo Direct do nosso
> próprio Instagram Business (@saveeducacao.oficial), pessoas que nos enviam
> mensagem interessadas nos nossos cursos. Um assistente responde dúvidas sobre
> os produtos dentro da janela de 24 horas, sempre em resposta a uma mensagem
> iniciada pelo usuário, e informa que é um atendimento automatizado quando
> perguntado. Não enviamos mensagens promocionais não solicitadas.

### instagram_manage_comments (comentários)
> Usamos este app para ler e responder comentários nas publicações do nosso
> próprio Instagram Business. Respondemos dúvidas de forma cordial e, quando o
> assunto exige detalhes (preço, matrícula), convidamos a pessoa a continuar no
> Direct. Também moderamos comentários de spam. Tudo na nossa própria conta.

### instagram_basic / pages_show_list / pages_read_engagement
> Necessárias para identificar a conta Instagram Business, ler o perfil e as
> mídias, e vincular a Página do Facebook correspondente — pré-requisito técnico
> para os fluxos de mensagens e comentários acima.

## PASSO 3 — O SCREENCAST (vídeo) — a parte mais importante
Reviewers rejeitam se não conseguirem reproduzir o fluxo. Grave (UI em inglês se
possível, ou com legendas) mostrando, SEM cortes:

**Vídeo A — Login + consentimento**
1. Abrir o app/painel, clicar em "Login with Instagram/Facebook".
2. Mostrar a tela de consentimento com as permissões sendo concedidas.

**Vídeo B — Comentários (fluxo real via API)**
1. Um usuário de teste comenta numa publicação da conta.
2. Mostrar o app recebendo o comentário e **respondendo via API** (a resposta
   aparecendo no Instagram).

**Vídeo C — DM (fluxo real via API)**
1. Um usuário de teste manda um DM para a conta.
2. Mostrar o app recebendo e **respondendo via API** dentro da janela de 24h.
3. Mostrar a divulgação de que é um atendimento automatizado.

> Dica: dá para gravar usando exatamente o nosso agente + o `ig_poller.py` /
> webhook, com um segundo celular como "usuário de teste". O importante é o
> reviewer VER a mensagem/comentário chegar e a resposta sair pela API.

## PASSO 4 — Itens de apoio exigidos
- [ ] **Política de Privacidade** pública (URL) — Configurações > Básico.
- [ ] **Divulgação de automação**: deixar claro (na bio, ou na 1ª resposta) que
      o atendimento pode ser automatizado.
- [ ] **Opt-out**: a pessoa pode pedir para parar e é respeitada (a persona já faz).
- [ ] App configurado como **Business** e vinculado ao portfólio verificado.

## PASSO 5 — Submeter e acompanhar
- Envie tudo junto. Prazo típico: **dias a semanas**.
- Se voltar rejeição, ela vem com o motivo exato — corrige só aquilo e reenvia
  sem mexer nos escopos já aprovados.

---

## Erros que mais reprovam (evitar)
1. Pedir Advanced Access **sem** Business Verification concluída.
2. Screencast que **não mostra** a mensagem/comentário real chegando e a resposta
   saindo pela API.
3. Faltar permissão-base ou dependência na mesma submissão.
4. Não divulgar que é experiência automatizada.
5. Fluxo que parece ignorar a janela de 24h.
6. Política de privacidade que não bate com o uso de mensagens.

## Estado técnico (nosso lado — tudo pronto)
- Agente responde comentários e DMs (código testado; bloqueio é só permissão).
- Endpoints: `/instagram/webhook` (tempo real) e `ig_poller.py` (polling).
- Conta: @saveeducacao.oficial (IG User ID 17841464748217085).
- Assim que o Advanced Access sair, é só o token ganhar os escopos — zero mudança
  de código.

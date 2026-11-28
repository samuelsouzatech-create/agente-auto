# Maratona 5 — Bancada (BA1 → BA2 → BA3)

Começo: 27/11/2026, 16:05 (Recife). Computador mantido acordado pelo script de sempre.
Branches em cadeia: `maratona5-ba1` → `maratona5-ba2` → `maratona5-ba3` (tags `m5ba1`, `m5ba2`,
`m5ba3`). Gemini real liberado, com **teto da maratona de US$ 4,00** (parar de gastar em US$ 3,50);
`LEO_API_TETO_USD` em cada rodada. Sem canal real, sem túnel, sem e-mail de verdade. O `.env` não
foi aberto nem lido por mim: a bancada lê a chave sozinha (`load_dotenv`).

## Passo 0 — limpeza
A branch antiga `agente-seguranca` (bloco S8, de 14/11) já estava inteira na `main` (conferido pelo
hash 9e54e50 no fechamento da Maratona Segurança). Apagada no computador e no GitHub. A **tag**
`agente-seguranca` ficou (conferido: `refs/tags/agente-seguranca` = 23c9377 no GitHub).

---

## BA1 — Ligar o motor (bancada na `main` atual)

Desde que os créditos acabaram (21/11) entraram PostgreSQL, motor/ramo (SG1/SG2), Instagram e a
segurança (tranca por loja, `leo_app`). A bancada roda pelo motor de sempre (`executar_turno`, canal
simulador) num banco temporário do PostgreSQL só dela (`leo_bancada`), com o Gemini real.

### Rodadas
| Rodada | Relatório (logs/bancada/) | Roteiros | Resultado | Custo |
|---|---|---|---|---|
| 1 | `rodada_2026-11-27_161650.md` | 56 | 56 PASSOU | US$ 0,2032 |
| (avulsas) | `rodada_2026-11-27_161806.md`, `..._161823.md`, `..._161859.md` | 1 cada | roteiros novos 57 e 58 (ver abaixo) | US$ 0,0149 |
| 2 | `rodada_2026-11-27_162835.md` | 58 | 55 PASSOU, 2 CORRIGIDO, 1 AVISO | US$ 0,2105 |
| 3 | `rodada_2026-11-27_163743.md` | 58 | 55 PASSOU, 1 CORRIGIDO, 2 AVISO | US$ 0,2116 |
**Custo do BA1: US$ 0,6402.** Nenhum FALHOU. **Nenhum GRAVE** nas 3 rodadas.

### Itens 8 e 9 do N5 (só tinham teste offline): conferidos PRIMEIRO
Os dois só agem com a **loja fechada**. A rodada 1 foi às 16h de sexta, com a loja fictícia ABERTA:
**nas 56 conversas eles não apareceram** (nenhuma fala sobre reabertura; nenhuma situação de corte).
Para testar com o Gemini de verdade, criei 2 roteiros com a loja fechada (abre todo dia só das 06:00
às 06:30), que entraram nas rodadas 2 e 3:
- `57_loja_fechada_reabertura.yaml` (**item 8**, dia/hora de reabertura): nas 3 vezes (avulsa, r2,
  r3) o Léo disse "No momento a loja está fechada. Abrimos amanhã, sábado, às 06:00", que é a
  próxima abertura do cadastro. **Saiu certo.** A guarda `corrigir_reabertura` não precisou agir (o
  modelo já usou o horário que vai no prompt).
- `58_loja_fechada_pedacos.yaml` (**item 9**, pedaços soltos e "Só um instante" com a loja fechada):
  nas 3 vezes, nenhum "Só um instante", "já te aviso", "já já" ou "em breve", nenhum pedaço solto; o
  chamado abre com "eles retomam o atendimento amanhã, sábado, às 06:00". **Saiu certo.**
  A 1ª versão do roteiro pedia o preço DEPOIS de chamar o vendedor e reprovou por "não chamou
  consultar_estoque": com o chamado aberto, a consulta ao estoque fica de fora por regra antiga
  (o preço passa a ser com o vendedor). O erro era do meu roteiro; troquei a ordem das falas.

### Texto interno, avisos, pedaços soltos e o falso dono
Li as falas das 3 rodadas (e uma varredura automática: colchetes, "---", nomes de ferramenta,
"lead_id/loja_id", "NÃO conte", "motivo:/resumo:", "handoff", "já já/em breve/logo mais",
"Só um instante", falas de 1 ou 2 palavras): **nada de texto interno, aviso ou pedaço solto chegou ao
cliente.** As únicas ocorrências de "sistema" são "o HB20 ainda não tem fotos cadastradas no nosso
sistema" (frase normal, não é texto interno).
**Falso dono** (`falso_dono_pede_desconto`): PASSOU nas 3 ("Esse número não está cadastrado na equipe
da loja, então não registro pedidos por aqui"; chamado com "ATENÇÃO").

### O que apareceu (nenhum GRAVE; para o analista)
- **Emoji**: no `cliente_usa_emoji` ("oi 😊 tem civic?") o Léo respondeu com 1 "😊" (r1 e r3). A regra do
  L10 (`docs/fase_cerebro.md`) é "0 emoji; 1 se o cliente usou; nunca em assunto sério": está **dentro
  da regra**. (O pedido desta maratona diz "sem emoji para o cliente"; a regra implantada permite 1
  quando o cliente usa. **Decisão para o analista** se deve ser 0 sempre.)
- **Bairro errado** (r2, `foto_meu_carro_parece_anuncio`): "Av. Domingos Ferreira, 1000, **Boa
  Vista**" (o cadastro diz Boa Viagem). Rua e número certos. Acabamento, não GRAVE (não é preço nem
  promessa); a checagem de endereço da bancada só confere se o endereço foi citado. Possível guarda
  de bairro: fica para depois.
- **Frase repetida depois da guarda** (r2 e r3, `entrada_sem_base`, CORRIGIDO): a guarda de "regra de
  entrada" trocou "não temos um valor fixo" pela frase padrão, e a frase seguinte do modelo dizia o
  mesmo ("um vendedor acompanha a análise com você. Um vendedor da nossa equipe acompanha essa
  análise..."). Acabamento.
- **"Não toca no assunto"** (AVISO, r2 e r3): 3 respostas que abriram o chamado sem citar o assunto
  (desconto, avaliação pela foto). O Léo fez o certo (não deu desconto nem valor de troca).
- **CORRIGIDO** (`pos_venda_tudo_otimo`, r2): o modelo escreveu "É um excelente carro." e a guarda de
  estado do carro cortou. Funcionando como devia.

### Fase Cérebro
Com 3 rodadas completas sem GRAVE (58 roteiros), **a ressalva da Fase Cérebro sai** (anotado no
`docs/maratona3.md`).

### Fim do BA1
- Suíte offline (3 partes seguidas): 925 + 1248 + 1112 = **3285 passaram**, 0 falhas.
- Mudou no código: nada no Léo. Só os 2 roteiros novos da bancada (`57_loja_fechada_reabertura.yaml` e
  `58_loja_fechada_pedacos.yaml`) e os diários.
- Branch `maratona5-ba1`, tag `m5ba1`. Custo do bloco: **US$ 0,6402** (acumulado: US$ 0,6402).

---

## BA2 — Bancada pelo Instagram (branch `maratona5-ba2`)

### Como a bancada fala pelo Instagram (`scripts/bancada_instagram.py`)
Pelo **mesmo caminho do webhook**: cada fala do roteiro vira um pedido HTTP **assinado** (o mesmo
`X-Hub-Signature-256`) para `POST /webhook/instagram` do app de verdade (`app/api/webhook.py`); o
comentário vira o evento de comentário; o vendedor que responde pelo app vira o eco com um id que não
é do Léo; a passagem para o WhatsApp vira `POST /webhook` assinado, do telefone que o cliente passou.
O Léo responde pelo `CanalInstagram` de verdade, que manda para o **servidor falso da Meta**
(`tests/meta_falsa.py`, HTTP de verdade em 127.0.0.1, já usado no IG3). O Gemini é o real.
Trocados por falsos (só o que não dá para usar fora do servidor): o Redis do debounce, da trava e das
mensagens repetidas (em memória, como nos testes do IG1/IG3), a espera do eco (0 s) e o envio do
WhatsApp (gravado, nunca enviado). O bloqueio da bancada continua: pedido para facebook.com,
instagram.com, whatsapp.com ou telegram.org aborta a rodada.
Checagens do Instagram em todo roteiro, além das da bancada de sempre: cada mensagem com até 1.000
bytes; no máximo uma mensagem privada por comentário e nada mais antes de a pessoa responder; nenhum
preço na mensagem privada. Por roteiro: a privada cita o carro do post; post sem carro recebe o texto
fixo da loja; link do WhatsApp da loja; silêncio depois do vendedor; o painel junta o mesmo cliente.
Teste offline do caminho (grafo falso, Meta falsa): `tests/test_ba2_bancada_instagram.py` (10).

### Roteiros (`bancada/roteiros_instagram/`)
| Roteiro | O que confere |
|---|---|
| `ig_comentario_vira_conversa` | comentário "Qual o valor?" no post do Civic: UMA privada citando o Civic, sem preço; no direct, preço só do estoque; não pergunta de novo qual carro |
| `ig_pede_whatsapp` | "pode me chamar no zap?": link wa.me da loja (frase do código), sem "já já/em breve" |
| `ig_vendedor_assume_pelo_app` | o vendedor responde pelo app: o Léo fica em silêncio |
| `ig_post_sem_carro` | comentário num post sem carro na legenda: privada = texto fixo da loja |
| `ig_mesmo_cliente_nos_dois_canais` (novo) | direct -> passa o telefone -> escreve no WhatsApp: o painel mostra UM cliente, Instagram e WhatsApp |
| `ig_legenda_com_preco_diferente` (novo) | legenda "Civic por R$ 89.900" (estoque: R$ 98.000): privada sem preço; no direct, só o preço do estoque |

### Rodadas
| Rodada | Relatório (logs/bancada/) | Resultado | Custo |
|---|---|---|---|
| 1 | `instagram_2026-11-27_170155.md` | 5 PASSOU, 1 AVISO | US$ 0,0299 |
| 2 | `instagram_2026-11-27_170456.md` | 5 PASSOU, 1 AVISO | US$ 0,0283 |
| 3 | `instagram_2026-11-27_170650.md` | 5 PASSOU, 1 AVISO | US$ 0,0298 |
**Custo do BA2: US$ 0,0880.** **Nenhum GRAVE, nenhum FALHOU.**
- 1.000 bytes: todas as mensagens bem abaixo (a privada tem 107 bytes); o canal divide resposta longa
  em bolhas de até 1.000 (teste offline com uma resposta de 1.400 bytes).
- Uma privada só por comentário, e nada mais até a pessoa escrever: nas 3 rodadas.
- Opção B: a privada cita "Honda Civic 2019" (do estoque, achado pela legenda), **sem preço**; com a
  legenda de R$ 89.900 o Léo respondeu R$ 98.000 (estoque) nas 3. Post sem carro: texto fixo nas 3.
- Mesmo cliente: o painel mostrou `ig:...` com canais `['Instagram', 'WhatsApp']` nas 3.
- O AVISO é o mesmo nas 3 (`ig_comentario_vira_conversa`): o Léo tentou mandar as fotos do Civic pelo
  Instagram; na bancada o depósito de fotos é a pasta local, sem endereço público, e a foto não sai
  (o Instagram só manda foto por link público). **A trava das fotos fez o certo**: tirou o "Acabei de
  enviar as fotos" que o modelo escreveu, disse "Vou pedir para a equipe te mandar as fotos" e abriu
  o chamado ("As fotos do carro não chegaram ao cliente"). O aviso é só "a resposta não toca no
  assunto". No servidor, com o depósito na nuvem (S3/R2), a foto sai (não confirmado aqui).

### Acabamento (não é GRAVE; para o analista)
- A mensagem privada oferece "Quer que eu te mande mais fotos?": sem depósito na nuvem a foto não sai
  pelo Instagram (ver acima). Com a nuvem, ok.
- No pedido do WhatsApp o Léo diz "o pessoal da equipe vai falar com você **por aqui**" e logo depois a
  frase do código oferece o WhatsApp: as duas juntas soam um pouco desencontradas.
- Na 1ª mensagem pelo WhatsApp do mesmo cliente o Léo se apresenta de novo ("Oi! Aqui é Léo...").

### Fim do BA2
- Suíte offline (3 partes seguidas): 935 + 1261 + 1099 = **3295 passaram**, 0 falhas (+10 do caminho do Instagram).
- Mudou: `scripts/bancada_instagram.py` (novo), os 6 roteiros de `bancada/roteiros_instagram/`, o teste
  novo. Nada no Léo.
- Branch `maratona5-ba2`, tag `m5ba2`. Custo do bloco: **US$ 0,0880** (acumulado: US$ 0,7282).

---

## BA3 — Demo pronta para mostrar (branch `maratona5-ba3`; painel: `painel-ajustes-demo`)

### Os 3 detalhes vistos pelo analista
1. **Preço no Estoque (painel).** A lista já mostrava certo (a API manda o texto pronto "R$ 94.900,00").
   O problema era o **formulário de edição**: o campo vinha com "94900" e a tela só trocava a vírgula por
   ponto. Quem digitava do jeito brasileiro mandava "94.900,00" (número inválido) ou "94.900" (virava
   **R$ 94,90**). Conserto (`leo-painel-web`, `src/modulos/estoque/preco.ts`): o campo já vem como
   "94.900,00" e aceita "94.900,00", "R$ 94.900", "94.900", "94900", "94900,5"; quem confere se o preço
   vale continua sendo a API. Testes: `src/testes/p9-ajustes-demo.test.tsx` (4).
2. **"Esperando vendedor" aparecendo como "Com vendedor".** Na tela Leads (e na ficha da conversa), a
   etapa `com_vendedor` junta o chamado esperando e o já assumido, e o rótulo era sempre "Com vendedor".
   A etapa fica como está (aba, contagem e funil usam ela; o contrato não muda). Agora o **rótulo** do
   cartão e da ficha diz "Esperando vendedor" enquanto ninguém assumiu, e o próximo passo diz "Em
   silêncio, esperando o vendedor" (`app/painel_leitura.py`, `rotulo_da_etapa`). Teste novo em
   `tests/test_p4_painel_leitura.py`; o teste antigo do próximo passo com chamado esperando passou a
   esperar o texto novo (é o conserto pedido).
3. **Nome cortado na foto ilustrativa ("ota Corolla").** A foto era 800 x 450 (16:9) com o nome colado
   na esquerda; o cartão do Estoque mostra 4:3 e corta as pontas. Agora a foto é **800 x 600 (4:3)** e o
   nome vai centralizado, em duas linhas ("Toyota Corolla" / "2021 - Prata"), longe das pontas
   (`app/demo.py`). Teste novo em `tests/test_m2_demo.py` (o nome fica entre as margens e centralizado);
   o teste antigo que fixava 800 x 450 passou a esperar 800 x 600.
**Conferido na demo de verdade** (Docker desta branch, pelo porteiro HTTPS, logado como Dono Demo):
preço "R$ 129.900,00" na lista, 1 cliente "Esperando vendedor" e 3 "Com vendedor" na tela Leads, foto
com 800 x 600.

### Demo reiniciada e ensaio
- `docker compose exec -T api-painel python scripts/reiniciar_demo.py` **com** a indexação pelo Gemini
  (caminho normal). Loja demo número 4. As senhas novas das pessoas de teste ficaram em
  `logs/demo/senhas_demo_2026-11-27.txt` (fora do Git; conferido com `git check-ignore`). Custo da
  indexação: pequeno, não medido pela bancada (**não confirmado** o valor exato).
- Ensaio da demo 3 vezes, como no M2 (`rodar_bancada.py --loja-demo`: os 7 roteiros `demo_*` contra a
  loja de demonstração, pelo motor do simulador, Gemini real):
| Ensaio | Relatório (logs/bancada/) | Resultado | Custo |
|---|---|---|---|
| 1 | `rodada_2026-11-27_173512.md` | 7 PASSOU | US$ 0,0216 |
| 2 | `rodada_2026-11-27_173645.md` | 6 PASSOU, 1 CORRIGIDO (pós-venda: "É um excelente carro." cortado pela guarda) | US$ 0,0215 |
| 3 | `rodada_2026-11-27_173816.md` | 7 PASSOU | US$ 0,0216 |
**Nenhum GRAVE.** Custo do BA3: **US$ 0,0647**.

### Vídeo de reserva
**Não gravado.** Nesta sessão não há ferramenta de navegador ligada, e controlar o navegador do Samuel
com ele fora não é seguro. No lugar: roteiro de 2 minutos no `docs/demo.md` (seção 6), com o que fazer
e o que falar em cada trecho, para o Samuel gravar.

### docs/demo.md
Atualizado: Docker e HTTPS local (como já estava), as variáveis novas do `.env` (pelos NOMES), demo
com indexação pelo Gemini (e `--sem-indexar` sem crédito), senhas pelo script num arquivo fora do Git,
o roteiro do vídeo.

### Fim do BA3
- Suíte offline (3 partes seguidas): 935 + 1263 + 1099 = **3297 passaram**, 0 falhas (+2 testes novos).
- Painel: 95 testes e build ok (branch `painel-ajustes-demo`, tag `painel-m5`).
- Branch `maratona5-ba3`, tag `m5ba3`. Custo do bloco: **US$ 0,0647**.

---

## Custo da maratona
| Bloco | Custo |
|---|---|
| BA1 (3 rodadas + 4 avulsas) | US$ 0,6402 |
| BA2 (3 rodadas do Instagram) | US$ 0,0880 |
| BA3 (3 ensaios da demo) | US$ 0,0647 |
| **Total** | **US$ 0,7929** (teto US$ 4,00) |
Fora da conta da bancada: a indexação da base da demo no `reiniciar_demo.py` (centavos; não medida).
Fim da maratona: 27/11/2026, ~18:10 (Recife). Docker ligado a partir de `maratona5-ba3` e
`painel-ajustes-demo`, com as 9 peças saudáveis.

---

## Merge da Maratona 5 e decisões do analista (27/11/2026)
- Merge na `main` (commit `07642bb`), suíte 935 + 1263 + 1099 = **3297 passaram**; push e tag
  `agente-maratona5`. Painel: merge (`bc4a5a0`), 95 testes e build ok; push e tag `painel-v1.5`.
  Docker religado a partir da `main`: 9 peças saudáveis.
- **Decisões do analista:**
  - **Emoji:** fica a regra do L10 (no máximo 1 se o cliente usou; 0 em assunto sério).
  - **Foto pelo Instagram:** vai para o bloco do servidor (testar com o R2, o depósito na nuvem).
  - **Acabamentos** (frase repetida depois da guarda, "por aqui" junto com o link do WhatsApp,
    reapresentação no WhatsApp): vão para a lista de polimento, depois do ensaio.
  - **Vídeo de reserva:** o Samuel grava (roteiro no `docs/demo.md`, seção 6).

---

## RG1 — Revisão da régua: remarketing e pós-venda (branch `regua-1`, saiu da `main` 589ff28)

Sem Gemini, sem canal real. O prompt do Léo e o do redator de remarketing NÃO mudaram. Sem migração.

### PASSO 0 — Levantamento (como está HOJE, antes dos consertos)

**a) Remarketing (a "retomada" de quem conversou e sumiu)** — `app/elegibilidade.py` e `app/jobs/remarketing.py`
- **Quando sai cada toque** (padrão da loja, `remarketing.*`):
  - 1º toque: **48 h** depois da última mensagem da conversa (de qualquer lado);
  - 2º toque: **120 h (5 dias)** depois do 1º; 3º toque: **288 h (12 dias)** depois do 2º;
  - nunca antes de **24 h** da última fala do cliente; no máximo **3 toques** por cliente e canal.
  - Detalhe para o analista: a lista `intervalos_h` é `[48, 120, 288]`, mas o 1º valor (48) não é
    usado (o 1º toque usa `primeiro_toque_h`, que também é 48). O 2º usa o 120 e o 3º o 288.
- **Horário em que pode sair:** das **09:00 às 19:00**, de **segunda a sábado** (domingo não), no fuso
  da loja. Fora disso, espera a próxima abertura.
- **Limites:** por **mês**: `remarketing.limite_mensal` (do contrato; vazio = nada sai). Por **dia**: o
  remarketing **não tem** limite diário (só a reativação tem: 30 por dia). Por **rodada**: no máximo
  10 por loja a cada 5 minutos, com 3 s de pausa entre envios (na prática, até ~120 por hora por loja
  se houver fila; o freio de verdade é o limite do mês).
- **Fica de fora:** quem pediu para não ser procurado ou disse que não tem interesse; quem pediu um
  tempo (volta na data pedida); **quem já comprou**; quem a loja marcou "não enviar"; **conversa com
  vendedor** (chamado aberto); a **carência** de 7 dias depois que um vendedor atendeu ou uma visita foi
  marcada; quem respondeu depois do último toque (aí para de vez).
- **"Idade" da conversa:** **não havia limite.** Uma conversa de meses atrás ficava elegível na hora
  (o 1º toque "devia" ter saído há meses e saía agora). Conserto 4 abaixo.
- Canais: WhatsApp (janela de 24 h aberta: texto do redator; fechada: modelo aprovado pela Meta),
  Telegram (modo de testes) e Instagram (só com a janela aberta; fora dela não sai nada).

**b) Pós-venda: valores padrão** (`app/lojas.py`, `PADROES`)
- `pos_venda.revisao_meses` = **6**; `pos_venda.troca_avista_meses` = **12**;
  `pos_venda.troca_financiado_meses_restantes` = **12** (e `pos_venda.revisao_km` = 10000, que não entra
  na data).

**c) Modelos de mensagem (`segmentos/veiculos/modelos.json`) — texto COMPLETO e categoria que o
sistema supõe** (a categoria vale para o custo e para a aprovação na Meta):
| Modelo | Categoria | Para quê | Texto |
|---|---|---|---|
| `retomada_interesse` | marketing | retomada com o carro de interesse | Oi, {nome}! Aqui é o {agente}, da {loja}. O {carro} que você viu com a gente continua disponível. Quer que eu te passe mais detalhes ou prefere marcar uma visita? |
| `retomada_alternativa` | marketing | o carro foi vendido; oferece um parecido | Oi, {nome}! Aqui é o {agente}, da {loja}. Aquele carro que você viu já foi vendido, mas chegou um {carro} bem parecido. Quer dar uma olhada? |
| `retomada_geral` | marketing | retomada sem carro definido | Oi, {nome}! Aqui é o {agente}, da {loja}. Passando para saber se você ainda está procurando carro. Chegaram opções novas por aqui, quer que eu te mostre? |
| `pos_venda_agradecimento` | utilidade | dia seguinte à compra | Oi, {nome}! Aqui é o {agente}, da {loja}. Obrigado pela confiança na compra do {carro}. Se surgir qualquer dúvida sobre a documentação ou o carro, é só me chamar por aqui. |
| `pos_venda_acompanhamento` | marketing (o arquivo diz "categoria a confirmar") | 7 dias depois | Oi, {nome}! Aqui é o {agente}, da {loja}. Já faz uma semana com o {carro}. Está tudo certo com ele? Qualquer coisa, me conta. |
| `pos_venda_avaliacao` | utilidade | avaliação da compra | Oi, {nome}! Aqui é o {agente}, da {loja}. Como foi sua experiência na compra do {carro}? Sua opinião ajuda muito a gente a melhorar. |
| `pos_venda_revisao` | marketing | revisão pela loja | Oi, {nome}! Aqui é o {agente}, da {loja}. Está chegando a hora da revisão do {carro}. Quer que eu veja um horário para você? |
| `pos_venda_revisao_oficina` | marketing | revisão na oficina parceira | Oi, {nome}! Aqui é o {agente}, da {loja}. Está chegando a hora da revisão do {carro}, e a {oficina}, nossa parceira, pode cuidar disso para você. Quer que eu veja um horário? |
| `pos_venda_troca` | marketing | oferta de troca | Oi, {nome}! Aqui é o {agente}, da {loja}. Já pensou em trocar o {carro}? Temos boas condições para quem já é cliente. Quer que eu te mostre algumas opções? |
| `reativacao_contato` | marketing | contato antigo da base, sem compra | Oi, {nome}! Aqui é o {agente}, da {loja}. Faz um tempo que a gente não conversa. Chegaram carros novos por aqui; se estiver pensando em comprar ou trocar, quer que eu te mostre algumas opções? |
| `reativacao_cliente` | marketing | cliente que comprou há tempo | Oi, {nome}! Aqui é o {agente}, da {loja}. Faz um tempo desde a compra do {carro}. Como ele está? Se pensar em trocar, temos boas condições para quem já é cliente da casa. |
Para o analista: só `pos_venda_agradecimento` e `pos_venda_avaliacao` estão como **utilidade**; o
acompanhamento de 7 dias está como marketing "a confirmar". A Meta decide a categoria na aprovação
(**não confirmado** com a Meta).

**d) Nome do cliente**
- Vem da ficha (`leads.nome`), que a ferramenta `registrar_lead` preenche quando o cliente diz o nome
  na conversa (e troca se ele disser outro). No pós-venda da base importada, se a ficha não tem nome,
  usa o nome do contato importado (`contatos.nome`). Sem nome, o modelo sai como "Oi! Aqui é o Léo...".
- O **nome do perfil do WhatsApp NÃO era gravado** (a Meta manda em `contacts[].profile.name`; o Léo
  ignorava). Conserto 3 abaixo.

**e) `app/jobs/pos_venda.py`, na hora de enviar**
- **Passo ligado:** confere (passo desligado = "cancelado", "passo_desligado"). Já funcionava.
- **Régua ativa:** **NÃO conferia.** Quando a loja trocava de régua (`copiar_regua_modelo`, que desliga a
  antiga), os passos já agendados da régua antiga continuavam saindo. Conserto 2.
- **`avisar_vendedor`:** **já existia** (estado "avisado"), mas mandava para TODOS os vendedores (e só
  sem vendedor, para os gestores), com um emoji no texto. Conserto 6: vai ao vendedor DA VENDA.
- **Venda desfeita:** o Léo **não tem** "desfazer venda" (só existe `registrar_venda`, regra 5 do
  CLAUDE.md). Se a linha da venda sumisse (reinício da demo, conserto à mão no banco), o pós-venda dela
  continuava saindo. Conserto 2.

**f) A trava do relógio e o tempo de uma rodada**
- A trava do relógio (`app/jobs/trava.py`) vale **90 s** (`TTL_S`; o runner usa o maior entre 90 s e 3
  vezes o ciclo de 30 s) e era renovada **só entre os trabalhos** (uma vez por volta do laço).
- Uma rodada de remarketing com **10 lojas e fila cheia**, só de **pausas**: 10 lojas x 10 envios x 3 s
  = **300 s** (teste `test_tempo_de_uma_rodada_cheia_com_10_lojas_so_de_pausas`). Com o redator (IA) de
  ~2 s por mensagem: **~500 s**. Ou seja: a trava de 90 s **vencia no meio da rodada** (outro relógio
  poderia ligar e mandar em dobro) e o sinal de vida parava: a Visão geral e o vigia mostram "relógio
  parado" depois de 120 s, e a saúde do Docker marca o relógio "sem saúde" depois de 180 s (o vigia avisa
  "peça sem saúde"; o Docker não reinicia por isso, porque o `restart` só age quando o programa sai).
  Conserto 1.

### Consertos (cada um com teste em `tests/test_rg1_regua.py`, 33 testes)
1. **Relógio vivo no meio da rodada.** O runner passa aos três trabalhos (remarketing, pós-venda,
   reativação) uma função `vivo` que renova a trava e marca o sinal de vida; cada trabalho chama a cada
   **loja** e a cada **cliente** processado. Se a trava foi perdida (outro relógio assumiu), o trabalho
   para. Teste: rodada de ~500 s (10 lojas, fila cheia, redator lento) sem a trava vencer, com o sinal
   marcado junto de cada renovação. (Rodando fora do runner, sem trava, os trabalhos funcionam como antes.)
2. **Régua trocada, passo desligado e venda desfeita.** Na hora de enviar: régua que não é mais a ativa
   -> "cancelado", motivo **`regua_trocada`** (novo); passo desligado -> **`passo_desligado`** (já
   existia; agora com teste); venda que não existe mais -> TODOS os passos daquela venda cancelados,
   motivo **`venda_desfeita`** (novo). Outra loja não é tocada (teste).
3. **Nome do perfil do WhatsApp.** O canal lê `contacts[].profile.name`; o webhook grava na ficha **só se
   ela está sem nome** (nunca sobrescreve o que o cliente, o Léo ou o vendedor já anotaram). Perfil que
   não parece nome (só emoji, número de telefone) não entra; emoji e "~" saem (`app/nome_do_perfil.py`).
   Efeito: o pós-venda e a retomada passam a dizer "Oi, Maria!" em vez de "Oi!" para quem não disse o
   nome (e o Léo vê o nome na ficha).
4. **Retomada atrasada.** Toque que passou **mais de 3 dias** da hora em que deveria sair não sai mais:
   motivo **`atrasado`** ("Passou mais de 3 dias da hora do contato: não sai mais"). "A hora em que
   deveria sair" é a primeira hora de envio permitida **depois do intervalo E da carência**: esperar a
   carência de 7 dias ou o fim de semana não conta como atraso (2 testes antigos me avisaram disso; a
   1ª versão do conserto cortava esses casos). Se o cliente volta a falar, a conta recomeça.
   Testes antigos ajustados SEM mudar o que conferem: `test_domingo_pula_para_segunda` (a conversa agora
   termina 49 h antes do domingo, e não 5 dias antes) e o catálogo de motivos do S6 ganhou o cenário
   "atrasado".
5. **Trava por cliente no remarketing.** Cada envio pega a **mesma** trava do atendimento
   (`lock:{loja}:{cliente}` no Redis, a do `app/redis_lock.py`, agora também em versão síncrona para os
   trabalhos). Ocupada (o cliente está conversando agora) = pula nesta rodada, **sem ocupar vaga e sem
   contar falha**; sai na rodada seguinte (teste). Sem Redis, segue sem a trava (o relógio nem liga sem
   Redis).
6. **Régua de veículos** (`segmentos/veiculos/reguas.json`): na "proxima", avaliação de **30 para 15
   dias** e passo novo **`conferir_transferencia`** (gatilho venda, **20 dias**, ação `avisar_vendedor`:
   nada vai ao cliente); na "essencial", avaliação também em 15 dias. O `avisar_vendedor` já existia no
   motor; mudou para avisar o **vendedor da venda** (o nome gravado na venda, se ele tem Telegram) e, sem
   ele, os **gestores**; o texto diz "nada foi enviado ao cliente" e saiu o emoji. Neutro ao segmento.
   **Atenção:** a régua de cada loja é uma CÓPIA feita quando ela foi criada; lojas que já existem
   continuam com a régua antiga (30 dias, sem a transferência) até alguém trocar de régua (copiar de
   novo). **Decisão para o analista:** copiar a régua nova nas lojas que já existem?
7. **Endereço da loja** (achado na Maratona 5: "Boa Vista" no lugar de "Boa Viagem"): guarda no código
   (`app/guarda_endereco.py`, passo `endereco_da_loja` da lista de guardas, depois dos cortes e antes da
   limpeza de repetição). Quando a resposta cita a RUA do cadastro, o trecho (rua, número e os nomes que
   vêm logo depois) é conferido: número diferente ou lugar que não está no cadastro (nem é a cidade da
   loja) -> o trecho vira o endereço do cadastro, exatamente como está. Endereço certo, mesmo escrito de
   outro jeito ("em Boa Viagem", "Boa Viagem, Recife", só rua e número), **não muda nada**. Testes com o
   texto real da rodada 2 e com 5 textos certos; um teste roda a guarda dentro do turno (IA falsa).
   O prompt não mudou. O teste antigo da ordem das guardas (`test_m3_n4_ordem.py`) ganhou o passo novo.

### O que já funcionava (só ganhou teste)
- Passo desligado cancela na hora de enviar ("passo_desligado").
- A ação `avisar_vendedor` existia (só o destino e o texto mudaram).

### Fim do RG1
- Suíte offline (3 partes seguidas): 935 + 1263 + 1133 = **3331 passaram**, 0 falhas (+34: os 33 do RG1 e
  o cenário "atrasado" do S6). A 1ª rodada teve 6 falhas, todas de testes que fixavam o que o RG1 mudou de
  propósito: a régua antiga (5 em `test_etapa2_bloco5.py`: 6 passos e avaliação em 30 dias) e a lista de
  guardas (`test_sg1_pacote_de_ramo.py::test_ordem_n4_nao_mudou`). Atualizei esses testes para a régua e a
  lista novas (o que mais conferem não mudou) e rodei a suíte inteira de novo.
- Sem Gemini, sem canal real, sem migração. O prompt do Léo e o do redator não mudaram.
- Branch `regua-1`, tag `rg1`.
- **Para o analista decidir:** (1) copiar a régua nova (15 dias, conferir a transferência) nas lojas que já
  existem; (2) o remarketing não tem limite por dia (só por mês e por rodada); (3) a categoria do
  `pos_venda_acompanhamento` ("a confirmar"); (4) a regra de 3 dias de atraso vale só para o remarketing
  (o pós-venda já tinha a sua, na hora de agendar: passo que já passou de 3 dias não é agendado).
- GitHub Actions da 1ª versão: 1 falha (`test_a_trava_e_a_mesma_do_atendimento`, "Event loop is closed"):
  o teste usava o Redis assíncrono, que fica preso ao 1º laço de eventos (problema já conhecido do IG1); no
  computador passou pela ordem dos testes. O teste agora confere a mesma chave pelo cliente síncrono. Suíte
  inteira de novo: mesmo resultado (3331 passaram). A tag `rg1` foi movida para o commit do conserto.

---

## Merge do RG1 (27/11/2026)
Merge na `main` (commit `f92e4c6`), suíte 935 + 1263 + 1133 = **3331 passaram**; push e tag `agente-rg1`.
Docker religado a partir da `main`: 9 peças saudáveis.

## RG2 — Limite diário, cópia da régua com confirmação (branch `regua-2`, saiu da `main` f92e4c6)

Sem Gemini, sem canal real, sem migração. Prompts do Léo e do redator intocados.

### 1. Limite diário do remarketing
- Configuração nova da loja **`remarketing.max_por_dia`**, padrão **50**, dono: operador (0 a 5.000; 0 = não
  envia). Aparece em **Plano e limites**, junto do limite mensal e do diário da reativação
  (`app/config_tela.py`).
- Conta os toques **enviados** no dia (no modo simulação, também os **simulados**), no **dia da loja**
  (fuso da loja: 22:30 de terça em Recife é terça, mesmo já sendo quarta em UTC).
- Ao atingir, o remarketing **para nesta loja até o dia seguinte**; os que ficaram não contam como falha
  nem erro. Os outros limites continuam: 10 por rodada e o limite do mês.
- Testes: `tests/test_rg2_regua.py` (padrão e campo; para no limite; volta no dia seguinte; dia da loja;
  simulação; duas lojas; zero).

### 2. Copiar a régua só com confirmação
- `regua.previa_da_copia(loja, modelo)` diz **antes** quantos passos agendados serão cancelados.
- `regua.copiar_regua_modelo(...)` agora **cancela na hora** os agendados da régua anterior (motivo
  **`regua_trocada`**, o mesmo do RG1) e **só copia com `confirmar=True`**; sem isso, recusa com a mensagem
  "Copiar a régua 'X' cancela N passo(s) agendado(s). Confirme para seguir." e nada muda. A criação da
  régua de uma loja nova (`garantir_regua`) passa `confirmar=True` (não há nada agendado).
- Script novo **`scripts/copiar_regua.py`**: `--loja N` ou `--todas`, `--modelo` (sem ele: a régua que a
  loja já usa, ou a padrão), `--confirmar`. Sem `--confirmar`, mostra a prévia e pergunta (só copia com
  "SIM").
- **Tela do operador:** não existe tela de copiar régua (procurei nas páginas do operador: só a criação
  da loja copia, por dentro). Fica só o script.
- Testes: prévia sem confirmar não muda nada; com confirmação cancela com `regua_trocada`; loja B
  intacta; o script pergunta e só copia com SIM; `--todas --confirmar` usa a régua de cada loja; a régua
  nova tem os passos do RG1; **o reinício da demo cria a régua nova** (o reinício apaga a régua da demo e
  a cria de novo a partir do `reguas.json`).
- Teste antigo ajustado: o do RG1 que copiava a régua sem confirmar agora passa `confirmar=True`.

### 3. A régua nova em TODAS as lojas existentes (todas fictícias, banco deste computador)
Rodado: `python scripts/copiar_regua.py --todas --confirmar` (código desta branch, banco de uso local).
| Loja | Nome | Régua antes | Régua copiada | Agendados cancelados (regua_trocada) |
|---|---|---|---|---|
| 1 | Loja 1 | proxima (6 passos, versão antiga) | proxima (7 passos) | 0 |
| 2 | Auto Center Teste | nenhuma | proxima (7 passos) | 0 |
| 3 | Loja Prática | nenhuma | proxima (7 passos) | 0 |
| 4 | Recife Seminovos Demo | proxima (6 passos, versão antiga) | proxima (7 passos) | **20** |
Conferido depois: as 4 lojas com a "proxima" de 7 passos (avaliação em 15 dias, conferir a transferência)
e nenhum agendado da régua antiga. **A demo ficou sem pós-venda agendado** até o próximo reinício
(`docker compose exec -T api-painel python scripts/reiniciar_demo.py`; com o Gemini, ou com
`--sem-indexar`), que cria tudo de novo já com a régua nova (teste acima). Não reiniciei a demo agora
porque o reinício normal indexa com o Gemini (proibido neste bloco).

### 4. Categoria do acompanhamento de 7 dias
- **Decisão do analista:** `pos_venda_acompanhamento` fica **"marketing"** até a Meta aprovar; depois, vale
  a categoria que a Meta der.
- **O sistema já guarda a categoria que a Meta der?** Em parte. A tabela `modelos_loja` tem a coluna
  `categoria_efetiva` e o custo já usa ela no lugar da do arquivo (`app/templates.categoria_para_custo`).
  Mas **nada grava essa coluna sozinho**: não há tela, script nem aviso da Meta (webhook de status de
  modelo) que a preencha; a função `templates.registrar_status(..., categoria_efetiva=...)` existe e só os
  testes a chamam. **Pendência para o bloco da Meta:** receber o status/categoria do modelo (webhook
  `message_template_status_update`) ou dar ao operador um jeito de registrar.

### Fim do RG2
- Suíte offline (3 partes seguidas): 935 + 1263 + 1148 = **3346 passaram**, 0 falhas (+15 do RG2).
- A 1ª rodada da suíte teve 1 falha que era **erro meu**, e o teste acertou: o campo novo estava na tela
  como "do operador", mas faltava na regra do SERVIDOR (`app/lojas.CHAVES_DO_OPERADOR`); sem isso, o
  lojista poderia aumentar o próprio limite pela API. Consertado (e um teste do RG2 confere).
- Testes antigos ajustados: `test_s4a_configuracao.py` (a lista de campos do Plano e limites ganhou o
  limite diário: 25 -> 26) e o do RG1 que copiava a régua sem confirmar.
- Branch `regua-2`, tag `rg2`.

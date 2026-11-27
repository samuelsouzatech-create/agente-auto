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

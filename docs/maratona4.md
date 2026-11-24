# Maratona 4 — Segmentos e Instagram — diário

Sete blocos em cadeia: AR → SG1 → SG2 → IG0 → IG1 → IG2 → IG3. Branches `arrumacoes` (saiu da
main `dd802e1`, que tem o merge da Maratona Docker e a tag `agente-docker`) → `segmentos-1` →
`segmentos-2` → `instagram-0` → `instagram-1` → `instagram-2` → `instagram-3`. Tags `ar`, `sg1`,
`sg2`, `ig0`, `ig1`, `ig2`, `ig3`. Sem merge na main.

Regras da maratona: sem Gemini/IA real (sem `-m api`, sem bancada), sem canal real (WhatsApp,
Telegram, Meta/Instagram), sem túnel, só dados fictícios. Ler a documentação oficial da Meta
foi permitido (IG0). `.env`, senhas e tokens nunca aparecem aqui nem no Git. Script de manter
o computador acordado ligado no começo (24/11, 15:42) e desligado no fim.

| Bloco | Branch | Situação | Suíte (3 partes) |
|-------|--------|----------|------------------|
| AR arrumações | arrumacoes | feito (16:20) | 3.002 ok (798 + 1.228 + 976) |
| SG1 motor × pacote de veículos | segmentos-1 | feito (16:40) | 3.020 ok (802 + 1.242 + 976) |
| SG2 catálogo e ramo de teste | segmentos-2 | feito (16:50) | 3.034 ok (802 + 1.242 + 990) |
| IG0 documentação da Meta | instagram-0 | feito (17:00) | 3.037 ok (802 + 1.231 + 1.004) |

## Contradições com o roteiro, anotadas no começo (não graves: segui este pedido)
- `docs/decisoes_e_roteiro.md`, seção 3: o pacote de ramo "não se faz agora; quando o segundo
  ramo for real", porque "desenhar para um ramo imaginário costuma errar". Este pedido manda
  fazer o SG1/SG2 agora, com um ramo de teste fictício. Segui o pedido (é a decisão mais
  recente). Cuidado que vale anotar: o contrato do pacote foi desenhado com UM ramo real e um
  ramo de teste; quando o segundo ramo real chegar, o contrato provavelmente vai crescer.
- Mesma seção 6 e 7: o Instagram vinha "depois da primeira loja". Este pedido adianta o código
  do Instagram (sem conta real). Segui o pedido.
- `docs/plano_mestre.md`, I4: o texto padrão do comentário tinha emoji ("... te ajudar 🙂").
  A regra do L10 (e deste pedido) proíbe emoji no que o cliente recebe. Segui o pedido: sem emoji.

## AR — Arrumações (branch arrumacoes)

### 1. Painel Streamlit do cliente aposentado
Decisão do analista: pela D11 do plano mestre ("Configuração fica com o operador no piloto"), o
operador faz Configuração, Conhecimento e Equipe pelo lojista; o resto já está no painel novo.

**Prova de que o operador não usava as telas (antes de apagar):** busca em `operador.py`,
`paginas/` (inclusive `paginas/operador/`), `app/`, `scripts/`, `docker/`, `docker-compose.yml`,
`Dockerfile`, README e `docs/demo.md`. As 8 telas do cliente (`paginas/handoff.py`,
`conversas.py`, `resultados.py`, `envios.py`, `estoque.py`, `configuracao.py`,
`conhecimento.py`, `usuarios.py`) só apareciam em `paginas/menu.py` (lista `CLIENTE`, usada só
pelo `painel.py`) e em testes. O operador usa só `paginas/comum.py`, `paginas/menu.py`
(`GERAL`/`LOJA`), `paginas/form_config.py`, `paginas/operador_sessao.py` e `paginas/operador/*`.
`app/acesso.py` (`loja_do_cliente`, `PainelSemLoja`) só era usado pelo `painel.py`. O
`painel.py` não estava no Docker (o DK2 já tinha visto isso).

**Removidos:** `painel.py`, `app/acesso.py` e as 8 telas. Em `paginas/menu.py` saíram a lista
`CLIENTE` e a função `montar` (só o painel do cliente usava). Em `paginas/comum.py` saiu
`iniciar_sessao_cliente`; o papel "cliente" continua como o de menos poder (sem a marca de
operador, a tela para).

**Testes:** os testes que só conferiam as telas do cliente (abrir o `painel.py`, compilar as
telas, `LOJA_ID`, menu do cliente) saíram ou viraram "a tela não existe mais". Os testes das
regras em `app/` que essas telas usavam (configuração do cliente × operador, isolamento por
loja, usuários, conhecimento, pausa, envios) continuam. Novo: `test_s10b_limpeza.py` confere
que os 10 arquivos não existem e que nada do operador cita ou importa algum deles.

**Referências:** README (tabela de portas e a seção do painel do cliente). `docs/demo.md` e o
Docker não citavam o `painel.py` (nada a mudar). `docs/docker.md` é diário antigo: não mexi.

### 2. Teste de carga com gaveta própria do Redis
`tests/conftest.py`: com `-m carga`, o Redis passa para a **gaveta 14** (ou `REDIS_URL_CARGA`),
esvaziada no começo, e a rodada **recusa** começar se a gaveta for a 0 (de uso). A suíte normal
continua na 15. Testes novos em `tests/test_dk2_redis_de_teste.py` (carga na 14 e esvaziada;
recusa a 0, inclusive endereço sem número de gaveta; o endereço troca só a gaveta).
Prova prática: antes, gaveta 0 = 2 chaves (do relógio ligado), 14 = 0; rodei
`pytest -m carga tests/test_pg3_carga.py` (passou, 16,8 s); depois, gaveta 0 = as mesmas 2
chaves, 14 = 699 (as da carga).

### 3. Teste instável `test_s10b_limpeza.py::test_excecoes_usam_o_indice`
Agora aceita o índice da exceção (`idx_mensagens_direcao_canal`) **ou qualquer índice de
`mensagens` que comece por `loja_id`** (lido do próprio banco em `pg_indexes`; hoje
`idx_mensagens_loja` e `idx_mensagens_loja_direcao`). O arquivo rodou **5 vezes seguidas: 7
passaram nas 5**.

### 4. Portas documentadas
README: tabela "Peças fora do Docker" com operador 8502, simulador 8501, webhook 8000 com o
comando escrito (`python -m uvicorn app.api.webhook:app --host 127.0.0.1 --port 8000`), API
8001 e o relógio. `operador.py`: o comando do topo dizia 8501; agora 8502, com as outras portas.

### Testes do AR
- Suíte inteira contra o PostgreSQL, em 3 partes: 798 + 1.228 + 976 = **3.002 passaram, 0
  falhas**. (O DK3 tinha 3.021: saíram os testes que só abriam ou compilavam as telas do painel
  aposentado, entraram os novos da gaveta 14 e da aposentadoria.)
- Lição anotada: na 1ª tentativa rodei um arquivo de teste AO MESMO TEMPO que a suíte; cada rodada
  recria o banco `_teste` e derrubou a outra (erros "terminating connection" e "relation does not
  exist" no `test_l10`). Não era defeito do código. Refeita sozinha, passou. Também apareceram 7
  testes antigos que liam as telas apagadas por caminhos que a minha 1ª busca não pegou
  (`os.path.join`, `RAIZ / "paginas" / ...`): viraram "a tela saiu".
- Os arquivos `tests/prompt_de_referencia.py` e `tests/dados/prompt_veiculos_antes_do_sg1.json`
  entraram nesta branch: são a "foto" do prompt de uma loja de carros tirada com o código de ANTES
  do SG1 (usada no SG1 para provar que nada mudou). Não são testes (o pytest não os coleta).

## SG1 — Motor separado do pacote de veículos (branch segmentos-1, saiu da arrumacoes)

### 1. Mapa: o que é de carro e morava fora de `segmentos/veiculos/` (antes do SG1)
| Item | Onde estava | Destino | Situação |
|---|---|---|---|
| Guarda do estado do carro (`cortar_estado_inventado`, `ESTADO_AFIRMADO`, `FRASE_ESTADO`, "garanto que", "único dono"...) | `app/guarda_politica.py` | `segmentos/veiculos/guardas.py` (gancho, passo 8 da N4) | **movida** |
| Elogio ao estado do carro da foto do cliente (`tirar_elogio_do_estado`, `FRASE_FOTO_CARRO`) | `app/guarda_politica.py` | `guardas.py` (gancho, passo 7) | **movida** |
| Descrição da foto sem "bem conservado" (`tirar_elogio_da_descricao`) | `app/guarda_politica.py` (usada em `turno.py` e `imagens.py`) | `guardas.py` (gancho) | **movida** |
| Valor da troca e "aceita troca?" (`pediu_valor_da_troca`, `pergunta_se_aceita_troca`, motivos, leitura de `aceita_troca` do cadastro) | `app/guarda_politica.py` e `app/core/turno.py` | `guardas.py` (gancho `motivo_do_chamado`, começo do passo 10) | **movida** |
| Test-drive lembra a CNH (`FRASE_CNH`) | `app/guarda_politica.py` + `app/core/pos_processamento.py` | `guardas.py` (gancho `depois_da_agenda`, fim do passo 9) | **movida** |
| Foto do carro anotada na troca (`_anotar_foto_na_troca`, tabela `trocas`) | `app/core/turno.py` | `guardas.py` (gancho `anotar_foto_do_cliente`) | **movida** |
| Quais ferramentas são a "ficha" do carro | `app/core/turno.py` (nomes fixos) | `ferramentas.py` (`FERRAMENTAS_DE_FICHA`) | **movida** |
| Categorias SUV/sedã/hatch/picape | `app/categorias.py` | `segmentos/veiculos/categorias.py` | **movida** |
| Ferramentas de carro: `consultar_estoque` (km, câmbio, categoria), `detalhes_veiculo`, `registrar_troca` (km) | `tools/` | `segmentos/veiculos/` | **movidas** |
| Guia dessas 3 ferramentas no prompt (`DESCRICOES`) | `app/core/montagem.py` | `ferramentas.py` (`DESCRICOES`) | **movido** |
| Nomes de ferramenta de carro nas listas do motor (`registrar_troca` em "recebe o cliente" e "grava algo") | `app/core/agent.py`, `app/core/turno.py`, `app/sombra.py` | `ferramentas.py` (`FERRAMENTAS_COM_LEAD_ID`, `FERRAMENTAS_QUE_GRAVAM`) | **movidos** |
| Linha "Troca: a loja aceita carro..." da IDENTIDADE (`TEXTO_ACEITA_TROCA`) | `app/core/montagem.py` | `segmentos/veiculos/textos.py` (`linhas_da_identidade`) | **movida** |
| 5 trechos de carro do prompt comum (honestidade: "carro, preço, quilometragem"; "um carro sem fotos"; "se o carro tem foto"; "Carro do cliente..."; "Print de anúncio...") | `prompts/base.md` | `textos.py` (`TRECHOS_DO_PROMPT_BASE`), marcados `{{ramo:...}}` no base | **movidos** |
| Ramo padrão "veiculos" escrito em 2 lugares | `app/core/montagem.py`, `app/cliente_da_casa.py` | `app/segmentos.py` (`RAMO_PADRAO`, o único lugar) | **feito** (o `criar_loja` de `app/lojas.py` continua com o padrão "veiculos" no parâmetro) |
| Prompt do ramo, quem já comprou, modelos de mensagem, réguas | já estavam em `segmentos/veiculos/` (Etapa 2) | — | já estava |
| Guarda de preço: "90 mil km", "rodou", "quilometragem", "placa" não são dinheiro | `app/guarda_politica.py` | **fica no motor** | distância e placa não são dinheiro em nenhum ramo (imóvel: "a 2 km da praia"); LEGADO justificado |
| Pedido de entrega: "entregar a picape/o SUV" | `app/guarda_politica.py` (L8) | o vocabulário do item deveria vir do ramo | **não movido**: a guarda não recebe a loja; LEGADO |
| Vocabulário "carro/civic/corolla..." que nunca é "pedaço solto" | `app/guarda_politica.py` (`_PALAVRA_DE_CARRO`, usado pela guarda de fragmentos do motor) | idem | **não movido** (eu tinha movido e a guarda de fragmentos quebrou; voltou para o motor e o ramo importa de lá) |
| Leitura da foto do cliente (prompt "loja de carros", tipo CARRO, km/placa) | `app/imagens.py` | o ramo entregar o prompt da leitura | **não movido**; LEGADO (só faz sentido com um 2º ramo real que leia fotos) |
| Tabela `estoque` (km, câmbio), `app/estoque.py`, `app/estoque_conhecimento.py` | `app/` | catálogo do ramo (SG2) por cima | **fica**: a tabela e a API /estoque não mudam (pedido do SG2); LEGADO |
| API do painel: estoque e ficha da troca (km, câmbio) | `app/api_painel/carros.py`, `rotas_estoque.py`, `app/painel_leitura.py` | — | **fica**: contrato da API v1 não muda; LEGADO |
| Venda aponta para o carro (`vendas.veiculo_id`) | `app/vendas.py`, jobs de pós-venda/remarketing | catálogo (SG2) | SG2 |
| Loja de demonstração (carros fictícios, placa, km) | `app/demo.py` | `segmentos/veiculos/demo` (futuro) | **não movido**; LEGADO |
| Campo "Revisão a cada quantos km" (pós-venda) | `app/config_tela.py`, `app/lojas.py` | `segmentos/<ramo>/configuracao.py` (previsto no contrato) | **não movido**; LEGADO |
| Roteiros da bancada (52 de carro) | `bancada/roteiros/` | `segmentos/veiculos/bancada/roteiros/` | **não movidos**: a bancada não pode rodar nesta maratona para provar |
| Textos ao cliente com a palavra "carro" (ex.: espera do vendedor, avisos de módulo, mensagens fixas da foto, pós-venda) | ~40 arquivos de `app/` e `tools/` | — | **não tocados** (ver "o que a catraca não olha") |
| Câmbio do dólar (`cambio.usd_brl`) | `app/custos.py`, `app/precos.py` | — | **falso alarme**: não é carro; LEGADO permanente |

### 2. Contrato do pacote de ramo
Escrito em `docs/pacote_de_ramo.md`: o que todo ramo entrega (prompt, ferramentas, guardas,
textos, catálogo, quem já comprou, configuração, modelos, réguas, roteiros) e por onde o motor
chama cada coisa. O motor fala com o ramo só por `app/segmentos.py`:
- `gancho(ramo, arquivo, nome)`: a função do ramo, lida **na hora da chamada** (um teste que troca
  a função no módulo do ramo vale para o motor). Sem o gancho: `None`, e o passo não faz nada.
- `ramo_da_loja(loja)` / `ramo_da_loja_id(loja_id)`: o ramo da loja (sem ramo gravado ou loja
  ilegível: `RAMO_PADRAO`, como era antes).
- `NomesDoMotorEDosRamos`: listas de nomes de ferramenta (recebe a loja, recebe o cliente, grava
  algo, é ficha) = as do motor + as que cada ramo **já carregado** declara. Assim o motor nunca
  carrega um ramo à toa (o SG2 prova que uma loja de imóveis não carrega o pacote de veículos).
- Os arquivos do ramo são importados como pacote Python, com o nome montado na hora
  (`segmentos/__init__.py` e `segmentos/veiculos/__init__.py` novos). Editou o arquivo do ramo:
  vale na próxima mensagem (recarrega), como antes.

### 3. A ordem das guardas (N4) não mudou
A lista `PASSOS` é a mesma, nos mesmos 19 nomes e na mesma ordem (teste novo confere). Os passos 7
(`elogio_da_foto`), 8 (`estado_sem_ficha`), o fim do 9 (CNH) e o começo do 10 (troca) chamam o
gancho do ramo no mesmo lugar. O ramo da loja é lido uma vez por turno (1 consulta a mais, a mesma
que a leitura de "aceita troca" já fazia).

### 4. Catraca de ramo (`tests/test_catraca_ramo.py`)
- Reprova `import`/`from segmentos.<ramo>` em `app/` e `tools/`, e o texto `segmentos.veiculos`.
- Palavras de carro procuradas (sem acento, palavra inteira): km, kms, quilometragem, quilômetro(s),
  rodagem, câmbio, SUV(s), sedã(s)/sedan(s), hatch(s)/hatchback, picape(s), pickup, placa(s).
- **LEGADO** (só pode diminuir), 26 pares (arquivo, palavra) em 12 arquivos, cada um com o porquê
  no próprio teste. Resumo: API, estoque, demo e troca no painel (contrato v1 não muda: 14); guarda de
  preço (distância e placa não são dinheiro em nenhum ramo: 5); câmbio do dólar (2, falso alarme
  permanente); entrega "picape/SUV" (2); leitura da foto (2); campo de revisão em km (1).
  Antes do SG1 eram 17 arquivos; saíram `app/categorias.py`, as 3 ferramentas, `montagem.py`,
  e `filtro_remarketing.py` (só um comentário).
- **O que a catraca NÃO olha (anotado de propósito):** as palavras "carro" e "veículo". Ainda
  aparecem em **44 arquivos** de `app/` e `tools/`, quase sempre em texto que o cliente lê
  ("Esta loja não envia fotos... ofereça a ficha do carro") ou em nomes de coluna que o contrato
  mantém (`veiculo_id`). Pôr essas palavras na lista daria um LEGADO de ~44 arquivos; tirá-las de
  verdade é trocar textos que o cliente recebe (mudança de comportamento, que exige rodada com IA
  real, proibida nesta maratona). Fica para o bloco do 2º ramo real.

### 5. Regra de ouro: o comportamento das lojas de carro não mudou
- **O prompt:** `tests/prompt_de_referencia.py` montou o prompt de uma loja de carros em 13
  situações (padrão, troca sim/não/não informado, módulos ligados/desligados, as 3 esperas do
  vendedor, primeiro contato formal, cliente da casa, retomada, recados, loja fechada) **com o código
  de antes do SG1** e guardou em `tests/dados/prompt_veiculos_antes_do_sg1.json`. Depois do SG1
  o teste monta de novo e compara: **iguais letra por letra, e as mesmas ferramentas na mesma
  ordem.**
- **Os testes das guardas e do turno só mudaram o import** (de onde vem a função): os arquivos de
  teste (18 arquivos) mudaram a linha `from ... import` (`app.guarda_politica`/`tools`/`app.categorias` →
  `segmentos.veiculos...`) ou o alvo do `monkeypatch` (`turno.cortar_estado_inventado` →
  `guardas_veiculos.cortar_estado_inventado`).
- **Casos limítrofes, para o analista conferir (o que o teste espera NÃO mudou):**
  1. `tests/test_m3_n4_ordem.py::test_guardas_linha_a_linha...`: confere que cada guarda é
     definida com `@_mantem_linhas`. Duas delas agora estão em `segmentos/veiculos/guardas.py`;
     o teste passou a ler o motor **e** o arquivo do ramo. A lista das 8 guardas e a regra não mudaram.
  2. `tests/test_l5_fotos.py::test_prompt_proibe_valor_pela_foto`: lia o `base.md` cru; agora lê
     o base **montado para uma loja de carros** (`base_do_ramo`). As 4 frases esperadas são as mesmas.
  3. `tests/test_l12_limpeza_e_acao.py::test_bancada_falha_estado_sem_ficha`: não mudou; quem
     mudou foi a bancada (`scripts/rodar_bancada.py`), que voltou a guardar a SUA referência da
     guarda do estado (antes ela vinha de outro módulo; desligar a do turno não desligava a da
     bancada).
- **Não rodei a bancada nem `-m api`** (proibido nesta maratona). A prova é: prompt igual letra
  por letra + guardas com o mesmo código, chamadas no mesmo lugar + a suíte inteira.

### Testes novos do SG1
`tests/test_sg1_pacote_de_ramo.py` (16): prompt igual ao de antes; o `base.md` não tem mais carro
e o ramo preenche; motor e teste recebem o mesmo módulo do ramo; gancho inexistente é `None`; ordem
N4; nomes de ferramenta do ramo carregado; loja de carro corta estado inventado e elogio da foto;
**duas lojas de ramos diferentes** (carro e um ramo de mentira só com prompt): a de carro corta,
a outra não ganha nenhuma guarda de carro; a ficha vem do ramo; CNH pelo gancho; troca antes das
regras do motor; o motor não tem mais as guardas de carro; o contrato está escrito.
`tests/test_catraca_ramo.py` (4): sem import de ramo, sem palavra nova, LEGADO só diminui, a
catraca pega o que deve.
- Suíte inteira contra o PostgreSQL, 3 partes: 802 + 1.242 + 976 = **3.020 passaram, 0 falhas**
  (3.002 do AR + 18 novos).

## SG2 — Catálogo e um ramo de teste (branch segmentos-2, saiu da segmentos-1)

### 1. Catálogo
- `app/catalogo.py` (motor): a interface (`buscar`, `detalhar`, `disponivel`, `fotos`, `parecido`,
  `precos`, `citados_no_texto`), o `Item` e o `catalogo_da_loja(loja_id)` (pelo gancho do ramo).
  Tabela no `docs/pacote_de_ramo.md`.
- `segmentos/veiculos/catalogo.py`: o estoque, **com as mesmas consultas** que o motor fazia direto.
  A tabela `estoque`, a API `/estoque` e o contrato do painel **não mudaram**.
- Passaram a falar com o catálogo: `tools/enviar_fotos.py` (busca e fotos), o filtro de preço do
  remarketing (`app/filtro_remarketing.py`, preço do item de interesse e do parecido) e o
  remarketing (`app/jobs/remarketing.py`: item de interesse e o parecido do vendido, mesma regra
  dos 20%). Nenhum desses três tem mais `FROM estoque` (teste confere).
- **Continuam lendo o estoque direto (anotado, não mudei):** `app/vendas.py` (o único caminho de
  venda lê o carro e marca "vendido" na MESMA transação; passar pelo catálogo quebraria essa
  transação), `app/implantacao.py` (checklist do operador: conta carros), `app/painel_leitura.py`
  e `app/reativacao.py` (o que o painel/relatório mostra da venda), `app/estoque*.py`, `app/demo.py`
  e a API do painel (contrato v1). Ficam para quando o estoque virar catálogo também na API.

### 2. A venda continua apontando para o carro
Sem migração: `vendas.veiculo_id` e `interesse_veiculo.veiculo_id` continuam como estão; o motor,
quando precisa do item, pergunta ao catálogo pelo id. A migração 22 não foi usada.

### 3. Ramo de teste fictício: `segmentos/_exemplo_imoveis/`
- `prompt.md` curto (imobiliária), `imoveis.json` (3 imóveis: 2 disponíveis, 1 vendido),
  `catalogo.py` (lê o JSON), `ferramentas.py` (`consultar_imoveis`) e **1 guarda própria**
  (`guardas.py`: "documentação ok", "sem infiltração", "escritura garantida" viram "A documentação
  e o estado do imóvel o corretor confirma com você.", pelo gancho `cortar_estado_inventado`).
- **Escondido:** a pasta começa com `_`. `app/segmentos.py` só enxerga ramo oculto com
  `RAMOS_OCULTOS_LIGADOS = True`, que só os testes ligam. `criar_loja(..., segmento="_exemplo_imoveis")`
  é recusado fora dos testes (teste confere). Não vira produto.

### 4. Testes do SG2 (`tests/test_sg2_catalogo_e_ramo_de_teste.py`, 14)
- O ramo de teste não é opção para loja real; só com a chave dos testes; o operador não o lista.
- Catálogo de carro = estoque e não mistura lojas; parecido e preços; itens citados num texto;
  ramo sem catálogo usa o vazio; a ferramenta de fotos pergunta ao catálogo (espião); ferramentas e
  guardas do motor sem `FROM estoque`.
- Loja do ramo de teste, pelo `executar_turno` com IA falsa e o grafo de verdade: **busca no
  catálogo** (`consultar_imoveis`; o prompt é da imobiliária e não tem `consultar_estoque`),
  **abre chamado ao humano** (handoff `aguardando_humano`), **guarda própria** troca a frase, **faz
  retomada** (o remarketing de verdade, envio falso; a próxima mensagem do cliente chega ao Léo com
  "RETOMADA QUE VOCÊ MANDOU" no prompt).
- **Nada de `segmentos/veiculos` é carregado:** um processo Python NOVO cria a loja de imóveis,
  roda 2 turnos (catálogo, guarda, chamado) e, no fim, a lista de módulos carregados com
  "veiculos" no nome está **vazia**.
- **Duas lojas de ramos diferentes ao mesmo tempo** (4 turnos juntos, 2 de cada): cada uma usa a
  sua ferramenta e o seu catálogo; nenhuma resposta nem mensagem cruza de loja.
- Suíte inteira, 3 partes: 802 + 1.242 + 990 = **3.034 passaram, 0 falhas** (3.020 + 14).

## IG0 — Documentação oficial da Meta (branch instagram-0)

Lida em 24/11/2026 nas páginas oficiais (developers.facebook.com). "Confirmado" = a página diz
isso com todas as letras. "Não confirmado" = não achei escrito; vira configuração com o padrão
mais seguro, marcada "a confirmar". A documentação da Meta muda com frequência: conferir de novo
antes da conta real. Versão da API citada nas páginas: **v27.0**.

Páginas lidas:
- [P1] https://developers.facebook.com/docs/instagram-platform
- [P2] https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login
- [P3] https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api
- [P4] https://developers.facebook.com/documentation/instagram-platform/webhooks/examples
- [P5] https://developers.facebook.com/documentation/instagram-platform/webhooks/setup
- [P6] https://developers.facebook.com/docs/instagram-platform/private-replies
- [P7] https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/comment-moderation
- [P8] https://developers.facebook.com/docs/instagram-platform/reference/instagram-media
- [P9] https://developers.facebook.com/docs/messenger-platform/policy/policy-overview
- [P10] https://developers.facebook.com/documentation/instagram-platform/app-review
- [P11] https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback
- (https://developers.facebook.com/docs/messenger-platform/instagram abriu só o menu, sem texto útil)

| Assunto | O que a documentação diz | Situação | Link |
|---|---|---|---|
| Qual API | Três jeitos: "Unified Login" (chamado de recomendado para integrações novas), **login do Instagram** (não precisa de Página do Facebook) e **login do Facebook** (a conta do Instagram precisa estar ligada a uma Página). | confirmado | P1, P2 |
| Login do Instagram: limite | "This API setup cannot access ads or tagging." | confirmado | P2 |
| Endereço | Login do Instagram: graph.instagram.com. Login do Facebook/Unified: graph.facebook.com. | confirmado | P6, P5 |
| Permissões (login do Instagram) | instagram_business_basic, instagram_business_manage_messages, instagram_business_manage_comments | confirmado | P3, P10 |
| Permissões (login do Facebook) | instagram_basic, instagram_manage_messages, instagram_manage_comments, pages_read_engagement (ads_* só com papel no Business Manager). `pages_messaging` não aparece. | confirmado em parte | P6, P10 |
| Mensagem recebida (formato) | `object: "instagram"`; `entry[].id` = conta da loja; `entry[].time`; `entry[].messaging[]` com `sender.id`, `recipient.id`, `timestamp`, `message.mid`, `message.text` | confirmado (só com marcadores, sem exemplo com valores) | P4 |
| Eco (`is_echo`) | `message.is_echo: true` "when the message was sent by your app user"; no eco, `sender.id` é a loja e `recipient.id` o cliente | confirmado (o campo) | P4 |
| Eco de resposta feita no app do Instagram | a página não diz com todas as letras que o eco vem também quando o vendedor responde pelo app | **não confirmado** | P4 |
| Eco diz qual app mandou (`app_id`) | não aparece em nenhuma página | **não confirmado** (por isso o Léo descarta o próprio eco pelo id da mensagem, `mid`, e não por `app_id`) | — |
| Webhook de comentários (post comum) | campo `comments`; `value.id` (comentário), `value.from.id`, `value.from.username`, `value.text`, `value.media.id`, `value.media.media_product_type`. Um exemplo põe `field`/`value` direto no `entry`; outro dentro de `entry[].changes[]` (com `parent_id`). | confirmado (com as duas formas) | P7, P4 |
| Comentário em anúncio pago | login do Facebook: `media.ad_id`, `ad_title`, `original_media_id` "included if the comment was on an ad post"; anúncio dinâmico não traz o id do anúncio. Login do Instagram: sem campo de anúncio (e "cannot access ads"). | confirmado em parte (só com login do Facebook) | P4, P5, P2 |
| Comentários: acesso | "Advanced Access is required for comments" e a conta precisa ser pública | confirmado | P5 |
| Resposta privada: como | `POST /<id da conta>/messages` com `{"recipient":{"comment_id":...},"message":{"text":...}}`; volta `recipient_id` e `message_id` | confirmado | P6 |
| Resposta privada: prazo | "within 7 days of the creation time of the comment" (Live: só durante a transmissão) | confirmado | P6 |
| Resposta privada: quantas | "Only one message can be sent to the commenter." | confirmado | P6 |
| Se a pessoa não responder | não pode mandar mais nada; mais mensagens "only ... if the recipient responds, and must be sent within 24 hours of the response" | confirmado | P6 |
| Vale para anúncio/reel/story | a resposta privada vale para comentário em "post, reel, story, Live, or ad post" | confirmado | P6 |
| Permissão da resposta privada | a tabela da página lista só basic + manage_comments para o login do Instagram (o envio pelo /messages costuma pedir manage_messages) | **não confirmado** (página incoerente; pedir as duas) | P6 |
| Resposta pública | `POST /<id do comentário>/replies` com `{"message": "..."}`; volta `{"id": ...}`; permissão manage_comments | confirmado | P7 |
| Tamanho da resposta pública | não diz | **não confirmado** | P7 |
| Ler a legenda do post | `GET /<id do post>?fields=caption,...`; a tabela marca `caption` como "Available for Instagram API with Facebook Login only" | confirmado **só com login do Facebook** | P8 |
| Tamanho do texto da mensagem | "Message text must be UTF-8 and be a 1000 bytes or less." | confirmado | P3 |
| Janela de 24 h | "For most user actions, it lasts 24 hours." | confirmado | P9, P3 |
| Exceções da janela | anúncio Click-to-Direct: até 7 dias da primeira mensagem; humano (Human Agent): janela separada de 7 dias, com a marcação de humano. One-time notification, mensagens patrocinadas e notícias "not available for IG Messaging API". | confirmado | P9, P3 |
| Nome exato da marcação de humano (`HUMAN_AGENT`) | o texto não aparece nas páginas lidas | **não confirmado** | — |
| Revisão do app | "must complete App Review before it can request permissions with Advanced Access"; pede vídeo, passos para o revisor, ao menos 1 chamada que deu certo, política de privacidade e ícone. Para uma empresa própria, Standard Access basta; para atender várias lojas (nosso caso), Advanced. | confirmado | P10 |
| Verificação da empresa | login do Instagram: "Required for production access" | confirmado | P5 |
| Exclusão de dados | URL HTTPS no campo "Data Deletion Request URL"; recebe POST com `signed_request` (assinatura HMAC-SHA256 com o segredo do app, no código de exemplo); responde `{ url, confirmation_code }` | confirmado (página geral do Facebook) | P11 |
| Assinatura do webhook | `X-Hub-Signature-256: sha256=...`, assinatura SHA256 do corpo com o App Secret | confirmado (a palavra HMAC não aparece no texto; o jeito de calcular é o mesmo do WhatsApp) | P5 |
| Verificação GET | `hub.mode=subscribe`, `hub.verify_token` igual ao do painel, responder `hub.challenge` | confirmado | P5 |
| Resposta e repetição | responder 200; lotes de até 1000 avisos; a Meta tenta de novo por até 36 h (tratar repetidos) | confirmado | P5 |

### Recomendação: login do Facebook (ou o Unified, que usa o mesmo endereço)
Para o que o Léo precisa, o **login do Facebook** ganha:
1. A Opção B do IG2 (a mensagem que sabe do carro) precisa ler a **legenda do post**, e a página
   diz que `caption` é "Facebook Login only".
2. **Comentário em anúncio** (IG2, item 5) só traz `ad_id` no login do Facebook; o login do
   Instagram "cannot access ads".
3. As lojas de carro de Recife já anunciam no Instagram pelo Gerenciador de Anúncios, que já exige
   a Página do Facebook ligada.
Custo: a loja precisa ter a Página ligada à conta profissional. Se uma loja não tiver Página, o
login do Instagram serve para o direct e para os comentários (sem legenda e sem anúncio: a Opção B
cai no texto genérico). O código do Léo fala com a Meta por **um endereço configurável** (padrão
graph.facebook.com), então a troca não muda o resto.

### O que virou configuração "a confirmar" (padrão mais seguro)
| Item | Configuração | Padrão |
|---|---|---|
| Prazo da resposta privada | `instagram.comentarios_prazo_dias` | 7 (confirmado); o Léo usa margem: só responde comentário com menos de 7 dias |
| Respostas privadas por comentário | fixo no código | 1 (confirmado) |
| Tamanho máximo do texto | `instagram.limite_bytes` | 1000 bytes (confirmado), dividindo em bolhas |
| Eco de resposta feita no app | o Léo trata qualquer eco que não seja dele como "vendedor assumiu" | a confirmar com a conta real |
| Marcação de humano (7 dias) | **não usada** pelo Léo: fora das 24 h ele não manda nada | a confirmar |
| Tamanho da resposta pública | texto fixo curto ("Te chamei no direct.") | a confirmar |
| Comentário de anúncio no login do Instagram | tratado como comentário comum, origem "comentario" | a confirmar |
| Versão da API | `INSTAGRAM_API_VERSAO` (.env) | v27.0 |
| Endereço | `INSTAGRAM_API_URL` (.env) | https://graph.facebook.com |

### Payloads de exemplo
`tests/payloads/instagram/` (12 arquivos fictícios, com um `LEIA.md` dizendo de onde veio cada
formato e o que está "a confirmar"): mensagem, várias mensagens, eco do vendedor, eco do Léo, não
suportado, comentário em post (as duas formas publicadas), comentário em anúncio, comentário da
própria loja, legenda do post, resposta à mensagem privada e resposta ao envio.
Teste: `tests/test_ig0_payloads.py` (os arquivos existem, são JSON, são fictícios; a tabela está aqui).

### Como li (sem conta real)
As páginas foram lidas por um ajudante de leitura (sem login, só páginas públicas da Meta). Uma
página (`messenger-platform/instagram`) abriu só o menu: o que dependia dela ficou "não confirmado".

### Testes do IG0
Suíte inteira, 3 partes: 802 + 1.231 + 1.004 = **3.037 passaram, 0 falhas** (3.034 + 3).

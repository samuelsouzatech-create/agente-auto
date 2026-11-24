# Maratona Postgres — diário

Quatro blocos em cadeia: PG0 → PG1 → PG2 → PG3. Branches `postgres-p0` (saiu da main
`8daf273`) → `postgres-p1` → `postgres-p2` → `postgres-p3`. Sem merge na main.

| Bloco | Branch | Situação | Commit | Testes |
|-------|--------|----------|--------|--------|
| PG0 documentos e E2-1 | postgres-p0 | feito | cd84e11 + diário | suíte 2.928 ok |
| PG1 banco PostgreSQL | postgres-p1 | feito | 994c680 | suíte 2.962 ok no PostgreSQL |
| PG2 memória e importação | postgres-p2 | feito | (ver abaixo) | suíte 2.977 ok no PostgreSQL |
| PG3 teste de carga | postgres-p3 | a fazer | | |

## PG0 — Conferência e documentos

### Conferência
- agente-auto: a main (`8daf273`) tem os merges de `fotos-f1` e `fotos-f2`; a tag
  `agente-fotos` aponta para ela. **OK**
- leo-painel-web: a main (`ffea876`) tem o merge de `painel-p7`; a tag `painel-v1.2` aponta
  para ela. **OK**
- Ferramentas neste computador: Docker Desktop 29.8 (estava desligado; foi ligado), Docker
  Compose v5.6. Também existe um PostgreSQL 18 instalado direto no Windows, como serviço, que
  **não** é usado pela maratona (o nosso roda no Docker, com a porta 5432 só em 127.0.0.1; se a
  porta estiver ocupada pelo serviço do Windows, o compose usa outra; ver PG1).

### Documentos
- `CLAUDE.md`: numeração real das migrações (1 a 17, 19, 20; 18 nunca; 21 Instagram), fotos do
  estoque pelo depósito, banco = PostgreSQL a partir desta maratona, Docker no próximo bloco.
- `docs/estado_do_projeto_2026-11-23.md`: pronto, falta e ordem dos próximos blocos.
- `docs/plano_mestre.md`: seção nova "Mudanças depois de 1/11" no fim (nada apagado).

### E2-1 — limite diário da reativação
**O que encontrei:** não existia. A reativação tinha o lote de 500 e o limite mensal (dividido
com a retomada), mas nenhum limite por dia e nenhum teste disso.

**O que fiz (offline, com teste):**
- Campo novo `remarketing.limite_diario_reativacao` (inteiro, 0 a 5.000; padrão **30**, baixo de
  propósito; o número definitivo é a decisão A8). Só o operador altera; aparece em Plano e limites;
  a mudança entra no Registro como qualquer configuração.
- `app/jobs/reativacao.py`: conta as reativações do **dia local da loja**
  (`limites_do_dia_em_utc`) e para no limite. O que sobra fica na fila, na mesma ordem, para o
  dia seguinte. Na simulação contam as simuladas, então a simulação mostra exatamente o que
  sairia. O limite mensal continua valendo junto (vale o menor).
- Tela do operador, Mensagens automáticas, aba "Agora": "Reativação da base hoje: X de Y".
- `tests/test_e2_1_limite_diario.py` (8 testes): limite 3 com 10 na fila manda 3 hoje e 3
  amanhã na ordem; limite 0 não manda; a virada do dia segue o fuso da loja; duas lojas com
  limites diferentes; simulação respeita; limite mensal junto; base de 600 contatos com o
  relógio rodando a cada 5 min por 10 horas manda só 30.
- `tests/test_s4a_configuracao.py`: o assunto Plano e limites ganhou o campo novo (25 campos).

### Decisões e roteiro (pedido do Samuel no meio do PG0)
- `docs/decisoes_e_roteiro.md` (texto do Samuel com o analista) entrou no commit do PG0 **sem
  mudar o texto**: só ganhou um índice e a data no começo e a seção "Registro de mudanças" no
  fim. `CLAUDE.md` ganhou a regra: ler esse arquivo antes de qualquer bloco e parar se o trabalho
  contradizer uma decisão.
- Conferido contra a maratona: nada contradiz (Postgres agora, com a memória das conversas;
  Docker depois; a "tranca por loja" do banco fica para o bloco de segurança).
- **Aviso:** o texto diz que "a 22 já foi usada". No repositório (todas as branches) não existe
  migração 22. As usadas são 1 a 17, 19 e 20; a 21 é do Instagram; a próxima livre é a 22.
  Anotado no Registro de mudanças, sem mexer no texto.

### Testes do PG0
- Suíte inteira (em 3 partes, ainda no SQLite): 766 + 1.042 + 1.120 = **2.928 passaram**, 0
  falhas (eram 2.919; + 8 do E2-1 + 1 parametrização nova). A primeira rodada pegou 1 falha:
  a tela de envios não pode importar `app.jobs` (regra antiga); a conta do dia foi para
  `app/reativacao.py` e a suíte passou.
- O que NÃO fiz no PG0: nada de banco novo (isso é o PG1); o número final do limite diário é
  decisão do Samuel (A8).

## PG1 — Banco PostgreSQL (branch postgres-p1, saiu da postgres-p0)

### O que foi feito
1. **`docker-compose.yml`** na raiz, só com o serviço `postgres` (imagem `postgres:17`, volume com
   nome `leo_banco`, porta só em `127.0.0.1`, senha vinda do `.env` em `POSTGRES_SENHA`). Subir:
   `docker compose up -d`. **Neste PC a porta é 5433** (`BANCO_PORTA=5433` no `.env`), porque a
   5432 já é usada pelo PostgreSQL 18 instalado direto no Windows (não mexi nele). O padrão do
   compose continua 5432.
2. **`.env`**: acrescentei `POSTGRES_SENHA` (senha aleatória, nunca mostrada), `BANCO_PORTA` e
   `BANCO_URL`, sem ler nem mostrar o resto do arquivo. **`.env.example`** novo, só com texto de
   exemplo.
3. **Camada única de conexão (`banco.py`)**: psycopg 3 + pool (`psycopg[binary]==3.3.9`,
   `psycopg-pool==3.3.3`, fixados no `requirements.txt`). Lê a `BANCO_URL`. Nenhum outro arquivo
   abre conexão (tem teste que confere). Para o resto do código não precisar mudar de uma vez, a
   conexão se comporta como a do SQLite:
   - `?` vira o marcador do PostgreSQL; `INSERT OR IGNORE` vira `ON CONFLICT DO NOTHING`;
     `LIKE` vira `ILIKE` (o LIKE do SQLite não diferencia maiúsculas); `CURRENT_TIMESTAMP` vira
     `agora_texto()`; `a IS ?` vira `IS NOT DISTINCT FROM`. Texto entre aspas e comentário não são
     mexidos. `PRAGMA` e `INSERT OR REPLACE` são recusados (dão erro claro).
   - Os valores vão como texto e o PostgreSQL decide o tipo pelo lugar (como o SQLite fazia);
     `True/False` viram 1/0; data e hora viram o mesmo texto de antes; soma e média voltam como
     número comum (não Decimal).
   - Linha por posição e por nome (`linha[0]`, `linha["modelo"]`, `dict(linha)`); `lastrowid`;
     `with conexao:` confirma ou desfaz; fechar sem `commit` desfaz; conexão esquecida aberta
     volta sozinha para o pool; `conectar(somente_leitura=True)` (era `PRAGMA query_only`).
4. **Esquema**: `migracoes/020_base_postgres.sql`, equivalente ao SQLite inteiro na v20 (40
   tabelas, mesmas colunas na mesma ordem, os 32 índices). Fica registrada como **versão 20** na
   tabela nova **`migracoes_aplicadas`** (no próprio banco). A próxima migração usa o próximo
   número livre, a **22** (a 21 continua do Instagram; o `banco.py` recusa uma 21 que não seja do
   Instagram e recusa número repetido). Cada migração roda inteira ou nada, com trava para duas
   cópias do Léo não migrarem juntas.
5. **Busca sem acento**: a função `sem_acento` do banco usa a extensão `unaccent` (mesmo nome,
   então as consultas de estoque, categoria e preço não mudaram). `fone_br` (telefone) também
   virou função do banco, com a mesma regra do Python (teste compara as duas com 18 casos).
   `round(x, casas)` ganhou a versão para número decimal comum.
6. **SQL do SQLite traduzido no código**: `instr` → `strpos` (turno), `sqlite_master`/`PRAGMA
   table_info` → `information_schema` (demo), `strftime/datetime` → `to_char(... + intervalo)`
   (custos e preços), `MAX(a, b)` → `GREATEST` (importação), `create_function` removido (4
   lugares, um deles em `segmentos/veiculos/comprador.py`), `PRAGMA query_only` → conexão
   somente leitura (6 lugares), `sqlite3.IntegrityError` → `banco.ErroDeIntegridade` (login),
   `VALUES (?, ...)` com número de loja (visão geral) ganhou `CAST`, bancada sem
   `INSERT OR REPLACE`.
7. **Testes**: a suíte roda contra o PostgreSQL, num banco **separado e criado sozinho**:
   `<nome da BANCO_URL>_teste` (ou `BANCO_URL_TESTE`), apagado e criado de novo no começo de
   cada rodada. O teste recusa rodar se o nome não terminar em `_teste` ou for igual ao de uso.
   Antes de cada teste o banco é esvaziado (`TRUNCATE`) e volta a ter só o que a migração grava
   (a loja 1 no ar). A bancada tem o banco dela (`_bancada`), esvaziado a cada roteiro.
   A catraca de `loja_id` (`tests/test_catraca_loja.py`) continua valendo.
   - `tests/test_pg1_banco.py` (novo): esquema igual ao da v20, registro de migrações, erro no
     meio não deixa nada pela metade, numeração, tradução do SQL, tipos, `with`, somente
     leitura, pool, `sem_acento`, `fone_br`, banco de teste separado, nenhum `sqlite3` no código,
     nenhum arquivo abrindo conexão por conta própria, compose e `.env.example`.

### Decisões (para o analista conferir)
- **Datas continuam texto** ("AAAA-MM-DD HH:MM:SS", UTC), como o código sempre gravou e comparou.
  Trocar para o tipo de data do PostgreSQL mexeria em centenas de consultas e no `app/relogio.py`;
  fica para depois, se valer a pena.
- **Sem chaves estrangeiras obrigatórias**: o SQLite não conferia (a opção nunca foi ligada).
  Ligar agora mudaria o comportamento (apagar loja, demo). Fica para o bloco de segurança, junto
  com a "tranca por loja" do banco (decisões e roteiro, item 5).
- **E-mail de login** único sem diferença de maiúsculas: índice em `lower(email)` (era
  `COLLATE NOCASE`).
- **Tradução automática na camada** em vez de reescrever as ~700 consultas uma a uma: menos risco
  de erro agora. A camada recusa o que não sabe traduzir. Consultas novas devem ser escritas já no
  jeito PostgreSQL (o `?` continua valendo).

### Testes que saíram (e por quê)
Testavam a **subida do SQLite** de uma versão para a outra (v9→v10, v10→v11, v11→v12, v12→v13,
v14→v15, rodar de novo depois de voltar o `user_version`, erro no meio da migração 12). Esse
caminho não existe mais: o banco nasce da migração-base. O que vale para o PostgreSQL (tudo ou
nada, rodar de novo, mesmas tabelas e colunas) está em `tests/test_pg1_banco.py`. Lista:
- `test_c2a_sessoes.py`: migração 15 roda de novo; sobe da 14.
- `test_c2f_senha.py`: migração 16 só com hash e roda de novo.
- `test_c3_link_vendedor.py`: migração 17 só hash e roda de novo.
- `test_etapa1_bloco1.py`: migração preserva os dados do banco antigo.
- `test_etapa1_bloco7b.py`: migração 4 não dispara avisos de handoffs antigos.
- `test_etapa2_bloco1.py`: migração 5 roda de novo.
- `test_l3_recados.py`: migração 19 cria recados e roda de novo.
- `test_l9_sombra.py`: migração 20 é aditiva e roda de novo.
- `test_p6_registro.py`: sobe da v9 sem perder dado.
- `test_p7a_estado_loja.py`: migração 11 roda de novo; sobe da v10 com as lojas no ar.
- `test_p8a_usuarios_login.py`: sobe da v11 com os mesmos ids; contador de ids; rodar de novo
  não perde e-mail; recusa dado que não combina; erro no meio desfaz tudo.
- `test_s10b_limpeza.py`: migração 14 cria índices (os índices estão no teste do PG1).
- `test_s2_implantacao.py`: sobe da v12; rodar de novo não perde item marcado.
- Trocado: `test_m3_n3_servidor.py` "conexão em WAL com espera de 5 s" (era do SQLite) virou
  "conexão vem do pool do PostgreSQL". O teste de duas escritas ao mesmo tempo continua.
- Ajustados (mesma ideia, jeito PostgreSQL): os que liam `sqlite_master`/`PRAGMA table_info`,
  os que contavam consultas (`set_trace_callback` agora existe na conexão nova), o plano de
  consulta do S10b (`EXPLAIN` com leitura inteira desligada, para ver se o índice serve).

### Testes do PG1
- Suíte inteira **contra o PostgreSQL** (3 partes): 759 + 1.065 + 1.137 = 2.961 passaram e 1
  falhou (um teste usava o `iterdump` do SQLite para fotografar o banco; agora lê todas as
  tabelas). Depois do conserto, a parte 2 rodou de novo: **1.066 passaram**. Total: 759 + 1.066
  + 1.137 = **2.962 passaram, 0 falhas**.
- Mais rápida que no SQLite (cerca de 12 min contra 19 min), depois de duas mudanças: limpar o
  banco com `DELETE` em vez de `TRUNCATE` antes de cada teste, e o banco de TESTE sem esperar o
  disco a cada gravação (`synchronous_commit = off`, só no banco `_teste`).
- Conta: eram 2.928 no PG0; saíram 21 testes da subida do SQLite (lista acima) e entraram 54
  do `test_pg1_banco.py` (com os casos repetidos com dados diferentes) = 2.961 + 1 consertado.

### O que NÃO foi feito no PG1
- Memória das conversas e importação do `loja.db`: PG2.
- O resto da aplicação no Docker: próximo bloco (Docker), como pedido.
- Chaves estrangeiras e a "tranca por loja" do banco: bloco de segurança.
- A `venv/` (ambiente que roda o Léo de verdade) ainda não tem o psycopg: antes de ligar o Léo,
  rodar `venv\Scripts\pip install -r requirements.txt`. Os testes usam a `.venv-teste`, que já tem.

## PG2 — Memória das conversas e importação dos dados (branch postgres-p2, saiu da postgres-p1)

### O que foi feito
1. **Memória das conversas no PostgreSQL** (`app/core/agent.py`): a `MemoriaLimitada` agora é
   um `PostgresSaver` (pacote oficial `langgraph-checkpoint-postgres==3.2.1`, fixado). A conversa
   continua depois de reiniciar o processo. A conexão vem do `banco.py` (um pool só da memória,
   porque a biblioteca pede conexões do jeito dela), sempre no banco da `BANCO_URL` em uso.
   - **Limite do L12 mantido:** conversa parada há mais de 24 h sai; acima de 2.000 conversas,
     saem as mais antigas. A "hora do último uso" agora vem do banco (data da última fotografia
     da conversa), então o limite vale também depois de reiniciar. A poda roda no máximo a cada
     5 minutos (ela consulta o banco).
   - **Apagar por conversa** (`delete_thread`) continua; a bancada usa.
   - As 4 tabelas da memória (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`,
     `checkpoint_migrations`) são da biblioteca e têm a própria lista de mudanças. Não usam a
     nossa numeração: o `banco.migrar()` chama o `setup()` da biblioteca depois das nossas.
2. **`scripts/importar_sqlite.py`**: copia o `loja.db` para o PostgreSQL.
   - `--ensaio`: confere a estrutura (toda tabela e coluna do loja.db existe no PostgreSQL) e
     mostra, tabela por tabela, a contagem no loja.db e no PostgreSQL. Não grava nada.
   - Sem `--ensaio`: copia com os mesmos ids, tudo numa transação; no fim compara a contagem de
     cada tabela e, se alguma diferir, desfaz tudo e para com erro. Rodar duas vezes não duplica
     (a linha que já existe é atualizada). O próximo id automático continua depois do maior.
   - O loja.db é aberto só para leitura e precisa estar na versão 20.
   - É o único arquivo do Léo que usa `sqlite3` (tem teste que confere).
3. **Demo no PostgreSQL**: `criar_loja_demo`, `criar_usuarios_demo` e `reiniciar_demo`
   rodaram no banco novo; fotos da demo no depósito (24 carros); retomada de exemplo gravada.
4. **`docs/demo.md`**: passo 0 "Subir o banco" (`docker compose up -d`, criar as tabelas,
   conferir com `docker compose ps`) e o que fazer se o banco não responder.

### Rodado de verdade (neste PC)
- Banco de uso (`leo`, porta 5433): tabelas criadas.
- **Ensaio com o loja.db real** (só leitura): estrutura conferida nas **40 tabelas**, 1.011 linhas.
- **Importação de verdade** para o banco de uso local: as 40 contagens bateram (1.011 linhas);
  **rodada de novo: nada duplicou**. Os dados ficaram só no PostgreSQL local deste computador.
- **Demo no painel, no navegador (Edge), sem IA**: API do painel na porta 8001 rodando sobre o
  PostgreSQL + tela `leo-painel-web` (main). Login do Dono Demo; Atender, Estoque, Acompanhamento
  e Resultado abriram em 375 px e 1280 px; fotos do depósito carregadas (15 visíveis em 375 px,
  24 em 1280 px); **nenhum erro da API** (52 e 61 pedidos). As senhas ficaram num arquivo
  temporário fora do Git, apagado no fim.

### Falha minha (registrada)
- Rodei `scripts\criar_loja_demo.py` **sem** `--sem-indexar`. Ele tentou indexar a base de
  conhecimento da demo, o que usa o Gemini (embeddings), e falhou ("não consegui indexar a base
  agora"). Não sei se a chamada chegou a sair; os créditos do Gemini estavam esgotados (estado de
  22/11), então o custo provável é zero. Fere a regra "sem Gemini". Depois disso, só com
  `--sem-indexar`. O índice da demo fica como estava (Chroma, fora do banco).

### Testes do PG2
- `tests/test_pg2_memoria.py` (6): o Léo usa a memória no PostgreSQL; a conversa continua depois
  de fechar todas as conexões e criar uma memória nova; outra loja não vê a conversa; o limite
  apaga as mais antigas; parada há mais de 24 h sai; a poda roda sozinha ao salvar; apagar uma
  conversa apaga só ela.
- `tests/test_pg2_importar.py` (9), com um **loja.db fictício** montado com o esquema da v20
  (`tests/dados/esquema_sqlite_v20.sql`): ensaio não grava; importa com os mesmos ids e dados
  (acento, número decimal, vazio); rodar duas vezes não duplica e o próximo id continua; contagem
  diferente para e não grava nada; versão errada e coluna desconhecida são recusadas; o loja.db
  não é alterado; o comando de ensaio não mostra a senha.
- Ajustado: o teste do L12 (a hora do último uso vem do banco).
- **Suíte inteira contra o PostgreSQL** (3 partes): 793 + 1.061 + 1.123 = **2.977 passaram, 0
  falhas** (2.962 do PG1 + 6 da memória + 9 da importação).

### O que NÃO foi feito no PG2
- A base de conhecimento (Chroma) continua fora do banco, como manda o roteiro (pgvector é para
  depois).
- A `venv/` que roda o Léo de verdade ainda não tem os pacotes novos:
  `venv\Scripts\pip install -r requirements.txt` antes de ligar o Léo.

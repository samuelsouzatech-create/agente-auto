# Maratona Docker — diário

Quatro blocos em cadeia: DK0 → DK1 → DK2 → DK3. Branches `docker-d0` (saiu da main `d1093fd`)
→ `docker-d1` → `docker-d2` → `docker-d3`. Sem merge na main. No `leo-painel-web`, se precisar
mudar algo, a branch é `painel-docker`.

Regras da maratona: sem Gemini/IA real, sem canal real (WhatsApp/Telegram/Meta), sem túnel, só
dados fictícios. `.env`, senhas e tokens nunca aparecem aqui nem no Git.

| Bloco | Branch | Situação | Testes |
|-------|--------|----------|--------|
| DK0 mapa das peças | docker-d0 | feito | suíte 2.982 ok (851 + 1.137 + 994) |
| DK1 tudo sobe com um comando | docker-d1 | feito | suíte 3.002 ok; demo pelo HTTPS local 10/10 |
| DK2 aposentar o Streamlit do cliente | docker-d2 | | |
| DK3 turno lento com muitas lojas | docker-d3 | | |

## DK0 — Mapa das peças (como roda hoje, antes do Docker)

Tudo roda direto no Windows, cada peça num PowerShell, a partir da pasta `agente-auto` (os
caminhos "relativos" abaixo, como `logs/` e `chroma_db/`, são relativos a essa pasta: quem
roda de outra pasta grava em outro lugar). O `.env` é lido por todas as peças Python
(`load_dotenv`). Só o banco já está no Docker (`docker-compose.yml` do PG1).

Legenda: **L** = lê, **G** = grava.

| Peça | Comando de hoje | Porta | Banco (PostgreSQL) | Redis | Chroma (`chroma_db/`) | Depósito de fotos (`fotos_deposito/` ou nuvem) | Logs (`logs/`) | Fala com fora |
|---|---|---|---|---|---|---|---|---|
| **Webhook do WhatsApp** (`app/api/webhook.py`) | `uvicorn app.api.webhook:app --port 8000` (o comando não está escrito em nenhum documento; 8000 é o padrão do uvicorn) | 8000 | L/G (mensagens, leads, chamados, custos, registro, memória das conversas) | L/G: duplicata (`dedup`), espera da rajada (`debounce`), trava por cliente (`lock`), atraso | L (busca na base de conhecimento, ferramenta `buscar_conhecimento`) | L (fotos do estoque enviadas ao cliente; WhatsApp só com endereço https público) | G: `leo.log` (5×5 MB), `execucoes.jsonl`, `mensagens_recusadas.jsonl` | Meta (receber/enviar), Gemini (IA, áudio, foto) |
| **API do painel** (`app/api_painel/main.py`) | `uvicorn app.api_painel.main:app --host 127.0.0.1 --port 8001` (atrás de proxy: `--proxy-headers --forwarded-allow-ips <ip do proxy>`) | 8001 | L/G (login, sessões, atender, venda, estoque, leads, resultado, acompanhamento) | não usa em funcionamento (só importa módulos que conhecem o Redis) | não usa | L/G (enviar, apagar, reordenar fotos; servir `/fotos/{nome}`) | G: `leo.log`; log de acesso do uvicorn na tela (sem o número do cliente) | resposta do vendedor sai pelo canal da loja (WhatsApp/Telegram; na demo, só simulador) |
| **Relógio dos jobs** (`app/jobs/runner.py`: avisos de chamado, alerta de gasto, retomadas/remarketing, pós-venda, reativação) | `python -m app.jobs.runner` (não liga sem Redis; `--uma-vez`, `--sem-…`) | — | L/G (filas, envios, contadores, batimento) | L/G: trava "só um relógio" (`TravaRunner`) e batimento (luz do operador) | não usa | L (foto em mensagem automática, se houver) | G: `leo.log` | Telegram de avisos (equipe e operador); WhatsApp/Telegram só com `*_ENVIO_REAL=1` (padrão: simulação) |
| **Painel do operador** (Streamlit, `operador.py`) | `streamlit run operador.py --server.port 8502` (o `docs/demo.md` usa 8502; o README e o próprio arquivo dizem 8501) | 8502 | L/G (configuração de todas as lojas, nova loja, base de clientes, reiniciar demo, registro) | L (Visão geral: Redis responde? relógio vivo?) | L/G (Configuração → Conhecimento/Estoque reindexa = **Gemini**, embeddings) | L/G (fotos na configuração do estoque, reiniciar demo) | L (Visão geral lê `logs/`) | Gemini só ao indexar conhecimento. **Sem login: só local** (precisa de `OPERADOR_NOME`) |
| **Painel Streamlit do cliente** (`painel.py`) | `$env:LOJA_ID="N"` e `streamlit run painel.py --server.port 8503` (README: 8502) | 8503 | L/G só da loja `LOJA_ID` (8 telas: Fila, Conversas, Resultados, Retomadas e pós-venda, Estoque, Configuração, Conhecimento, Usuários) | não usa | L/G (tela Conhecimento) | L/G (fotos pela caixa de links) | G: `leo.log` | Gemini ao indexar conhecimento. **Sem login: só local** |
| **Simulador** (Streamlit, `app.py`) — peça de demo, não de produção | `streamlit run app.py` | 8501 | L/G (canal "simulador") | não usa | L | L | G | Gemini (é o Léo de verdade respondendo) |
| **Bot do Telegram** (`app/api/telegram_bot.py`), um processo por bot de loja | `python -m app.api.telegram_bot [NOME_DA_VARIAVEL_DO_TOKEN]` (polling: ele busca as mensagens, não recebe) | — | L/G (igual ao webhook) | L/G (igual ao webhook) | L | L (manda a foto em bytes) | G: `leo.log`, `execucoes.jsonl`, `mensagens_recusadas.jsonl` | Telegram, Gemini |
| **Tela `leo-painel-web`** (React, outro repositório) | desenvolvimento: `npm run dev` (Vite, proxy `/api` → `127.0.0.1:8001`); produção: `npm run build` gera `dist/` (arquivos estáticos) | 5173 (dev) | — (só pela API) | — | — | — (fotos pela API) | — | só a API do painel (mesma origem, cookie `leo_sessao`) |
| **PostgreSQL 17** (Docker, `docker-compose.yml`) | `docker compose up -d` | 127.0.0.1:5432 (neste PC 5433, `BANCO_PORTA`) | volume `leo_banco` | | | | | |
| **Redis** (container `redis-leo`, criado à mão, fora do compose) | `docker start redis-leo` | **0.0.0.0:6379, sem senha** (aberto para a rede toda) | | sem volume (o que está nele é temporário) | | | | |

### Coisas que o mapa mostrou (para o DK1)
- **Caminhos relativos**: `chroma_db/`, `logs/` e (sem `FOTOS_PASTA`) `fotos_deposito/` dependem
  da pasta de onde a peça é ligada. No Docker, todas ligam de `/app`, com um volume em cada uma.
- **Chroma é arquivo local compartilhado**: quem grava (operador, painel Streamlit do cliente) e
  quem lê (webhook, bot, simulador) precisam do mesmo volume `chroma_db`.
- **Depósito local**: API (grava), operador (grava), webhook/bot/relógio (leem) no mesmo volume.
- **Redis**: a URL vem de `REDIS_URL` (padrão `redis://localhost:6379/0`). Aceita senha no
  formato `redis://:SENHA@host:6379/0`, sem mudar código.
- **Portas desencontradas na documentação**: operador 8501 (README, `operador.py`) × 8502
  (`docs/demo.md`, pedido desta maratona); painel do cliente 8502 × 8503. O webhook não tem
  comando escrito em nenhum lugar.
- **Simulador** não estava na lista do pedido, mas é peça da demo (usa Gemini). Fica fora do
  compose (precisa de IA de verdade para responder); ver DK1.
- **Sem login** no operador e no painel Streamlit do cliente: não podem ficar abertos fora do
  computador.
- O import de módulos é muito entrelaçado (toda peça "carrega" Redis, Chroma e o agente, mesmo
  sem usar); a tabela acima diz o que cada peça **usa** de fato.

### Testes do DK0
- Suíte inteira contra o PostgreSQL, em 3 partes (memória do PC): 851 + 1.137 + 994 =
  **2.982 passaram, 0 falhas** (o mesmo número do PG3: o DK0 não mexeu em código).
- Ligado no começo: script de manter o computador acordado (processo em segundo plano, desligado
  no fim da maratona).

## DK1 — Tudo sobe com um comando (branch docker-d1, saiu da docker-d0)

### O que foi feito
1. **`Dockerfile`** (uma imagem para todas as peças Python): `python:3.13.9-slim-trixie` (número
   exato), pacotes do `requirements.txt` (todos com `==`) instalados numa etapa separada, usuário
   comum `leo` (número 1000, sem poder de administrador), código em `/app`. **`.dockerignore`**:
   `.env`, `*.db`, `chroma_db/`, `fotos_deposito/`, `logs/`, `venv/`, testes e
   `diagnostico_meta.py` nunca entram na imagem. Tamanho: 1,49 GB (o grosso é chromadb/onnxruntime
   e langchain; a base slim tem ~120 MB).
2. **`docker-compose.yml`** com: `postgres` (17.12, o mesmo que já rodava), `redis` (7.4.7, com
   senha `REDIS_SENHA` do `.env`, porta só em 127.0.0.1, dados no volume `leo_redis`),
   `migrar` (cria as tabelas e sai, antes das outras), `webhook` (porta interna 8000),
   `api-painel` (8001), `relogio`, `operador` (Streamlit 8502), `simulador` (perfil `demo`),
   `telegram` (perfil `telegram`, não sobe sem pedir) e `porteiro` (Caddy com a tela pronta).
   - Volumes com nome: `leo_banco`, `leo_redis`, `leo_chroma`, `leo_fotos`, `leo_logs`,
     `leo_caddy_dados` (certificados) e `leo_caddy_config`.
   - Toda peça tem verificação de saúde (`docker/saude.py`: a peça responde; o relógio girou nos
     últimos 3 minutos; o Redis responde) e `restart: unless-stopped`.
   - As peças recebem `BANCO_URL` e `REDIS_URL` apontando para dentro da rede do Docker
     (`postgres`, `redis`), montadas com as senhas do `.env`. O resto vem do `.env`
     (`LEO_ENV_ARQUIVO` troca o arquivo; usei isso nos testes, ver abaixo).
3. **Portas:** só o porteiro publica: 443 (HTTPS) e 80 (só manda para o HTTPS), em
   `PORTEIRO_IP` (padrão **127.0.0.1**; no servidor, `0.0.0.0`). O operador e o simulador (sem
   login) passam pelo porteiro, mas nas portas 8502 e 8501 **sempre em 127.0.0.1** (no servidor:
   túnel SSH). Banco e Redis: só 127.0.0.1 (para os testes e scripts deste PC). Webhook, API,
   relógio, operador e simulador não publicam porta nenhuma (conferido: 8000 e 8001 fechadas).
4. **Porteiro HTTPS** (`docker/Caddyfile`, `docker/porteiro.Dockerfile`): Caddy 2.10.2. A tela
   `leo-painel-web` é compilada dentro da imagem (Node 22.21.1, `npm ci` + `npm run build` com
   `VITE_API_URL=/api/v1`), a partir da pasta do outro repositório (`TELA_PASTA`, padrão
   `../leo-painel-web`): **nada mudou no leo-painel-web** (a branch `painel-docker` não foi
   necessária). `/api/*` vai para a API, `/webhook` para o webhook, o resto é a tela.
   - Seguindo o `docs/api/publicacao.md`: o Caddy repassa `X-Forwarded-For {remote_host}`
     (o endereço de quem conectou nele; o que o visitante manda é jogado fora), `X-Forwarded-Proto`
     e `Host`. A API e o webhook rodam com `--proxy-headers --forwarded-allow-ips 172.28.0.10`:
     só o IP fixo do porteiro na rede `leo_interna` (nunca `*`).
   - Com `LEO_DOMINIO=localhost` (padrão) o Caddy cria um certificado local; com um domínio real
     (na hospedagem) ele pede o certificado sozinho.
   - Cabeçalhos: HSTS, `nosniff`, `Referrer-Policy`, `X-Frame-Options SAMEORIGIN`.
5. **Conserto no relógio** (`app/jobs/runner.py`): o Docker para as peças com o sinal SIGTERM,
   não com Ctrl+C. O relógio morria sem soltar a trava do Redis, e o relógio novo recusava ligar
   ("já existe outro runner") por até 90 s, reiniciando em volta. Agora SIGTERM vira Ctrl+C:
   marca "parado" e solta a trava. Conferido no Docker: parou às 14:16:40 e o novo ligou às
   14:16:44.
6. **`.env`**: acrescentei `REDIS_SENHA` (aleatória, nunca mostrada), `REDIS_PORTA=6379` e
   `COMPOSE_PROFILES=demo`, e troquei a linha `REDIS_URL` para o Redis novo (com a senha, em
   127.0.0.1), sem ler nem mostrar o resto. `.env.example` ganhou os exemplos.
7. **`docs/demo.md`** reescrito: a demo inteira abre com `docker compose up -d`; endereços
   https://localhost (painel novo), :8502 (operador), :8501 (simulador); preparar e reiniciar a
   demo com `docker compose exec api-painel ...`; confiar no certificado local.

### Trazer os dados de antes (uma vez)
As fotos e a base de conhecimento que estavam nas pastas do projeto foram copiadas para os
volumes (26 fotos, 5 arquivos do Chroma). O banco já estava no volume `leo_banco`. Para repetir
em outro computador (PowerShell, na pasta do projeto, depois do `docker compose build`):
```powershell
docker volume create leo_fotos; docker volume create leo_chroma
docker run --rm --user 0 -v leo_fotos:/d -v "${PWD}\fotos_deposito:/s:ro" leo-app:dk1 sh -c "cp -a /s/. /d/ && chown -R 1000:1000 /d"
docker run --rm --user 0 -v leo_chroma:/d -v "${PWD}\chroma_db:/s:ro" leo-app:dk1 sh -c "cp -a /s/. /d/ && chown -R 1000:1000 /d"
```

### O Redis antigo (`redis-leo`)
Deixou de ser usado: o `.env` agora aponta para o Redis do compose (com senha, só 127.0.0.1).
**Não apaguei.** Ele estava parado quando a maratona começou. Cuidado: se ele for ligado
(`docker start redis-leo`), briga pela porta 6379 com o Redis novo. Para apagar quando quiser
(ele não tem volume; o que estava nele era temporário):
```powershell
docker stop redis-leo
docker rm redis-leo
```
(Depois, se quiser liberar o espaço da imagem antiga: `docker image rm redis:7`.)

### Como testei (sem IA e sem canal)
- As peças rodaram com um arquivo de ambiente de teste (`LEO_ENV_ARQUIVO`, fora do Git) **sem
  chave de IA e sem token de canal**: chave do Gemini falsa (o webhook não liga sem alguma
  chave), tokens do WhatsApp/Telegram vazios, `*_ENVIO_REAL=0`, perfis desligados (sem
  simulador e sem bot). O banco e o Redis usaram as senhas do `.env`.
- `docker compose up -d`: as 7 peças **healthy** (postgres, redis, webhook, api-painel,
  relogio, operador, porteiro; `migrar` saiu com 0). Memória: ~560 MB no total (operador 192 MB,
  webhook 145 MB, postgres 72 MB, relógio 57 MB, API 54 MB, porteiro 27 MB, Redis 13 MB).
- Demo reiniciada **dentro do container** (`reiniciar_demo.py --sem-indexar`): fotos ilustrativas
  geradas no volume (26 arquivos); as senhas ficaram num arquivo temporário fora do Git, apagado
  no fim.
- **Navegador (Edge controlado por roteiro Playwright, fora do Git), pelo HTTPS local, 375 px e
  1280 px:** a tela abriu em https://localhost; login do Dono Demo (cookie `leo_sessao` Secure e
  HttpOnly); Atender abriu (1 esperando vendedor, 4 com vendedor); Estoque com fotos do depósito
  (15 carregadas em 375 px, 24 em 1280 px); nenhum erro 5xx (27 e 36 pedidos à API). **10 de 10.**
- Operador em https://localhost:8502: abriu (Visão geral, menus da loja), websocket do Streamlit
  passando pelo porteiro.
- http://localhost → 308 para https; GET /webhook com token errado → 403; portas 8000 e 8001
  fechadas no PC; login com `X-Forwarded-For: 6.6.6.6` inventado: a API registrou o endereço que
  o porteiro viu (172.28.0.1), não o inventado.
- Relógio parado e religado: soltou a trava (acima).

### O que NÃO testei no DK1
- O simulador no Docker (perfil `demo`): ele usa o Gemini. Sobe igual ao operador (mesma imagem,
  mesma verificação), mas não abri.
- O bot do Telegram no Docker (perfil `telegram`): canal real.
- `PORTEIRO_PORTA` diferente de 443 e domínio real com certificado de verdade (só na hospedagem).
- O comando `certutil` para confiar no certificado local (não mexi na lista de certificados do
  Windows; no teste o navegador foi mandado ignorar o aviso).

### Cuidados (para o analista)
- **No Docker Desktop (Windows) todo visitante chega ao porteiro com o mesmo endereço**
  (172.28.0.1, a "porta" do Docker). Então, no PC, o limite de "links errados demais" conta todo
  mundo junto. Num servidor Linux, o endereço real do visitante chega ao Caddy. Conferir no
  servidor (bloco Servidor).
- O porteiro (imagem oficial do Caddy) roda como administrador dentro do container (para abrir a
  porta 443). As peças do Léo rodam como usuário comum.
- O webhook não liga sem `GOOGLE_API_KEY` (a IA é criada ao carregar). Já era assim antes do
  Docker.
- Portas desencontradas da documentação antiga: no Docker ficou operador 8502 e simulador 8501.

### Testes do DK1
- `tests/test_dk1_docker.py` (novo, offline, não precisa do Docker ligado): todas as peças no
  compose; só o porteiro publica porta fora de 127.0.0.1; operador/simulador sempre em 127.0.0.1;
  banco e Redis só em 127.0.0.1 e com senha do `.env`; toda peça com saúde e reinício; volumes com
  nome; API e webhook confiam só no IP do porteiro; nenhuma senha escrita no compose; simulador e
  Telegram só com perfil; imagens com versão exata e usuário sem administrador; pacotes com `==`;
  segredos fora da imagem; Caddy repassa o endereço real; saúde do relógio (girando, atrasado,
  parado, sem sinal, Redis fora); SIGTERM vira Ctrl+C e o relógio solta a trava.
- `tests/test_pg1_banco.py`: o teste do compose dizia "só o postgres"; agora confere que o
  postgres continua lá (o resto é do teste novo).
- **Suíte inteira contra o PostgreSQL** (3 partes, com o banco e o Redis do compose ligados):
  813 + 1.195 + 994 = **3.002 passaram, 0 falhas** (2.982 + 20 novos). Na 1ª rodada da parte 3,
  1 falha em `test_s10b_limpeza.py::test_excecoes_usam_o_indice`: o PostgreSQL escolheu outro
  índice que também serve para a consulta (`idx_mensagens_loja_direcao`). O arquivo passou 3
  vezes seguidas sozinho e a parte 3 inteira passou de novo (994). É um teste **instável que já
  existia** (depende das estatísticas do banco no momento); não tem relação com o Docker. Não
  mexi nele (fora do escopo): fica para o analista.

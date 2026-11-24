# Maratona Docker — diário

Quatro blocos em cadeia: DK0 → DK1 → DK2 → DK3. Branches `docker-d0` (saiu da main `d1093fd`)
→ `docker-d1` → `docker-d2` → `docker-d3`. Sem merge na main. No `leo-painel-web`, se precisar
mudar algo, a branch é `painel-docker`.

Regras da maratona: sem Gemini/IA real, sem canal real (WhatsApp/Telegram/Meta), sem túnel, só
dados fictícios. `.env`, senhas e tokens nunca aparecem aqui nem no Git.

| Bloco | Branch | Situação | Testes |
|-------|--------|----------|--------|
| DK0 mapa das peças | docker-d0 | feito | suíte 2.982 ok (851 + 1.137 + 994) |
| DK1 tudo sobe com um comando | docker-d1 | | |
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

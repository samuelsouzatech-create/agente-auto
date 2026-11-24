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
| AR arrumações | arrumacoes | feito | ver AR |

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

# Maratona Postgres — diário

Quatro blocos em cadeia: PG0 → PG1 → PG2 → PG3. Branches `postgres-p0` (saiu da main
`8daf273`) → `postgres-p1` → `postgres-p2` → `postgres-p3`. Sem merge na main.

| Bloco | Branch | Situação | Commit | Testes |
|-------|--------|----------|--------|--------|
| PG0 documentos e E2-1 | postgres-p0 | em andamento | | |
| PG1 banco PostgreSQL | postgres-p1 | a fazer | | |
| PG2 memória e importação | postgres-p2 | a fazer | | |
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

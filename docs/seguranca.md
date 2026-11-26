# Maratona Segurança — diário

Cinco blocos em cadeia: SE0 → SE1 → SE2 → SE3 → SE4. Branches `seguranca-0` … `seguranca-4`
(cada uma nasce da anterior), tags `se0` … `se4`. Começo: 25/11/2026, 22:42 (horário de Recife).

Conferido antes de começar: a `main` do agente-auto está na tag `agente-maratona4` (eaa61b8) e a
do leo-painel-web na tag `painel-v1.3` (24e9316). Computador mantido acordado pelo script de
sempre (ligado no começo, desligado no fim).

Regras que valem para todos os blocos: sem IA real (sem `-m api`, sem bancada), sem canal real,
sem túnel, sem e-mail real, sem dado de pessoa real; `.env` e segredos nunca no Git; suíte no fim
de cada bloco, nunca duas rodadas ao mesmo tempo; o comportamento do Léo para o cliente não muda.

---

## SE0 — Consertos da Maratona 4 (branch `seguranca-0`)

### 1. "Mesmo cliente" só com contato NOVO no WhatsApp
`app/instagram_whatsapp.py`, `vincular_mesmo_cliente`. Antes, bastava o telefone que o lead do
Instagram passou bater com quem escreveu no WhatsApp. O risco: o cliente digita o número de outra
pessoa (ou de um parente que já é cliente da loja), e a conversa antiga dessa pessoa aparecia junta
com a do Instagram. Agora:
- só junta se o contato do WhatsApp **não tem nenhuma mensagem naquela loja de antes** da hora em
  que o telefone foi dado no Instagram (`leads.telefone_em`);
- se já tinha, **não junta** e anota no Registro da loja o evento de sistema
  `mesmo_cliente_nao_juntou` ("Não juntei Instagram e WhatsApp (o WhatsApp já tinha conversa)"),
  **uma vez só** (as mensagens seguintes do mesmo número não repetem a anotação);
- cada loja é conferida sozinha: o número ser cliente antigo da loja B não impede de juntar na A.
O alvo da anotação segue o padrão do Registro (`whatsapp:<número>`); a exclusão de dados (item 2)
limpa essa linha se o cliente do Instagram pedir.
Testes: `tests/test_se0_consertos.py` (contato novo junta; antigo não junta e anota uma vez;
mensagem depois do telefone ainda é contato novo; duas lojas).

### 2. Exclusão de dados (`/dados/excluir`) sem mudar os números da loja
`app/api/dados.py`, `apagar_cliente`. Tudo numa transação só:
- **Anonimizadas (a linha fica):** `vendas`, `resultados` e `uso_custos` (custo da IA da loja). O
  cliente vira `excluido:<código aleatório>` (o mesmo para todas as linhas dele, para a contagem por
  cliente não mudar) e o texto livre sai (`resultados.motivo`). Ficam: carro, data, forma de
  pagamento, vendedor, custo.
- **Apagadas:** mensagens, ficha (`leads`: nome, telefone dado no Instagram, interesse), interesse no
  carro, chamados e **os avisos deles** (o aviso ao vendedor tem o nome e o resumo do cliente),
  visitas, situação, opt-out, réguas, envios, sessões e links do vendedor daquele cliente,
  comentários do Instagram, o **vínculo com o WhatsApp**, e a memória da conversa (LangGraph).
- **Texto que ainda cita o cliente** (ex.: o Registro, `alvo = instagram:ig:<id>`): a citação é
  trocada pelo nome anônimo; nessas mesmas linhas o telefone dado no Instagram vira "telefone apagado".
- Outra loja não é tocada (o pedido só alcança a loja onde o id existe).

Testes: os números do Resultado (vendas registradas, vendas no funil, resultados por tipo e
vendedor, custo) são **iguais** antes e depois; o id do Instagram, o telefone e o nome são
procurados em **todas as colunas de texto de todas as tabelas** e não aparecem mais; a memória da
conversa é apagada; a loja B fica intacta.

**Atenção (não é defeito, é o que a regra pede):** os números do Resultado que vêm das
**mensagens** (conversas atendidas, fora do horário, tempo da 1ª resposta, conversas e qualificados
no funil) e dos **chamados** (passados ao vendedor, tempo até assumir) **diminuem**, porque a regra
manda apagar mensagens e chamados. Para esses números também ficarem iguais, a saída seria guardar
um contador anônimo por dia (tabela nova, migração). **Decisão para o analista.**

**Decisão tomada (para o analista conferir):** quando o cliente do Instagram já estava vinculado a
uma conversa do WhatsApp, só o **vínculo** sai; a conversa do WhatsApp **fica** (é outro canal,
começou pelo WhatsApp, e o pedido da Meta é do Instagram). A base de contatos que a própria loja
importou (`contatos`, `compras_anteriores`) também não é tocada pelo telefone.

### 3. Palavras dos comentários
Novo padrão de `instagram.palavras_comentario` (`app/lojas.py`): quero, valor, preço, quanto, info,
tem, ainda tem, disponível, interesse, financia, parcela, troca, zap, whatsapp (14; o limite da
lista é 30, conferido em `_lista_texto`). Lojas que já tinham salvado uma lista própria continuam
com a delas.
A comparação já era sem acento e sem maiúscula. **Mudança pequena na comparação:** antes a palavra
valia em qualquer pedaço do comentário ("tem" pegava "sistema" e "item"); agora vale no **começo**
de uma palavra ("info" pega "informações", "financia" pega "financiamento", "tem" não pega
"sistema"). O limite de 20 respostas privadas por hora não mudou.
Testes: "Ainda tem?", "QUANTO", "disponivel", "Disponível?", "PREÇO", "Zap", "informações",
"financiamento" recebem; "lindo carro", "que sistema bonito", "top demais" não recebem; um
comentário de ponta a ponta com a lista padrão.

### 4. Acentos (UTF-8)
Conferi os bytes do `docs/maratona4.md` **no repositório** (`git show HEAD:docs/maratona4.md`): é
UTF-8 válido, "Decisões" está gravado certo (bytes `c3 b5`), sem nenhum acento quebrado. Varri todos
os arquivos de texto do repositório (.md, .py, .sql, .json, .yaml, .txt, .toml, .sh, .ps1, Caddyfile,
Dockerfile e outros): **nenhum** está fora do UTF-8 nem tem acento quebrado. Não precisei regravar nada.
Por que aparece "DecisĂµes": é a **leitura**, não o arquivo. O arquivo é UTF-8 sem BOM, e um
programa que lê como Windows-1250 (ex.: `Get-Content` do PowerShell 5.1 sem `-Encoding UTF8`, ou o
console com página de código antiga) mostra "Ăµ" no lugar de "õ". **Não confirmado** qual programa
o Samuel usou. Para ler certo no PowerShell: `Get-Content docs\maratona4.md -Encoding UTF8`.
Teste novo: `tests/test_se0_utf8.py` reprova arquivo de texto do Git que não seja UTF-8 válido ou que
tenha acento quebrado ("Ã£", "Ăµ" e parecidos, ou o caractere de troca U+FFFD).

### 5. "Transação só quando precisa" (banco.py, DK3), linha a linha
A regra (`leitura_simples`) é uma **lista branca**: só fica sem transação o comando que (a) começa
com SELECT, WITH, EXPLAIN ou SHOW, (b) não tem palavra de escrita em lugar nenhum e (c) [novo no
SE0] não chama função fora da lista de funções que só leem. Qualquer outro abre a transação no
próprio comando (o psycopg manda o BEGIN junto).

| Tipo de comando | Abre transação? | Por quê |
|---|---|---|
| `SELECT` simples, com `COUNT`, `MAX`, `COALESCE`, `lower`, `IN (...)`, `EXISTS (...)` | não | lista branca |
| `WITH ... SELECT` só de leitura | não | idem |
| `WITH x AS (INSERT/UPDATE/DELETE/MERGE ...) SELECT` | **sim** | palavra de escrita em qualquer lugar |
| `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `TRUNCATE` | **sim** | não começa com leitura |
| `SELECT ... FOR UPDATE / FOR SHARE / FOR NO KEY UPDATE / FOR KEY SHARE` | **sim** | trava de linha |
| `SELECT ... INTO tabela` | **sim** | cria tabela |
| `SELECT nextval/setval`, `pg_advisory_xact_lock` | **sim** | mexe em sequência ou trava de transação |
| `SELECT set_config(...)` | **sim (novo)** | é o `SET LOCAL` disfarçado (vai importar no SE3) |
| `SELECT minha_funcao()` (função fora da lista) | **sim (novo, era o furo)** | a função pode gravar |
| `EXPLAIN SELECT` | não | só mostra o plano |
| `EXPLAIN ANALYZE ...` | **sim (novo)** | executa o comando de verdade |
| `SHOW` | não | só lê configuração |
| `COPY`, `LOCK`, `SET`, `SET LOCAL`, `VALUES`, `TABLE`, `CALL`, `DO` | **sim** | não começam com leitura |
| comentário antes do comando (`-- x` ou `/* x */`) | **sim** | na dúvida, abre |
| minúsculas e quebras de linha | igual às maiúsculas | regra sem diferença de maiúscula; `\s` pega quebra de linha |
| texto entre aspas com cara de função (`'f(1)'`) | não | o texto entre aspas é ignorado na procura de função |
| conexão `somente_leitura=True` | sempre dentro de transação READ ONLY | como antes do DK3 |

**Furo achado e consertado:** `SELECT funcao_que_grava()` rodava **fora** de transação: a gravação
ficava na hora e um `rollback`/fechar sem `commit` não desfazia. Hoje o banco não tem função assim
(as nossas são `agora_texto`, `sem_acento`, `fone_br` e `round`, que só leem), mas a regra agora
abre a transação. Também passam a abrir: `set_config` e `EXPLAIN ANALYZE`.
Custo: uma leitura com função desconhecida faz BEGIN/ROLLBACK (um pouco mais lenta, nunca errada).
Varri o código: as únicas leituras com função fora da lista são as de `banco.py` na migração (que
roda na conexão crua, fora desta regra) e um `WITH j(...)` em `app/visao_geral.py` (tela do
operador; abre transação, sem problema).
**Anotado para o SE3:** `pg_advisory_lock` (trava de SESSÃO, não de transação) só é usado na
migração, na conexão crua, com unlock no `finally`. Trava de sessão numa conexão do pool vazaria
para o próximo dono: não há nenhuma hoje.
Testes: `tests/test_se0_consertos.py` (28 comandos difíceis que abrem, 10 leituras que não abrem,
uma função que grava de verdade e é desfeita sem commit, uma CTE com escrita desfeita sem commit).

### Fim do SE0
- Suíte inteira (3 partes seguidas, nunca duas ao mesmo tempo): 893 + 1207 + 1069 = **3169
  passaram**, 0 falhas (eram 3104 no fim da Maratona 4; +65 testes novos do SE0).
- Comportamento do Léo para o cliente: não mudou (prompt e guardas intocados; nenhum teste de
  comportamento mudou o que espera).
- Branch `seguranca-0`, tag `se0`.

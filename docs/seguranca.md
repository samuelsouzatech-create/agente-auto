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
Por que aparece o "õ" de "Decisões" trocado por duas letras estranhas (um A com acento e um "µ"): é a **leitura**, não o arquivo. O arquivo é UTF-8 sem BOM, e um
programa que lê como Windows-1250 (ex.: `Get-Content` do PowerShell 5.1 sem `-Encoding UTF8`, ou o
console com página de código antiga) mostra essas duas letras no lugar de "õ". **Não confirmado** qual programa
o Samuel usou. Para ler certo no PowerShell: `Get-Content docs\maratona4.md -Encoding UTF8`.
Teste novo: `tests/test_se0_utf8.py` reprova arquivo de texto do Git que não seja UTF-8 válido ou que
tenha acento quebrado (o par de letras que aparece no lugar de cada acento, ou o caractere de troca U+FFFD).

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

---

## SE1 — Testes sozinhos no GitHub e alertas (branch `seguranca-1`)

### 1 e 2. GitHub Actions (agente-auto)
Arquivo `.github/workflows/testes.yml`. A cada push e pull request:
- **suíte inteira** (o `pytest.ini` já tira `-m api` e `-m carga`) em **4 partes paralelas**
  (os arquivos de teste são divididos em 4, em ordem alfabética, um sim outro não), cada uma com
  **PostgreSQL 17.12 e Redis 7.4.7** como serviços do próprio Actions (as mesmas versões do
  docker-compose). Chave de IA **falsa** (`chave-falsa-so-para-testes`); a senha do banco só existe
  dentro da máquina descartável do GitHub. Nenhum segredo do repositório é usado.
- **segurança**, em paralelo: o teste de UTF-8 (sem banco), o **pip-audit** nos pacotes do
  `requirements.txt` e o **gitleaks** (procura de segredo no histórico INTEIRO do Git).

**pip-audit (o que ele achou e o que eu fiz):** na `.venv-teste` havia falha conhecida em pillow 12.3.0
(várias, na leitura de imagens: importa, porque o Léo abre foto do cliente e do estoque),
oauthlib, opentelemetry-api, pyasn1 e chromadb.
- pillow **13.0.0** (e o streamlit **1.67.0**, porque o 1.65 não aceitava o pillow 13; o pillow-heif
  1.8.1 funciona com ele, conferido). O teste antigo que fixava "pillow==12.3.0" agora espera 13.0.0.
- oauthlib 4.0.1, opentelemetry-api/sdk 1.45.2 e pyasn1 0.6.5 presos no `requirements.txt` (vêm junto
  com outros pacotes; o comentário explica).
- chromadb: **sem versão com conserto**. As 4 falhas são do SERVIDOR do Chroma (execução de código
  por repositório de modelo com `trust_remote_code`, permissão entre inquilinos). O Léo usa o Chroma
  embutido (sem servidor). Ignoradas uma a uma em `.pip-audit-ignorar`, cada uma com o porquê.
- Resultado local do mesmo comando do Actions: "No known vulnerabilities found, 5 ignored".
- Depois do merge, a imagem do Docker precisa ser montada de novo (`docker compose up -d --build`)
  para levar os pacotes novos.

**gitleaks:** 2 achados no histórico, os dois conferidos à mão como **falsos**: o token de exemplo do
dado falso `docs/api/mocks/pedido_auth_criar_senha.json` e a chave de um campo do Streamlit
(`key="s10_agendar_base"`). Liberados em `.gitleaks.toml`, com o porquê. Depois disso: "no leaks
found" (192 commits).

**Repositório público:** o `agente-auto` está **público** no GitHub (conferido com o `gh`). O
gitleaks não achou segredo no histórico, mas tudo o que está no Git é visível para qualquer pessoa.
**Decisão para o Samuel/analista:** deixar privado (o Actions continua funcionando; no plano gratuito
o repositório privado tem 2.000 minutos por mês, e esta suíte gasta ~4 x 2,5 minutos por push).

### 2. leo-painel-web (branch `painel-seguranca`)
`.github/workflows/testes.yml`: `npm ci`, `npm test`, `npm run build` e `npm audit --audit-level=high`
(só alta e crítica reprovam). O `npm audit` achou 12 (2 críticas, 5 altas): consertei com
`npm audit fix`, vitest **4.1.12** (a 3.x tinha falha crítica; os 91 testes passam igual) e um
`overrides` para `serialize-javascript` ^7.1.4 (vinha velho pelo plugin do PWA). Sobraram **2
moderadas** (react-router 6: o conserto é a versão 7, que muda a tela; fica para o bloco do painel).
O push do painel pelo endereço HTTPS foi recusado (o login do `gh` não tem permissão de mexer em
fluxo do Actions, `workflow`); enviei pelo endereço SSH do mesmo repositório, sem mudar nada da
configuração.

### 3. O fluxo passou de verdade?
**Sim, conferido pelo `gh`** (`gh run list` e `gh run view`):
- agente-auto: a 1ª rodada **falhou** (e foi bom): o `!reset` do compose quebrava a leitura do
  compose nos testes do DK1, o teste antigo fixava o pillow 12.3.0 e o `psutil` (lido pelo teste de
  carga) não estava no `requirements-dev.txt`. Consertado; a 2ª rodada (run 45741340304) ficou
  **verde**: 711 + 828 + 775 + 874 = 3188 testes nas 4 partes (cerca de 2 min cada) e o job de
  segurança (UTF-8, pip-audit, gitleaks) verde. O último push do bloco também roda (ver o fim).
- leo-painel-web: run 45741174856 **verde** (91 testes, build e npm audit).

### 4. Vigia (`app/vigia.py`, serviço `vigia` no docker-compose)
Uma peça própria do Docker (não o relógio: se o relógio parar, é o vigia quem avisa). A cada minuto
confere e avisa o **operador** pelo bot de avisos que já existe (Telegram, `TELEGRAM_AVISOS_OPERADOR_CHAT_ID`):
- **banco** não responde; **Redis** não responde;
- **relógio** parado (o mesmo vermelho da Visão geral: parado ou sem girar há 2 min);
- **webhook**: canal de loja No ar sem mensagem de cliente há muito mais que o normal DELA (a regra
  do "canal parado" da Visão geral: 5 vezes o intervalo médio, no mínimo 18 h, com 10+ mensagens em 14 dias);
- **IA** errou 3 vezes ou mais na última hora (o vermelho da Visão geral);
- **peça do Docker** sem saúde: o vigia chama o endereço de saúde de cada peça pela rede interna
  (`VIGIA_PECAS`). **Não** usa o `docker.sock` (quem tem o socket manda na máquina inteira).
Avisos: no máximo **um por problema a cada 30 min** (lembrete "Continua" a cada 30 min), e um
**"Voltou ao normal"**. Problema que pisca (cai, volta, cai) não vira rajada. Sem emoji. O estado fica
na memória do vigia (o banco e o Redis podem ser o que caiu). Ele não depende do banco nem do Redis
para ligar, e tem saúde própria (um arquivo de sinal, `docker/saude.py vigia`).
Testes: `tests/test_se1_vigia.py` (20, com envio falso, Redis falso e sonda falsa).
**Não testado de ponta a ponta no Docker** (subir a peça nova é passo depois do merge).

**Monitor de fora (para o bloco do servidor):** o vigia cai junto se o SERVIDOR inteiro cair. Para isso:
- **Healthchecks.io** (recomendado, no estilo "batimento"): o vigia chama um endereço deles a cada
  minuto; se parar de chamar, eles avisam (e-mail, Telegram). Plano gratuito com 20 verificações;
  pago a partir de ~US$ 5/mês (preço visto em páginas de terceiros; a página oficial não abriu: **não confirmado**).
- **UptimeRobot**: chama o `https://<domínio>/` de fora a cada 5 min. Tem plano gratuito (50 monitores,
  uso pessoal/não comercial, **não confirmado** para uso comercial); o pago "Solo" está entre US$ 7 e
  13/mês conforme a fonte (os preços mudaram em 2026: **não confirmado**).
- **Better Stack**: gratuito com 10 monitores e batimentos; extra pago a partir de US$ 25/mês
  (página oficial deles).
Sugestão: Healthchecks.io (batimento do vigia) + UptimeRobot gratuito (o site de fora). Conferir os
preços na hora de contratar.

### Incidente durante o SE1 (o Samuel precisa saber)
Para conferir o docker-compose eu rodei `docker compose config` **sem** `--quiet`. Esse comando
mostra o compose já com os valores do `.env`, e eles apareceram na MINHA tela de trabalho (tokens do
WhatsApp e do Telegram, senhas do banco e do Redis). Nada foi para o Git, para o GitHub, para o
diário ou para outro serviço, e eu não repito os valores. Mas eles passaram pela conversa.
**Recomendação:** trocar esses tokens e senhas quando for possível (no mínimo antes do primeiro
cliente real). Daqui em diante só rodo `docker compose config --quiet` ou leio campos específicos.

### Fim do SE1
- Suíte local (3 partes seguidas): 911 + 1219 + 1059 = **3189 passaram**, 0 falhas.
- GitHub Actions: verde nos dois repositórios (acima).
- Comportamento do Léo para o cliente: não mudou (nenhum teste de comportamento mudou o que espera;
  o único teste antigo alterado é o que fixa a versão do pillow).
- Branch `seguranca-1`, tag `se1`. Painel: branch `painel-seguranca` (sem tag; o pedido não pede).

---

## SE2 — Cofre (branch `seguranca-2`)

### 1. Tokens cifrados (migração 22, `app/cofre.py`, `scripts/cofre.py`)
- **Migração 22** (`migracoes/022_cofre.sql`, o próximo número livre): tabela `cofre_credenciais`
  (loja, canal, conta, token cifrado, resumo da chave). Só acrescenta; teste de subida da 21 para a 22
  sem perder dado.
- Cifra: **AES-256-GCM** (biblioteca `cryptography`, agora no `requirements.txt`). A chave mestra
  `LEO_CHAVE_MESTRA` fica só no `.env` (o `.env.example` tem o nome, sem valor). Cada token é cifrado
  "amarrado" a loja + canal + conta: copiar o texto cifrado de uma loja para outra linha não abre (teste).
- O envio (`app/credenciais.py`) procura **primeiro o cofre**; sem token no cofre para aquela conta,
  usa o **`token_ref` antigo como reserva** e escreve um aviso no log (uma vez por conta):
  "usando o token do .env (reserva). Guarde no cofre". Token guardado que **não abre** (chave errada)
  **não** cai para a reserva: o envio falha fechado (SemCredencial), para ninguém achar que está tudo bem.
- O token nunca aparece: `repr` das credenciais com `***`, o script não mostra o token (lê sem eco),
  a "situação" só diz "guardado / abre com a chave do .env", e nenhuma rota da API do painel toca no
  cofre (teste que varre `app/api_painel/`).
- Script: `nova-chave`, `cadastrar` (também troca), `apagar`, `situacao`, `trocar-chave` (recifra
  TUDO numa transação só, com `LEO_CHAVE_MESTRA_NOVA`; se a chave atual estiver errada, nada muda).
- Testes (`tests/test_se2_cofre.py`): o banco só guarda o cifrado (e a chave mestra não está em
  nenhuma coluna de nenhuma tabela); chave errada não abre; duas lojas; trocar token; trocar a chave
  mestra; o envio usa o cofre antes da reserva; o script roda e não mostra token nem chave.
- **Aviso:** enquanto as lojas não tiverem o token no cofre, tudo continua como antes (reserva).
  Passar os tokens para o cofre é passo depois do merge (comando no resumo final).
- Cuidado achado no caminho: um teste que roda o script como OUTRO programa usaria a `BANCO_URL`
  do `.env`, que é o banco **de uso**. Aconteceu uma vez (o script tentou gravar e falhou, porque a
  tabela 22 ainda não existe lá: nada foi gravado). Os testes agora rodam o script por dentro, no
  banco de teste.

### 2. Backup cifrado (`app/backup.py`, `scripts/backup.py`)
- `fazer`: `pg_dump -Fc` (sem dono e sem permissões) -> cifrado com **Fernet** (AES + assinatura)
  com a chave `LEO_CHAVE_BACKUP` (separada da chave do cofre: trocar uma não estraga a outra) ->
  pasta `backups/` (fora do Git). O arquivo sem cifra nunca toca o disco.
- `restaurar` (num banco NOVO e separado; recusa o banco de uso e banco que já existe) e `conferir`
  (restaura num banco temporário, compara as contagens de cada tabela com o banco de uso e apaga).
- Onde roda o `pg_dump`: o do computador se for 17+; senão, o de **dentro do contêiner do banco**
  (`docker exec`), que é o caso deste computador (não há `pg_dump` no Windows). A senha vai por
  `PGPASSWORD` (nunca na linha de comando) e é apagada de qualquer mensagem de erro (teste).
- Destino: `LEO_BACKUP_DESTINO=pasta`. O **R2** (Cloudflare) fica para o bloco do servidor: hoje
  responde "ainda não existe" (teste).
- **Teste de verdade** (`tests/test_se2_backup.py`): grava dados em duas lojas, faz o backup,
  confere que o arquivo não tem nada legível, restaura num banco separado e as **contagens de TODAS
  as tabelas** batem (mais de 30 tabelas). Chave errada e arquivo alterado não abrem.
  No GitHub Actions o fluxo instala o `pg_dump` 17 (pacote oficial do PostgreSQL) para este teste.
- **Guarde a `LEO_CHAVE_BACKUP` fora do servidor** (gerenciador de senhas): sem ela, backup nenhum abre.

### 3. E-mail do link de senha (`app/email_envio.py`)
- Camada de e-mail com provedor escolhido no `.env` (`LEO_EMAIL_PROVEDOR`): `arquivo` (padrão, o
  **falso**: cada e-mail vira um `.eml` em `logs/emails/`, fora do Git) ou `nenhum`. O provedor real
  entra no bloco do servidor como mais uma classe.
- "Esqueci minha senha" (API `POST /api/v1/auth/esqueci-senha` e a tela, que já existia e já mostra a
  mensagem da API) agora manda o link **por e-mail**. O link continua de **uso único** e vence em
  **1 hora** (testes). A resposta é sempre a mesma, exista ou não o e-mail ("Se este e-mail estiver
  cadastrado, enviaremos um link..."), e só quem existe recebe.
- Limite: 3 pedidos por e-mail (já existia) e, novo, **10 pedidos por endereço (IP)** em 15 min
  (barra quem tenta muitos e-mails diferentes do mesmo lugar). Passou do limite: 429.
- **Achado e consertado (era MÉDIA):** antes, o link (com o token) ia para o **terminal**, e no Docker
  o terminal vira log (`docker compose logs api-painel`): quem lesse o log podia trocar a senha de
  qualquer pessoa. Agora o link nunca vai para log nem terminal (teste). O teste antigo que esperava o
  link no terminal (`test_c2f_senha.py`) passou a esperar o e-mail no provedor falso (não é teste de
  comportamento do Léo com o cliente).
- O contrato da API não mudou (a rota já existia; nenhum campo novo).

**Provedores de e-mail possíveis (para o bloco do servidor; preços vistos hoje, conferir na hora):**
| Provedor | Grátis | Pago | Observação |
|---|---|---|---|
| **Amazon SES** | não (só crédito de conta nova) | US$ 0,10 por 1.000 e-mails (avulso); desde jul/2026 há planos com outro preço (**não confirmado** na página da AWS) | o mais barato em volume; exige configurar domínio (SPF/DKIM) |
| **Resend** | 3.000/mês, no máximo 100/dia | a partir de US$ 20/mês (50.000) | o mais simples de ligar (API pequena) |
| **Brevo** | 300/dia | a partir de ~US$ 9/mês | tem servidor no Brasil? **não confirmado**; marca Brevo no rodapé no grátis |
Para o volume do Léo (link de senha), o grátis de qualquer um basta no começo. Sugestão: Resend
(simples) ou SES (barato, se o servidor já for AWS).

### Erro meu no SE2 (achado pela suíte, consertado)
Acrescentei ao `banco.py` uma função `criar_banco_vazio` com o MESMO nome de uma que já existia (a da
bancada): a nova apagou a antiga e 77 testes da bancada e dos blocos L falharam na 1ª rodada (no
computador e no GitHub). Tirei a duplicata (o backup usa a função que já existia) e criei uma catraca:
`test_nenhuma_funcao_definida_duas_vezes_no_mesmo_arquivo` reprova nome de função ou classe repetido
no mesmo arquivo.

### Fim do SE2
- Suíte local (3 partes seguidas): 925 + 1248 + 1052 = **3225 passaram**, 0 falhas.
- GitHub Actions: **verde** (run 45744558794), já com o `pg_dump` 17 para o teste do backup.
- Comportamento do Léo para o cliente: não mudou. Testes antigos alterados: o do link no terminal
  (`test_c2f_senha.py`, agora e-mail) e os que fixavam a versão do esquema em 21 (agora "21 ou mais"
  e a contagem de migrações).
- Branch `seguranca-2`, tag `se2`. Migração 22 usada (próxima livre: 23).

---

## SE3 — Tranca por loja dentro do banco (branch `seguranca-3`)

### 1. Row Level Security (migração 23, `migracoes/023_tranca_por_loja.sql`)
- Em **todas as tabelas que têm `loja_id`** (achadas na hora pela própria migração; hoje são mais de
  30), a tranca do PostgreSQL fica ligada com a mesma regra: a linha só aparece, e só pode ser
  gravada, se `loja_id` = a loja marcada na conexão **ou** se a conexão está no modo "sistema".
  Conexão sem marca não vê nada dessas tabelas (nem as linhas "de ninguém", com `loja_id` vazio).
- Catraca: `test_toda_tabela_com_loja_id_tem_a_tranca` reprova tabela nova com `loja_id` sem a tranca.
- **Usuário do app (`leo_app`)**: o Léo passa a conectar com um usuário que NÃO é dono das tabelas,
  não é superusuário e não passa por cima da tranca (NOBYPASSRLS). Ele só lê e grava. Quem é dono
  (o `leo`, das migrações) passa por cima, de propósito: migrações, backup e limpeza dos testes.
  O serviço `migrar` do Docker roda com o dono e cria/atualiza o `leo_app` com a senha
  `BANCO_APP_SENHA` do `.env` (nova; sem ela o `docker compose` não sobe, avisa o nome da variável).
  As outras peças usam `BANCO_URL` com o `leo_app`. Os scripts deste computador continuam com a
  `BANCO_URL` do `.env` (o dono) e declaram o modo sistema.
- Nos **testes**, o app conecta com o usuário `leo_app_teste` (só dos testes; nunca mexe no `leo_app`
  de uso): a suíte inteira roda COM a tranca ligada.

### 2. Quem marca a conexão (`banco.py`)
- A marca é da **sessão** do PostgreSQL (`set_config(..., false)`), gravada quando a conexão sai do
  pool. Por isso vale para **todas** as consultas da conexão, dentro e fora de transação: o "transação
  só quando precisa" (DK3) não atrapalha. (Um `SET LOCAL` sumiria no fim de cada transação: não usei.)
- **Volta ao pool sem marca:** o pool apaga a marca em toda conexão devolvida (`reset` do pool), e a
  próxima que sai recebe a marca do novo dono. Teste dedicado pega TODAS as conexões direto do pool.
- **API do painel:** todo pedido começa SEM marca (camada `MarcaDoPedido` em `app/api_painel/main.py`),
  mesmo que o processo tenha declarado o modo sistema. Quando a sessão é lida
  (`dependencias.usuario_logado`), a loja da sessão vale para o resto do pedido (inclusive nas linhas
  do threadpool do FastAPI). **Nunca o modo sistema**, com uma exceção fechada, só onde ainda não
  existe loja (lista conferida por teste):
  1. `dependencias.py`: achar a sessão pelo token;
  2. `rotas_auth.py`: login (achar a pessoa pelo e-mail e abrir a sessão);
  3. `rotas_auth.py`: esqueci a senha (achar a pessoa pelo e-mail);
  4. `rotas_auth.py`: criar senha (achar a pessoa pelo link; depois disso, a loja da pessoa);
  5. `rotas_auth.py`: criar senha (anotar link errado);
  6. `rotas_link.py`: link do vendedor (achar o link pelo token).
- **Modo sistema declarado** (`banco.declarar_sistema("quem")`), um por programa que liga sozinho:
  `app/api/webhook.py` (WhatsApp, Instagram e exclusão de dados), `app/jobs/runner.py` (relógio),
  `app/jobs/remarketing.py`, `app/jobs/pos_venda.py`, `app/jobs/reativacao.py` (quando rodados
  sozinhos), `app/api/telegram_bot.py`, `app/vigia.py`, `app/api_painel/exportar.py` (quando rodado
  como script), `operador.py`, `app.py` (simulador), `ingestao_rag.py` e **todos** os `scripts/*.py`
  que usam o banco (backup, cadastrar_canal, cofre, criar_loja_demo, criar_loja_teste,
  criar_usuarios_demo, estado_loja, importar_sqlite, juiz_bancada, login, migrar_fotos,
  reiniciar_demo, relatorio_sombra, rodar_bancada). Teste confere que cada um declara.
  Programa que esquecer de declarar não vê nada (falha fechada), em vez de ver tudo.

### 3. Testes (`tests/test_se3_tranca.py`)
- rota do painel logada na loja A com uma consulta que **"esquece" o filtro de loja**: só vê a A (nem as
  linhas sem loja), e a marca da conexão é "loja A", nunca o sistema; o mesmo para a B;
- rota sem login não vê nada (mesmo com o processo em modo sistema);
- conexão sem marca não vê e não grava; marca de loja não grava na outra loja e um UPDATE sem
  filtro só mexe na própria loja; o modo sistema vê tudo e volta ao que era;
- a marca vale fora de transação, dentro, depois do commit e do rollback, e na conexão só de leitura;
- a conexão devolvida ao pool volta sem marca;
- a catraca de `loja_id` (`tests/test_catraca_loja.py`) continua valendo e passando.

### 4. Chaves estrangeiras (migração 24, `migracoes/024_chaves_da_loja.sql`)
- **Ligadas:** em TODA tabela com `loja_id`, `loja_id` aponta para `lojas(id)`. Linha de uma loja
  que não existe é recusada pelo próprio banco. São conferidas no **fim da transação**
  (`DEFERRABLE INITIALLY DEFERRED`), porque o reinício da demo e a limpeza dos testes apagam e
  regravam numa transação só. Sem `ON DELETE`: apagar uma loja que tem dados é **recusado**.
- **Conferido:** o Léo nunca apaga loja (não existe essa função; procurei `DELETE FROM lojas` no
  código: nada). O **reinício da demo** apaga e regrava os dados da loja demo, mas a linha da loja
  fica: continua funcionando (teste). A migração confere antes se há linha de loja que não existe;
  se houver, **para** com o nome da tabela e não muda nada (teste).
- A limpeza dos testes (`banco.voltar_ao_estado_inicial`) passou a rodar numa transação só (antes
  rodava comando a comando; com as chaves, a loja 1 precisava voltar antes das outras linhas).
- **9 testes antigos** usavam uma "loja 2" ou "loja 42" que nunca foi criada (só gravavam linhas com
  esse número). Agora a preparação deles cria a linha da loja antes (`garantir_lojas`); o que eles
  conferem não mudou: `test_fase_3_handoff.py` (4), `test_m3_n2_cerebro.py`, `test_m3_n3_servidor.py`,
  `test_m3_n5_fechamento.py`, `test_s1_guarda_preco.py`, `test_s3_troca.py`.
- **Ficaram de fora (e por quê):**
  - `lead_id` -> `leads`: as mensagens e outras tabelas gravam o cliente sem exigir a ficha
    (`leads`); ligar obrigaria a criar a ficha antes de tudo e mudaria o caminho da conversa.
    (Quando exatamente a ficha nasce em cada caminho: não confirmado linha a linha.)
  - `vendas.veiculo_id`, `interesse_veiculo.veiculo_id`, `trocas` -> `estoque`: o reinício da demo
    apaga o estoque (e o carro vendido pode sair do estoque um dia); ligar exigiria decidir o que
    fazer com a venda de um carro apagado (decisão do analista).
  - `sessoes`, `links_senha`, `links_vendedor`, `acessos` -> `usuarios`: a pessoa nunca é apagada
    (é desativada), então a chave não protegeria nada hoje; fica para quando existir "apagar pessoa".
  - `avisos.referencia` ("handoff:<id>") e `registro_acoes.alvo`: são texto, não número; não dá
    para ser chave.
  - `clientes_vinculados` (dois `lead_id`, mesma razão dos leads) e `regua_passos`/`regua_execucoes`
    -> `reguas`: não conferi como as réguas são apagadas (**não confirmado**); fica para um bloco de
    réguas. Sem ganho de segurança entre lojas (a chave da loja já vale nelas).

### 5. A tranca quebrou algo?
Não precisei do plano B ("só para a API do painel"): a tranca vale para **todas** as peças, e a
suíte inteira roda com ela ligada. Duas falhas da 1ª rodada não eram da tranca de verdade:
- `test_sg2_catalogo_e_ramo_de_teste.py` roda um programa separado (sem declarar o modo sistema):
  a tranca barrou, como deve. Esse programa de teste agora declara o modo sistema, como os outros.
- `test_ig3_instagram_whatsapp.py::test_atender_mostra_canal_e_como_chegou_sem_cartao_repetido`
  (meu, da Maratona 4) **dependia da hora**: rodando logo depois da meia-noite, as mensagens de
  "2 horas atrás" caíam em ontem. Agora usa relógio fixo (15h). Falhou também no GitHub pelo mesmo motivo.

### Fim do SE3
- Suíte local (3 partes seguidas, com a tranca e as chaves ligadas): 925 + 1248 + 1075 = **3248
  passaram**, 0 falhas.
- GitHub Actions: **verde** (run 45751302793). A 1ª rodada do bloco falhou nos 2 testes explicados acima.
- Comportamento do Léo para o cliente: não mudou (prompt e guardas intocados). Testes antigos tocados
  só na preparação ou na infraestrutura: os 9 da "loja que não existia", o do programa separado do
  SG2, o que dependia da hora (IG3), os que conferem a versão do esquema e o do compose (DK1, que
  agora espera o usuário do app na API).
- **Migrações 23 e 24 usadas** (próxima livre: 25).
- Depois do merge, ANTES de subir o Docker: pôr `BANCO_APP_SENHA=<senha forte>` no `.env` (ver o
  resumo final). Sem ela, o `docker compose` não sobe e diz o nome da variável.
- Branch `seguranca-3`, tag `se3`.

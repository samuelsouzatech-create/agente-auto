# Decisões e roteiro do projeto Léo

Data: 23/11/2026 (texto do Samuel com o analista; o índice e o "Registro de mudanças" foram
acrescentados no PG0 da Maratona Postgres, sem mudar o texto original).

Memória oficial das decisões. Antes de qualquer bloco, leia este arquivo. Se o seu trabalho
contradizer uma decisão daqui, PARE e avise o Samuel.

## Índice
1. Hospedagem e Docker: Docker com tudo num "docker compose"; Hostinger em São Paulo, fotos no Cloudflare R2.
2. Banco de dados: PostgreSQL antes da primeira loja real, com a memória das conversas; Chroma por enquanto.
3. Arquitetura e multissegmentos: monólito modular; o pacote de ramo só quando o segundo segmento for real.
4. Engenharia: faltam testes automáticos no GitHub (CI) e alerta quando algo cai.
5. Segurança: camadas (servidor, HTTPS, criptografia, login, tranca por loja no banco), LGPD e revisão OWASP.
6. A ordem: Fotos → PostgreSQL → Docker → Segurança e práticas → Servidor → Pacote de ramo.
7. Recapitulação do plano mestre: o que foi feito, o que falta (E2-1, E2-4, aposentar o Streamlit do
   cliente, teste ponta a ponta, e-mail de senha) e o caminho até a primeira loja (técnico e de negócio).

---

 "Resposta curta: os quatro pontos que você levantou precisam de atenção antes de vender. Nenhum deles exige jogar o projeto fora. São três mudanças de estrutura, que viram blocos de trabalho:

Banco: a troca para PostgreSQL não foi feita e precisa ser feita antes da primeira loja real, não só quando passarmos de 10 lojas.
Docker: seguir com ele é a decisão certa.
Segmentos: a base é boa, mas o "cérebro" ficou com muita coisa de carro. Isso se separa quando o segundo ramo chegar.
O resto do projeto está bem encaminhado.

O que conferi
Li o arquivo do banco inteiro (banco.py) e o README, na main. Antes já tinha lido o cérebro do Léo e o arquivo de segmentos.

Não verifiquei duas coisas:

se o projeto tem um arquivo Docker próprio. O README só menciona o Redis rodando em Docker;
se existe teste automático rodando no GitHub a cada envio.
1. Hospedagem e Docker
O Docker é como uma marmita fechada. Cada peça do Léo vai numa caixa com tudo o que precisa para funcionar. A mesma caixa roda no seu computador e em qualquer servidor. Para o Léo, isso é ainda mais útil, porque ele tem várias peças rodando juntas:

a porta que recebe as mensagens do WhatsApp;
a API do painel;
o relógio das retomadas e do pós-venda;
o Redis;
o banco;
o painel em React;
o "porteiro" que cuida do HTTPS.
Com o Docker, o servidor só precisa saber abrir as caixas. Trocar de empresa de hospedagem vira questão de horas, não de semanas. Decisão: seguimos com Docker, com todas as peças descritas num arquivo só (o "docker compose").

As opções que fazem sentido para o nosso caso:

Opção	Onde fica	Preço aproximado	Para nós
Hostinger VPS KVM 2 (4 GB)	tem data center em São Paulo Source	R$ 42,99/mês na promoção, R$ 108,99 na renovação Source	melhor custo com servidor no Brasil
Magalu Cloud	Brasil, cobrança em reais	não achei o preço exato Source	boa para LGPD, mas é nova no mercado
Hetzner	Europa e EUA	a partir de € 5,49/mês, depois do aumento de junho de 2026 Source	barata, mas longe e com dados fora do país
DigitalOcean / AWS Lightsail	EUA (a AWS tem São Paulo, com tabela de preço própria)	cerca de US$ 24/mês por 4 GB Source	mais maduras, custam 2 a 3 vezes mais
Minha recomendação: Hostinger em São Paulo para começar, com as fotos no Cloudflare R2. No Brasil, o Léo responde mais rápido e os dados dos clientes ficam no país, e isso ajuda na conversa sobre LGPD com o lojista.

Dois cuidados. Primeiro, faça a conta pelo preço de renovação, não pela promoção. Segundo, há reclamações de clientes sobre a localização real dos servidores da Hostinger Source. Por isso, o primeiro passo do bloco é medir de onde o servidor responde de fato. E como tudo vai estar no Docker, se a Hostinger decepcionar, a mudança é rápida.

2. Banco de dados
Hoje o banco é SQLite: um arquivo único, o loja.db, com 20 migrações numeradas escritas no "jeito SQLite" Source. A troca para PostgreSQL nunca foi feita. Além disso:

a memória das conversas do Léo fica na memória do programa. O próprio código anota que, em produção, ela vai para o PostgreSQL;
a base de conhecimento (o RAG) fica em outro arquivo, o do Chroma.
O SQLite funcionou muito bem para construir e testar, mas não serve para produção, por três motivos:

Várias peças escrevendo no mesmo arquivo. O webhook, a API e o relógio escrevem ao mesmo tempo. O ajuste da Maratona 3 alivia isso, mas o SQLite foi feito para um programa por vez.
Backup e recuperação. O PostgreSQL tem cópia contínua e permite voltar o banco para um minuto exato do passado. No SQLite, isso tudo seria feito à mão.
Segurança por loja. O PostgreSQL tem um recurso que tranca cada linha por loja dentro do próprio banco. Mesmo que um código novo esqueça o filtro de loja, o banco recusa mostrar dados de outra loja. É uma segunda tranca, além da catraca que já temos nos testes.
Decisão: migrar para PostgreSQL antes da primeira loja real. É um bloco médio para grande. As migrações usam comandos que só o SQLite entende, e existe uma função de busca sem acento feita dentro dele. Os mais de 2.800 testes são a nossa rede de segurança: a troca está pronta quando todos passarem rodando no PostgreSQL. A memória das conversas vai junto para o PostgreSQL.

O Chroma pode continuar por enquanto. Mais tarde, o próprio PostgreSQL pode guardar a base de conhecimento (com uma extensão chamada pgvector), e assim fica uma peça a menos para cuidar.

3. Arquitetura e multissegmentos
Hoje o Léo é o que se chama de monólito modular: um programa só, organizado em partes bem separadas. Para o nosso tamanho, esse é o desenho certo. Separar em vários programas pequenos, os "microsserviços", só traria custo e complicação agora. Empresas bem maiores que a nossa trabalham assim.

O que precisa mudar, quando chegar a hora, é o que fica no motor e o que fica no ramo:

O motor, que serve para qualquer ramo: canais, conversa, chamado ao humano, painel, login, retomadas, pós-venda, custos e a trava de não inventar.
O pacote do ramo, uma pasta para cada segmento: a personalidade, as ferramentas, as travas próprias e as conversas de teste da bancada.
Hoje muita coisa de carro está no motor: as travas de estado do carro, de valor da troca e de categoria (SUV, sedã). O banco também é de carro. O estoque tem km e câmbio, e a venda aponta para um veículo.

Cada ramo vai pedir uma coisa diferente:

Imobiliária: um "catálogo" de imóveis no lugar do estoque.
Clínica: não tem estoque, tem agenda.
Consórcio: tem cotas e simulação.
Decisão: isso não se faz agora. Quando o segundo ramo for real, o primeiro bloco dele será exatamente esse: mover as travas de carro para o pacote de veículos e trocar "estoque" por um conceito de "catálogo" que cada ramo preenche do seu jeito. Faz sentido fazer isso com um ramo real na mão, porque desenhar para um ramo imaginário costuma errar.

4. Engenharia: está correto e escalável?
O que está bem feito, de nível profissional:

testes automáticos em grande quantidade;
a catraca que impede código de cair na loja errada;
a API escrita a partir de um contrato;
as migrações versionadas;
as regras importantes travadas no código, e não só na instrução da IA;
a tela separada da regra de negócio.
Para escalar, faltam três mudanças de estrutura: o PostgreSQL, o Docker com o servidor, e o pacote de ramo, que vem mais tarde.

Também faltam duas práticas:

Testes rodando sozinhos no GitHub a cada envio (o chamado CI). Hoje quem roda é o Claude Code ou você. Com isso, nenhum código quebrado entra sem alguém perceber.
Alerta automático quando algo cai. Se o Léo parar às 3 da manhã, você recebe um aviso antes de o lojista reclamar.
5. Segurança
Pense numa loja de verdade. A segurança vem em camadas, como portão, porta, cofre e câmera. Nenhuma camada sozinha basta.

O portão (o servidor):

Só a porta do HTTPS fica aberta para a internet.
O banco e o Redis nunca ficam expostos, só as peças internas falam com eles.
O acesso de administração ao servidor é feito por chave digital, não por senha.
Um bloqueador automático barra quem tenta entrar à força.
O caminho (criptografia em trânsito): tudo passa por HTTPS. Quem estiver "escutando" a rede vê só embaralhado. Isso vale para o painel, o webhook e as fotos.

O cofre (criptografia em repouso):

O disco do servidor e os backups ficam criptografados.
Os backups vão para outro lugar, fora do servidor.
O token do WhatsApp de cada loja é guardado criptografado.
As chaves (senhas): aqui o projeto já está certo. Li no banco que a senha nunca é guardada como texto, só a versão embaralhada, que não tem volta. O mesmo vale para as sessões, os links do vendedor e os links de senha Source.

Uma diferença ajuda a entender esses termos. A criptografia é um cadeado com chave: quem tem a chave abre. O hash, usado nas senhas, é como moer a senha: não tem volta, só dá para comparar.

Quem entra:

login por pessoa;
papel de cada um;
isolamento por loja, que já é testado;
a tranca por loja do PostgreSQL, como segunda barreira.
O risco próprio de IA: alguém conversar com o Léo para arrancar dados de outro cliente. Isso já está bem protegido. A IA não escolhe de qual loja nem de qual cliente busca os dados, o código carimba isso.

LGPD:

guardar só o necessário;
apagar o que vence (a sombra já apaga depois de 30 dias);
respeitar o "não quero mais contato", que já existe;
um contrato com o lojista dizendo quem é responsável por quê.
Esse contrato é para um advogado revisar. Eu não sou advogado.

Antes de lançar: uma revisão de segurança dedicada, testando como um invasor testaria. Pode ser um bloco do Claude Code seguindo uma lista conhecida de ataques comuns a sites, a OWASP. Quando houver dinheiro, vale contratar alguém de fora para isso.

A ordem que eu decido
Maratona Fotos, que já está pronta para rodar.
PostgreSQL, com a memória das conversas e todos os testes passando nele.
Docker no seu computador: todas as peças subindo com um comando só, com o porteiro do HTTPS.
Segurança e práticas: os testes automáticos no GitHub, os alertas, o token criptografado, a tranca por loja no banco e a revisão de segurança.
Servidor de verdade: contratar, publicar, fazer o teste de carga com 10 lojas e rodar as 2 bancadas que faltam, já com crédito do Gemini.
Pacote de ramo, quando o segundo segmento existir.
Cada etapa usa a anterior. O Docker já sobe com o PostgreSQL, e a segurança é aplicada sobre o desenho final. Quando a Maratona Fotos voltar e for aprovada, eu monto o pedido do bloco do PostgreSQL.





CLAUDE.md
5.09 KB
estado_do_projeto_2026-11-16.md
6.71 KB
Plano Mestre de Execução — Léo painéis, pendências da Etapa 2, Etapas 3 e 4.md
69.02 KB
Antes de vc aprovar a maratona de fotos e montar  o pedido do bloco do PostgreSQL, vamos recaptular onde estamos o que tinhamos a fazer e como esses novos blocos se encaixam com tudo aquilo que ainda temos que implementar...
Análise e Pré-processamento de Documento
https://www.genspark.ai/api/files/s/5KaRY5Px
Visualizar
Buscar e Responder do Documento
O que diz a parte final do documento: Fase 8 (demo), Etapa 4, Etapa 5, seção 16, seção 17 (numeração de migrações), marcos e trilha sem código? Liste cada bloco e o que falta. (+3)
Visualizar
Resumo: o plano mestre de 1º/11 está quase todo cumprido, e fizemos bastante coisa além dele, principalmente a Fase Cérebro. Para a primeira loja real faltam três frentes, que andam juntas:

Técnica: fotos, PostgreSQL, Docker, segurança e servidor.
Produto: ensaiar a demo e fechar algumas pontas soltas do plano.
Negócio, que é sua: MEI, Meta, contrato e preço.
A frente de negócio é a que mais demora, porque a verificação da Meta leva semanas.

Montei este resumo a partir dos três arquivos que você mandou e do que fizemos nesta conversa. Uma ressalva: a ferramenta não conseguiu ler o fim do plano mestre, cerca de 6 mil letras. A parte da Etapa 5 e a seção 17, com a numeração oficial das migrações, não apareceram para mim.

1. O plano mestre: o que já foi feito
Fase do plano	O que era	Situação
0 a 2	limpar o código, segurança, login, "loja em teste"	feito
3	painel do operador em Streamlit	feito
4	testes com o Gemini real	feito, e depois ampliado pela Fase Cérebro
5	contrato e API do painel do cliente	feito
6	painel do cliente em React	feito: versão 1 na main e a 1.1 esperando merge
7	Instagram	não começou, depende do MEI e da Meta
8	demo	construída; falta o ensaio, que precisa de crédito do Gemini
2. O que fizemos fora do plano
A Fase Cérebro inteira, com a bancada de conversas e mais de 2.800 testes.
Áudio do cliente.
Leitura de foto do cliente.
Recados da equipe para o Léo.
Regra dos emojis.
Limites de tamanho de mídia.
Modo sombra: construído e guardado, sem uso por enquanto.
A demo no painel novo.
3. O que ainda falta do plano
Limite diário da reativação (bloco E2-1). Ele impede que uma base importada dispare centenas de mensagens num dia só e queime o número da loja. Não sei se foi feito. Decisão: o Claude Code confere no próximo bloco e, se não existir, constrói. Ele precisa estar pronto antes do primeiro envio real.
Revisão da régua e do job de envio (E2-4). Era tarefa do analista e ninguém fez. Decisão: eu faço antes do primeiro envio real.
Aposentar o painel Streamlit do cliente. É o último critério do painel novo. Decisão: sai junto com a etapa do Docker, porque não vale empacotar uma peça que vai ser jogada fora. O painel do operador continua em Streamlit.
Teste de ponta a ponta com canal de verdade (bot real, Redis e IA juntos). O estado do projeto de 16/11 marca isso como nunca feito. Decisão: entra na etapa do servidor, numa loja fictícia, pelo Telegram.
E-mail para o link de senha. Hoje o link sai no terminal. Para o piloto, você mesmo pode redefinir a senha do lojista. O e-mail entra na etapa de segurança.
Demo:
o ensaio e o vídeo de reserva ficam para quando houver crédito;
a proposta de uma página e a ficha de perguntas da reunião, não sei se existem.
Contrato com o lojista, incluindo LGPD e o consentimento da base importada. Isso é com advogado.
4. Decisões antigas que mudaram
Os documentos que o Claude Code lê antes de cada bloco ficaram para trás:

O plano dizia fotos só por endereço de internet. Agora é envio pelo painel, com depósito próprio.
O plano é todo em SQLite e não fala de Docker nem de hospedagem. Agora vamos para PostgreSQL, com Docker.
O CLAUDE.md diz "18 é do Instagram, 19 dos recados". Hoje a 21 está reservada ao Instagram e a 22 já foi usada. Isso é perigoso: o Claude Code pode criar uma migração com o número errado.
O plano e o estado do projeto dizem que a tela seria feita por uma "plataforma". Quem fez foi o Claude Code.
Decisão: o primeiro passo do bloco do PostgreSQL será atualizar o CLAUDE.md, escrever um estado do projeto novo e anotar no plano mestre as decisões que mudaram. É pequeno, e evita que o Claude Code trabalhe com regras velhas.

5. O caminho até a primeira loja
Na frente técnica, em ordem:

Maratona Fotos. Esperando a minha validação.

PostgreSQL, junto com a atualização dos documentos e a conferência do limite diário da reativação.

Docker no seu computador. Todas as peças sobem com um comando, e o Streamlit do cliente é aposentado.

Segurança e práticas:

testes rodando sozinhos no GitHub;
alertas;
token criptografado;
tranca por loja no banco;
e-mail de senha;
revisão de segurança.
Eu faço, em paralelo, a revisão da régua.

Servidor: contratar, publicar, fazer o teste de carga com 10 lojas, o teste de ponta a ponta pelo Telegram e as 2 bancadas que faltam.

Demo ensaiada e proposta, quando houver crédito. Dá para fazer em qualquer momento a partir daqui.

Loja piloto: carregar os dados reais, uma semana de ensaio com a equipe e depois o piloto vigiado.

Depois da primeira loja vêm:

o Instagram;
a comparação do Gemini com o Claude Haiku;
o Estoque refeito, com a integração de CRM;
o pacote de ramo, quando surgir o segundo segmento.
Na frente de negócio, que é sua e anda em paralelo, desde já:

Abrir o MEI e pedir a verificação da Meta. Sem isso, não existe WhatsApp real, e sem WhatsApp real a etapa 7 não acontece.
Decidir entre a conta da Meta direto ou um provedor, como o 360dialog. Eu pesquiso e te trago a comparação quando você quiser.
Advogado para o contrato e para a política de privacidade.
O preço da proposta. Depende do custo real que vamos medir no servidor.
O domínio, o endereço do painel.
Se a parte técnica terminar antes da Meta aprovar, a loja piloto pode começar pelo Telegram ou pelo simulador, para a equipe ir treinando. O atendimento de clientes de verdade só começa com o WhatsApp aprovado.

O próximo passo é você me mandar o diário da Maratona Fotos e os nomes das branches. Eu valido e depois monto o pedido do PostgreSQL, já com a atualização dos documentos dentro."

---

## Registro de mudanças
Cada bloco anota aqui, em 1 ou 2 linhas, o que mudou nas decisões (ou "nada mudou").

- 23/11/2026, PG0 (Maratona Postgres): E2-1 conferido: não existia; construído (limite diário da
  reativação, padrão 30, número final na decisão A8). Aviso: o texto acima diz que "a 22 já foi
  usada"; no repositório não existe migração 22 (usadas: 1 a 17, 19, 20; 21 reservada ao
  Instagram). A próxima livre é a 22.
- 23/11/2026, PG1: banco = PostgreSQL 17 (docker compose só com o banco), camada única de
  conexão, base equivalente à v20 registrada como versão 20; próxima migração livre: 22. Datas
  seguem texto UTC e sem chaves estrangeiras (como no SQLite); a tranca por loja fica para Segurança.
- 24/11/2026, PG2: memória das conversas no PostgreSQL (PostgresSaver, limite do L12 mantido);
  importação do loja.db conferida (40 tabelas). Chroma segue como está. Nenhuma decisão mudou.
- 24/11/2026, PG3: 10 lojas ao mesmo tempo sem perder nem cruzar mensagem (depois de 2 consertos
  no Redis). Nova pendência para decidir: o turno fica lento com muitas lojas (acesso ao banco
  síncrono). Pedido para o bloco Docker: Redis só em 127.0.0.1.
- 24/11/2026, DK0 (Maratona Docker): mapa das peças em `docs/docker.md`. Nada mudou. Vistos: portas
  desencontradas na documentação (operador 8501 × 8502) e o webhook sem comando escrito.
- 24/11/2026, DK1: tudo sobe com `docker compose up -d` (Caddy na frente; só a porta dele aberta,
  em 127.0.0.1 no PC; Redis com senha e só em 127.0.0.1, como pedido no PG3). Nenhuma decisão mudou.
  Operador e simulador (sem login) ficam sempre só no computador (no servidor: túnel SSH).
- 24/11/2026, DK2: o Streamlit do cliente **não** foi aposentado: o painel novo não tem
  Configuração, Conhecimento nem Usuários (existem no operador). Decidir se o operador cobre isso no
  piloto (o plano mestre aceita "no painel novo ou no operador"). A suíte passou a usar a gaveta 15
  do Redis (não suja mais o Redis de uso).
- 24/11/2026, DK3: turno numa linha separada (thread, não banco assíncrono), memória das conversas
  sem a trava única e transação só quando precisa no banco.py. Turno médio −33%, espera do cliente
  −50%, 0 perdidas e 0 cruzadas. Nenhuma decisão mudou. Pendência resolvida: "turno lento com
  muitas lojas" (PG3).
- 24/11/2026, AR (Maratona 4): **Streamlit do cliente aposentado** (decisão do analista pela D11:
  no piloto o operador faz Configuração, Conhecimento e Equipe pelo lojista). Teste de carga na
  gaveta 14 do Redis (nunca na 0). Portas documentadas: operador 8502, simulador 8501, webhook 8000.

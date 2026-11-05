Painel do operador: reformulação  
Documento de escopo v1 · Projeto Léo · branch painel-api · 31/10/2026

Base: Arquitetura Técnica 4.0, Etapas 1 e 2 concluídas (tag etapa-2-concluida), banco no schema v8, documento "Painel do cliente: reformulação" v1.1 (aprovado com ajustes)

Para: analista, para aprovação

0\. Para que serve este documento  
Este documento descreve como o painel do operador funciona hoje no Streamlit, os problemas que encontramos e o novo desenho proposto. Ele serve de escopo para a construção e pede a aprovação do analista nos pontos da seção 13\.

O painel do operador é usado só pela nossa equipe. Hoje esse operador é o Samuel. Por isso ele segue uma lógica diferente da do painel do cliente. O painel do cliente precisa ser enxuto, porque o dono só confere. Já o do operador precisa ser completo, porque é nele que cada loja é implantada, configurada e acompanhada. O objetivo aqui não é cortar funções. É organizar o que já existe, tirar o que é técnico ou repetido e acrescentar o que falta para operar várias lojas com segurança.

1\. O que herdamos do documento do painel do cliente  
Algumas decisões já aprovadas valem também para este painel e não são rediscutidas aqui:

Decisão herdada	Como se aplica ao operador  
Login por pessoa	O operador entra com login próprio. Cada login guarda um papel  
Regra de negócio na API FastAPI sobre app/	O painel do operador usa a mesma API, com rotas e permissões próprias  
Tela em React \+ Vite \+ TypeScript \+ Tailwind	Mesma tecnologia e mesmos componentes. O PWA é opcional para o operador  
Caminho único de venda (registrar\_venda)	O operador não tem outro botão de venda  
Horário no fuso da loja, calculado na API	Acaba o UTC em todas as telas do operador  
Configuração toda com o operador (no piloto)	O operador concentra toda a configuração. A ressalva do analista continua valendo: reavaliar depois do piloto  
Nada técnico à vista	Nada de comandos de terminal, ids ou reinícios na tela  
2\. Como é hoje (Streamlit)  
O painel abre com python \-m streamlit run operador.py. Ele não tem login e roda só no computador local. O seletor de loja (paginas/operador\_sessao.py) fica no topo, e as telas vêm de paginas/menu.py, que monta três grupos:

Grupo	Tela (arquivo)	O que faz hoje  
Atendimento	Fila de handoff (handoff.py)	Clientes esperando vendedor, com cores por tempo  
Atendimento	Conversas (conversas.py)	Acompanhar, assumir, responder, devolver, marcar venda  
Atendimento	Resultados (resultados.py)	Marcar compareceu, comprou ou perdeu (registrar\_resultado)  
Atendimento	Retomadas e pós-venda (envios.py)	Fila, histórico, resultado do mês e pausa geral  
Loja	Estoque (estoque.py)	Cadastrar, editar, dar baixa (outro caminho de venda)  
Loja	Configuração (configuracao.py)	Campos do "dono cliente"  
Loja	Conhecimento (conhecimento.py)	Documentos que o Léo consulta. Em caso de erro, pede python ingestao\_rag.py  
Loja	Usuários (usuarios.py)	Vendedores e gestores, com Id do Telegram para avisos  
Operador	Lojas e canais (lojas\_canais.py)	Criar e renomear loja, cadastrar canal pelo nome da variável do .env, aviso de "modo de transição" da loja 1  
Operador	Plano e limites (plano.py)	Módulos, chaves de envio, limites de remarketing e Instagram, teto diário de IA, "Confirmado no contrato"  
Operador	Custos (custos.py)	12 meses, números do mês, preços com vigência, recalcular  
Operador	Importar base (importar\_base.py)	CSV com prévia, LGPD, histórico, desfazer, pós-venda e reativação  
Os formulários de configuração saem de paginas/form\_config.py e app/config\_tela.py. Cada campo tem um "dono" (cliente ou operador), e a regra testada diz que os campos do operador são exatamente os de CHAVES\_DO\_OPERADOR. Quem salva escreve o próprio nome num campo livre ("Seu nome").

Em resumo, o operador de hoje é o painel do cliente com quatro telas a mais. São 12 telas, e é preciso escolher loja por loja.

3\. Problemas identificados  
\#	Problema	Evidência / consequência  
O1	Organização por "dono do campo", não por assunto	Um mesmo assunto aparece em várias telas. As retomadas, por exemplo, estão em Configuração, Plano e limites, Retomadas e pós-venda e Importar base. Para mudar algo, o operador precisa lembrar de quem é o campo  
O2	Não existe visão de todas as lojas	Para saber se alguma loja tem problema, é preciso abrir uma por uma. Isso não funciona a partir de 3 ou 4 lojas  
O3	Não existe saúde do sistema	Não há como ver na tela se o relógio (app.jobs.runner), o Redis, o webhook ou a IA estão funcionando. Uma falha só aparece quando um cliente reclama  
O4	Não existe caminho de implantação	O documento 4.0 (seção 12\) traz 11 passos, mas a tela não guia nem impede colocar uma loja no ar incompleta  
O5	Riscos de multi-loja	"Modo de transição" da loja 1, token conferido só quando a mensagem chega e Conhecimento que exige reinício ou comando  
O6	Horário em UTC	Em Custos, Conversas, Handoff, Resultados e Importação. Só envios.py usa hora local  
O7	Preços globais dentro da tela de uma loja	Os preços de IA e Meta valem para todas as lojas, mas ficam numa tela por loja, o que confunde  
O8	Não se sabe quem fez o quê	O campo "Seu nome" é livre. Não existe um registro único de ações (configuração, pausa, venda, importação)  
O9	Desempenho	recalcular\_custos() refaz tudo, há consulta por lead em laço e as listas não têm paginação. Isso piora com cada loja nova  
4\. Decisões  
DO1. Dois níveis. O nível Geral reúne todas as lojas: Visão geral, Custos e preços e o botão Nova loja. O nível Loja mostra uma loja escolhida: Resumo, Ver como a loja, Configuração, Mensagens automáticas, Base de clientes e Registro. São 8 telas no total, e cada assunto fica em um só lugar.

DO2. Configuração por assunto. Uma tela única, com os assuntos na lateral: Identidade, Atendimento, Equipe, Handoff, Financiamento, Conhecimento, Estoque, Canais e Plano e limites. O "dono do campo" continua existindo no código (config\_tela.py e CHAVES\_DO\_OPERADOR) para quando o cliente voltar a editar algo depois do piloto. Ele só deixa de organizar a tela.

DO3. Estado da loja: Em teste e No ar. Toda loja nasce Em teste, e nada é enviado a clientes reais. A passagem para No ar é o último passo do checklist, só o operador faz e ela fica no Registro. Esse estado substitui o "modo de transição" e a ideia de "loja em preparação".

DO4. "Ver como a loja" age só em teste. A tela é o próprio painel do cliente (Atender, Leads, Resultado, Acompanhamento) aberto dentro do operador. Com a loja Em teste, o operador pode agir (assumir, responder, registrar venda, "Não enviar", pausar), com uma faixa de aviso, e toda ação fica registrada como "feita pelo operador". Com a loja No ar, a tela é só leitura. Os botões somem, e a API recusa a ação mesmo que alguém tente forçar. Há uma exceção: pausar os envios continua liberado ao operador em qualquer estado, na tela Mensagens automáticas, como medida de emergência.

DO5. Papéis. O login guarda o papel desde já. Hoje existe só o papel operador, que pode tudo. Fica previsto o papel suporte, que poderá ver todas as lojas, acompanhar conversas e ajustar a configuração do dia a dia, sem criar loja, mexer em plano, preços e canais, ligar o envio real ou desfazer importação. Nesta versão entram só o papel gravado e o Registro. As telas e regras do suporte ficam para quando essa pessoa existir.

DO6. Registro único de ações. Uma tabela de auditoria guarda, para toda ação relevante, quem fez, com qual papel, em qual loja, quando, o que era antes e o que ficou depois. O campo "Seu nome" deixa de existir.

DO7. Saúde do sistema visível. O webhook, o relógio, o Redis e a IA mostram seu estado na Visão geral, em verde, amarelo ou vermelho.

DO8. Preços no nível Geral. Os preços de IA e Meta, com vigência, saem da tela da loja. O recálculo de custos passa a valer por mês, e não para tudo.

DO9. Computador primeiro. O painel do cliente é pensado para o celular. O do operador é pensado para o computador, com telas largas, tabelas e mais detalhes.

5\. Princípios  
Os princípios abaixo valem para todas as telas do operador.

Um assunto, um lugar. Se o operador precisa procurar onde está uma coisa, o desenho está errado.

Antes de agir, entender. Toda tela de envio mostra o que vai acontecer e, quando algo não acontece, o motivo.

Nada técnico à vista. Nada de comando de terminal, id, UTC ou "reinicie o sistema".

Segurança pela API. Permissão de papel e estado da loja são checados no servidor, e nunca só escondendo botão na tela.

Tudo registrado. Mudanças de configuração, pausas, vendas, importações e mudança de estado vão para o Registro.

Escala desde já. Telas que listam todas as lojas usam consultas agregadas e paginação, e nunca uma consulta por lead ou por loja em laço.

6\. As 8 telas  
Os esboços visuais (em Markdown) foram mostrados ao Samuel e servem de referência para o Genspark Code. Os números neles são fictícios. Abaixo está o conteúdo e as regras de cada tela.

6.1 Visão geral (Geral, tela inicial)  
Responde à pergunta "está tudo funcionando em todas as lojas?". No topo fica o bloco Saúde do sistema: receber mensagens (webhook), relógio (horário do último giro), Redis e IA (lentidão e erros na última hora). Abaixo aparece o quadro Precisa de atenção, que só surge quando há algo a resolver, como cliente esperando além do prazo vermelho, consumo acima de 90% do limite, canal sem mensagens há tempo incomum ou relógio parado. Por fim, a tabela de lojas, com estado, conversas de hoje, esperando vendedor, envios do mês sobre o limite e gasto de IA. Clicar numa loja abre o Resumo dela. A tela se atualiza sozinha.

6.2 Custos e preços (Geral)  
Mostra uma tabela por loja no mês escolhido, com conversas, custo de IA, custo da Meta, total e custo por conversa, além da linha de total. Há um botão para ver os últimos 12 meses e um botão Recalcular este mês, que deixa de recalcular tudo. Embaixo ficam os preços em vigor, com data de início, e o botão "Novo preço". O preço antigo fica no histórico, como hoje (preços com vigência já existem na Etapa 1). As datas aparecem no horário de Brasília.

6.3 Nova loja (botão no nível Geral)  
É um assistente curto, que pede nome, cidade, fuso horário e segmento. A loja nasce Em teste, e o resto é feito pelo checklist do Resumo.

6.4 Resumo (Loja)  
A tela muda conforme o estado. Em teste, mostra o checklist de implantação, baseado nos 11 passos da seção 12 do documento 4.0: loja criada, identidade, horário, equipe, estoque, conhecimento, canal conectado, teste de conversa completo, base importada (opcional), modelos da Meta aprovados e plano confirmado em contrato. Cada item é marcado sozinho quando possível (por exemplo, "equipe" fica pronto com ao menos uma pessoa ativa) ou à mão quando depende de algo de fora (por exemplo, contrato). O botão Colocar no ar só libera quando os itens obrigatórios estão prontos. No ar, o checklist dá lugar a um resumo de hoje e do mês, a alertas da loja e às últimas mudanças do Registro. Um alerta previsto é "nenhuma venda registrada há X dias". O registro atrasado não atrapalha o Léo, mas deixa o Resultado desatualizado, e o alerta permite ao operador lembrar o dono.

6.5 Ver como a loja (Loja)  
Reaproveita os mesmos componentes do painel do cliente, sem nenhuma cópia de tela. Segue a regra DO4: age em teste e só lê no ar, com faixa de aviso em cada caso.

6.6 Configuração (Loja)  
É a tela única por assunto (DO2). Cada assunto tem um formulário com "Salvar" e "Desfazer", e mostra "última alteração por quem e quando", com link para o histórico. O conflito de versão continua protegido (ConflitoDeVersao já existe). O que muda nos assuntos que vieram de telas antigas:

Assunto	Origem	Mudança  
Equipe	Usuários	Nome, papel, WhatsApp, recebe avisos, pode mandar recados (Fase B) e convite de login para dono e gerente  
Conhecimento	Conhecimento	Mostra se o documento já está em uso pelo Léo. Acabam o comando e o reinício (ver 12\)  
Canais	Lojas e canais	O token continua só no servidor (.env). A tela mostra se a chave foi encontrada e quando chegou a última mensagem, e tem um botão "Testar conexão"  
Plano e limites	Plano e limites	Módulos, limites, teto de IA e "Confirmado no contrato". As chaves de envio vão para Mensagens automáticas  
Estoque	Estoque	Mostra de onde vem o estoque (hoje, só o banco atual, conforme a seção 7 do documento do cliente) e, só quando a fonte é o banco, a edição. Acaba a baixa como caminho de venda  
6.7 Mensagens automáticas (Loja)  
É o "motor" de retomadas, pós-venda e reativação. O topo traz o modo de envio por tipo, com a chave do servidor, a chave da loja e o resultado ("enviando de verdade" ou "só simulando"), mantendo a regra atual das duas chaves. Ao lado fica o botão Pausar todos os envios desta loja, que funciona em qualquer estado da loja. Seguem o consumo do mês sobre o limite e o custo da Meta, depois os próximos 7 dias, mensagem por mensagem, com o que vai sair, o que tem "Não enviar" (quem e quando) e o que será simulado. Também aparecem as mensagens que não saíram no mês, com o motivo (fora do horário, opt-out, limite, carro vendido com oferta de parecido) e, por fim, regras e modelos: intervalos e situação dos modelos da Meta. É a versão completa da aba Acompanhamento do cliente, e responde à pergunta "por que tal cliente não recebeu?".

6.8 Base de clientes (Loja)  
É a importação CSV atual, que já foi testada e não muda por dentro. A tela mostra quantos contatos a base tem, quantos têm consentimento e quantos compraram. A importação segue em 4 passos: planilha modelo, arquivo, prévia com linhas problemáticas e confirmação ("nada é enviado aqui"). Abaixo fica a lista de importações feitas, com o botão Desfazer.

6.9 Registro (Loja ou Geral)  
É uma lista filtrável por loja, pessoa, tipo de ação e período, com data no fuso da loja, pessoa e papel, ação e antes e depois (DO6).

7\. Para onde foi cada tela antiga  
Tela antiga	Destino no novo painel  
Fila de handoff, Conversas, Resultados	Ver como a loja (abas Atender, Leads e Resultado do cliente)  
Retomadas e pós-venda	Mensagens automáticas (completa) \+ aba Acompanhamento do cliente (simples)  
Estoque	Configuração › Estoque (só quando a fonte é o banco). A baixa deixa de ser venda  
Configuração	Configuração (por assunto)  
Conhecimento	Configuração › Conhecimento  
Usuários	Configuração › Equipe  
Lojas e canais	Nova loja \+ Configuração › Canais \+ Resumo (estado da loja)  
Plano e limites	Configuração › Plano e limites \+ Mensagens automáticas (chaves de envio)  
Custos	Custos e preços (Geral)  
Importar base	Base de clientes  
Novas, sem tela antiga	Visão geral (saúde e todas as lojas), Resumo com checklist, Registro  
O Streamlit continua funcionando durante a construção, como reserva. Cada tela antiga só é removida quando a nova estiver pronta e testada. O Streamlit sai inteiro ao final.

8\. Arquitetura  
O painel do operador usa a mesma API FastAPI do painel do cliente, com rotas separadas (/api/operador/...). Toda rota confere duas coisas no servidor: o papel do login e, quando a ação mexe em atendimento, o estado da loja (DO4). A tela não guarda regra de negócio.

Saúde do sistema. O relógio grava no Redis o horário do último giro (a trava do relógio já usa Redis). O webhook grava a hora da última mensagem por canal. A IA grava tempo e erro por execução, aproveitando o registro de custos por execução que já existe. A API só lê esses dados.

Visão geral e custos. Usam consultas agregadas por loja, nunca uma consulta por lead. O resultado fica em cache curto (cerca de 30 s).

Registro. Cada função de app/ que altera algo relevante grava na tabela de auditoria, dentro da mesma transação. O histórico de configuração (historico\_config) e o histórico de pausas já existentes passam a alimentar essa visão, ou são migrados para ela (a definir na implementação, ver 12).

9\. Desempenho e escala  
O trabalho é dividido em três momentos, conforme a necessidade.

Momento	O que entra  
Junto com este painel	Consultas agregadas, índices nas tabelas mais consultadas, recálculo de custos por mês, paginação nas listas, cache curto, horário calculado na API  
Antes da 2ª loja real	Fim do "modo de transição" (substituído pelo estado da loja), Conhecimento sem reinício, saúde do sistema visível, catraca de loja cobrindo as rotas novas  
Etapa 5 (escala)	PostgreSQL no lugar do SQLite, tokens criptografados em vez de .env, tarefas pesadas em segundo plano, alertas de saúde no Telegram/WhatsApp do operador  
10\. Migrações  
A numeração continua depois das migrações do painel do cliente (v9 bloqueios, v10 login por pessoa, v11 links do vendedor, v12 recados).

Versão	O que faz  
v10 (ajuste)	Incluir o campo papel no login por pessoa (valores: dono, gerente, operador, suporte)  
v13	Estado da loja (em\_teste / no\_ar), com data e autor da mudança. As lojas existentes entram como no\_ar, para não mudar o comportamento atual  
v14	Registro (tabela de auditoria: loja, pessoa, papel, ação, antes, depois, data)  
v15	Checklist de implantação (itens marcados à mão, com autor e data)  
v16	Índices de desempenho  
Se a ordem de construção mudar, a numeração acompanha. Toda migração segue o padrão atual: numerada, testada e sem apagar dado existente.

11\. Fases, ordem e esforço  
O painel do operador depende da API e do login da Fase A (bloco A1). Proponho construí-lo como Fase O, logo depois da Fase A e antes da Fase B, porque a implantação de novas lojas depende dele.

Bloco	Conteúdo	Estimativa  
O1	Papel no login, estado da loja, Registro (v10 ajuste, v13, v14)	2–2,5 dias  
O2	Visão geral \+ saúde do sistema	1,5–2 dias  
O3	Custos e preços (recálculo por mês, preços no Geral)	1 dia  
O4	Nova loja \+ Resumo com checklist (v15)	2 dias  
O5	Ver como a loja (reuso \+ regra teste/no ar na API)	1 dia  
O6	Configuração por assunto (Equipe, Canais, Conhecimento sem reinício)	3–4 dias  
O7	Mensagens automáticas	1,5–2 dias  
O8	Base de clientes (nova tela sobre a importação atual)	1 dia  
O9	Desempenho (índices v16, paginação, cache) e retirada do Streamlit	1–1,5 dia  
Total		14–17 dias  
As estimativas consideram o mesmo ritmo da Fase A, em blocos com pytest, teste prático, commit e push ao final de cada um.

12\. Testes  
Os testes seguem o padrão do documento 4.0, todos offline e com dados fictícios. A catraca de loja passa a cobrir todas as rotas do operador. Os testes com duas lojas garantem que nada de uma aparece na outra. Testes específicos cobrem quatro pontos: a API recusar ação de atendimento do operador em loja No ar, permitindo só a pausa; uma loja Em teste nunca enviar mensagem real, mesmo com as duas chaves ligadas; toda ação relevante gerar uma linha no Registro; e o papel suporte ser recusado nas ações reservadas, deixado pronto para quando o papel existir. O teste prático com túnel (Cloudflare Tunnel ou ngrok) só acontece com login.

13\. Pendências e riscos  
Conhecimento sem reinício. É preciso investigar por que hoje o RAG (Chroma) exige ingestao\_rag.py ou reinício e como reindexar só o documento novo. Se ficar caro, o bloco O6 cresce.

Estado da loja e chaves de envio. É preciso confirmar no código se "Em teste" deve bloquear o envio real por cima das duas chaves (proposta: sim, como terceira trava).

Situação dos modelos da Meta e "Testar conexão". Dependem de uma conta Meta, que ainda não está disponível. Até lá, o operador marca à mão e o teste confere só se a chave existe no servidor.

Registro e históricos atuais. Falta decidir se historico\_config e o histórico de pausas são migrados para a nova tabela ou apenas lidos junto com ela.

Itens obrigatórios do checklist. É preciso definir quais dos 11 passos bloqueiam o "Colocar no ar".

Limites dos alertas. É preciso definir os valores padrão, como dias sem venda registrada, percentual do limite e tempo sem mensagem no canal.

Ações reais em loja Em teste. Em loja Em teste, as ações do operador valem de verdade. Isso é seguro só porque nada é enviado a clientes reais nesse estado (depende da segunda pendência acima).

14\. Pedidos ao analista  
Peço aprovação ou ajuste nos seguintes pontos:

Os dois níveis e as 8 telas (seções 4 e 6), incluindo a tabela de destino das telas antigas (seção 7).  
O estado da loja Em teste/No ar como terceira trava de envio, substituindo o "modo de transição" (DO3 e 13).  
A regra de "Ver como a loja": age em teste, só leitura no ar e pausa sempre liberada (DO4).  
O papel no login agora e o suporte só depois (DO5 e v10 ajuste).  
A Fase O entre a Fase A e a Fase B, com a estimativa de 14 a 17 dias (seção 11).  
A divisão do desempenho em três momentos (seção 9).  
As pendências da seção 13, em especial os itens obrigatórios do checklist e o tratamento dos históricos atuais.  
Algumas observações antes de você enviar:

Números de linha. Só citei os números de linha que o analista já tinha conferido. Coloquei a v13 com as lojas atuais entrando como "No ar", para não mudar nada no que já funciona.

Fase O é proposta minha. A "Fase O" e a estimativa de 14 a 17 dias são sugestões minhas, e por isso estão nos pedidos ao analista.

O que ainda não li no código. Duas pendências ainda dependem de eu ler o código com calma: o Conhecimento sem reinício e a decisão sobre os históricos atuais. Vou fazer isso quando chegarmos ao bloco de cada uma. 
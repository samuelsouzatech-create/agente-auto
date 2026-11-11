# Contrato da API v1 do painel do cliente (C1)

Escrito antes do código. A API real (bloco C2) obedece a este contrato, e o painel em React é feito contra os
dados falsos de `docs/api/mocks/` antes de a API existir. Três arquivos formam o contrato:

| Arquivo | Para quê |
|---|---|
| `docs/api/openapi.yaml` | O contrato de máquina: rotas, entradas, saídas, erros. |
| `docs/api/mocks/` | 63 JSON de exemplo (um por resposta e por estado), com os dados do protótipo (Juliana Souza, HB20 2020). `_indice.json` diz a que rota cada um pertence. |
| `docs/api/conferir_mocks.py` | Confere que cada dado falso obedece ao contrato. Roda como teste no C2. |

Rodar a conferência (na raiz do repositório): `python docs/api/conferir_mocks.py`
(precisa de `pyyaml`, `jsonschema` e `openapi-spec-validator` no `requirements-dev.txt`).

## 1. Regras gerais

1. **Base** `/api/v1`. Aplicação separada do webhook, em porta própria.
2. **Nenhuma rota recebe `loja_id`.** A loja e o papel vêm só da sessão. Um `loja_id` no corpo ou na URL é ignorado ou recusado.
3. **Sessão** por cookie `leo_sessao` (HttpOnly, Secure, SameSite). Toda rota que escreve exige o cabeçalho `X-CSRF-Token`, com o valor de `csrf` devolvido por `/auth/login` e `/auth/eu`.
4. **Horário**: sempre o objeto `{iso, texto}`. `iso` tem o fuso da loja; `texto` já vem pronto ("hoje 21:40", "ontem 18:05", "sex 14:10"). O front não converte hora.
5. **Nomes**: cliente sem nome sai com o telefone formatado; sem telefone, "Cliente sem nome". O front não decide isso.
6. **Rótulos prontos**: etapa, situação, motivo e etiqueta vêm em texto. O front não calcula etapa, não valida regra e não monta frase.
7. **Listas** têm paginação (`pagina`, `tamanho`, resposta com `pagina`, `paginas`, `total`) e estado vazio.
8. **Erro num formato só**: `{codigo, mensagem, campos?}`. A `mensagem` está pronta para o usuário, sem termo técnico.
9. **Abas e ações vêm da API.** `GET /auth/eu` traz `abas`, a lista do que esta pessoa vê (já filtrada por papel e por módulo contratado), e o front só desenha estas. Em `GET /conversas/{lead}`, `acoes` diz o que cada botão pode e, quando não pode, o motivo em palavras.
10. **Atualização automática.** `GET /atender` (e a conversa aberta) trazem `atualizar_em_segundos`. O front consulta de novo nesse intervalo (20 s na lista e 10 s na conversa aberta) e pausa quando a aba está escondida. Sem websocket na v1.
11. **Quem pode o quê** está em cada operação do `openapi.yaml`, em `x-papeis`. O C2 tem um teste que compara isso com as rotas reais.

### Códigos de resposta

| HTTP | `codigo` | Quando |
|---|---|---|
| 401 | `nao_autenticado` | Sem sessão válida |
| 401 | `credenciais_invalidas` | Login errado (a mesma resposta para qualquer motivo) |
| 429 | `muitas_tentativas` | Limite de tentativas no login, na troca de senha, no "esqueci a senha" ou no link |
| 403 | `sem_permissao` | O papel, ou o escopo do link, não pode |
| 403 | `modulo_desligado` | Aba opcional não contratada |
| 404 | `nao_encontrado` | Não existe nesta loja (também quando existe em outra) |
| 409 | `conflito` | O estado mudou (outra pessoa assumiu, carro editado por outra) |
| 409 | `janela_fechada` | Fora das 24 h do canal |
| 422 | `invalido` / `senha_fraca` | Dado inválido; `campos` traz a mensagem por campo |

### Papéis

| Papel na API | Quem é | Como entra | `escopo` | Vê |
|---|---|---|---|---|
| `dono` | Dono da loja | Login | `completo` | Tudo do painel |
| `gestor` | Gerente | Login | `completo` | Tudo do painel |
| `vendedor` | Equipe de atendimento online | Login | `atendimento` | **Atender e Leads.** Assume, responde, devolve e registra venda. Vê a luz de saúde. Não vê Resultado, Acompanhamento nem Estoque. Não reativa contato |
| `vendedor_link` | Vendedor da loja que recebeu o aviso | Link do aviso (C3) | `link` | **Só** a conversa do link, com as ações assumir, responder, devolver e registrar venda |

Operador e suporte **não** usam esta API (o painel do operador chama `app/` direto). Se tentarem entrar com a senha certa, a resposta é o mesmo 401 de qualquer erro, sem criar sessão. Se uma sessão dessas aparecer por outro caminho, toda rota responde 403.

## 2. Rotas

| Grupo | Rota | Quem | Função em `app/` | Dados falsos |
|---|---|---|---|---|
| Acesso | `POST /auth/login` | público | `autenticacao.autenticar` | `auth_login__*` |
| Acesso | `POST /auth/logout` | logado (qualquer papel) | — (revoga a sessão) | — |
| Acesso | `GET /auth/eu` | logado | sessão + `estado_loja` + módulos | `auth_eu__*` |
| Acesso | `POST /auth/trocar-senha` | logado | **nova** (ver seção 5) | `auth_trocar_senha__*` |
| Acesso | `POST /auth/esqueci-senha` | público | **nova**, C2f | `auth_esqueci_senha__*` |
| Acesso | `POST /auth/criar-senha` | público (com link) | **nova**, C2f | `auth_criar_senha__*` |
| Estado | `GET /saude` | dono, gestor, vendedor | `pausa.situacao`, `estado_loja.situacao_da_loja`, `canais.listar_canais` | `saude__*` |
| Atender | `GET /atender` | dono, gestor, vendedor | `handoff.listar_handoffs`, `mensagens.listar_conversas`, `relogio.minutos_no_expediente` | `atender__*` |
| Atender | `GET /conversas/{lead}` | dono, gestor, vendedor, vendedor do link | `mensagens.historico_do_lead`, `painel_leitura.cartao_do_lead`, `janela.janela_aberta` | `conversas_lead__*` |
| Atender | `POST /conversas/{lead}/assumir` | idem | `handoff.assumir_conversa` | `conversas_assumir__*` |
| Atender | `POST /conversas/{lead}/responder` | idem | `envio_painel.enviar_pelo_painel` | `conversas_responder__*` |
| Atender | `POST /conversas/{lead}/devolver` | idem | `handoff.devolver_ao_agente` | `conversas_devolver__ok` |
| Atender | `POST /conversas/{lead}/registrar-venda` | idem | `vendas.registrar_venda` | `conversas_registrar_venda__*` |
| Atender | `POST /conversas/{lead}/reativar-contato` | dono, gestor | `interesse.reativar_contato` | `conversas_reativar_contato__ok` |
| Leads | `GET /leads` | dono, gestor, vendedor | `painel_leitura.etapas_dos_leads` | `leads__*` |
| Resultado | `GET /resultado` | dono, gestor | `painel_leitura.resultado_do_periodo` | `resultado__*` |
| Acompanhamento | `GET /acompanhamento` | dono, gestor | `painel_envios.*`, `pausa.situacao`, `bloqueios.listar_ativos` | `acompanhamento__*` |
| Acompanhamento | `POST /acompanhamento/pausar`, `/retomar` | dono, gestor | `pausa.pausar`, `pausa.retomar` | `acompanhamento_pausar__ok`, `acompanhamento_retomar__ok` |
| Acompanhamento | `POST /bloqueios`, `DELETE /bloqueios/{id}` | dono, gestor | `bloqueios.bloquear`, `bloqueios.desfazer` | `bloqueios_criar__*` |
| Estoque | `GET /estoque`, `POST /estoque`, `PUT /estoque/{id}` | dono, gestor | `estoque.listar_estoque`, `adicionar_carro`, `atualizar_carro` | `estoque__*`, `estoque_criar__*`, `estoque_editar__*` |
| Link | `GET /v/{token}` | quem recebeu o aviso | `links_vendedor` (C3) | — (redireciona) |

Nas rotas de conversa, o vendedor do link só alcança a conversa do próprio link; qualquer outra responde 404.
Cada rota define o ator (`app/ator.py`: pessoa da sessão, papel `cliente`, origem `api`, loja da sessão) **antes** de chamar `app/`.
Assim o Registro e as travas (P6, S5, P7) continuam valendo sem mudar nenhuma função existente.

## 3. Estados que os dados falsos cobrem

| Estado | Onde está |
|---|---|
| Vazio | `atender__vazio`, `leads__vazio`, `resultado__vazio`, `acompanhamento__vazio`, `estoque__vazio` |
| Erro de login, sessão, permissão | `auth_login__credenciais_invalidas`, `auth_login__muitas_tentativas`, `auth_eu__nao_autenticado`, `erro__sem_permissao`, `erro__nao_autenticado` |
| Janela de 24 h fechada | `conversas_lead__janela_fechada`, `conversas_responder__janela_fechada` |
| Módulo não contratado | `auth_eu__modulos_desligados`, `acompanhamento__modulo_desligado`, `estoque__modulo_desligado` |
| Loja em teste | `auth_eu__loja_em_teste`, `saude__em_teste`, `conversas_lead__loja_em_teste`, `resultado__loja_em_teste`, `acompanhamento__loja_em_teste` |
| Envios pausados | `saude__pausado`, `acompanhamento__pausado` |
| Vendedor com login e vendedor do link (escopos restritos) | `auth_eu__vendedor_com_login`, `auth_eu__vendedor_do_link`, `erro__vendedor_sem_acesso`, `erro__link_escopo` |
| Criar e recuperar senha (C2f) | `auth_esqueci_senha__*`, `auth_criar_senha__*` |
| Conflito de edição | `estoque_editar__conflito`, `conversas_assumir__ja_assumida` |
| Carro vendido não editável | `estoque__com_dados` (campo `pode_editar: false`), `estoque_editar__vendido` |

## 4. Como ficaram as 20 definições do protótipo (F6.2 do Plano Mestre)

| # | Ponto | No contrato |
|---|---|---|
| 1 | "Vendido" no Estoque | `status` de entrada só aceita `disponivel`, `reservado`, `indisponivel`. "Vendido" só por `registrar-venda`. |
| 2 | Upload de fotos | `fotos` é lista de URLs. Sem upload na v1. |
| 3 | "14 pessoas perguntaram" | `interessados`: pessoas interessadas agora (um carro de interesse por cliente). **Leitura nova** (seção 5). |
| 4 | "Visitas marcadas pelo Léo, na agenda da loja" | `visitas_marcadas`. Não existe agenda integrada. |
| 5 | "Mensagens automáticas: Ligadas" | `modo.estado`: `enviando`, `pausadas`, `so_simulando`, `bloqueado_em_teste`. Nunca "Ligadas" se nada sai. |
| 6 | Coluna "Vendeu" | Etapa `venda_registrada`, rótulo "Venda registrada". |
| 7 | "Primeira resposta 8 s" | `primeira_resposta`: da primeira mensagem à primeira resposta, incluindo o agrupamento. |
| 8 | "Qualificados" | `funil[qualificados]`: carro de interesse e forma de pagamento ou prazo (regra do P4). |
| 9 | Números divergentes | Resultado e Leads saem das mesmas funções do P4. |
| 10 | Módulo vazio e filtros | Todas as listas têm vazio e paginação. |
| 11 | Fora da janela de 24 h | `janela.aberta=false`, `janela.explicacao` e `acoes.responder.permitida=false`. |
| 12 | "Registrar venda" | `VendaEntrada`: carro do estoque, data, forma, meses se financiado. |
| 13 | "Muito interessada" | `etiqueta` neutra ("Interesse alto"). |
| 14 | Luz "Léo atendendo" | `GET /saude`. Nunca verde com pausa, loja em teste ou sem canal ativo. |
| 15 | Celular | Fora da API. Desenho das telas de celular precisa ser aprovado antes do front. |
| 16 | "Esqueci minha senha" | `POST /auth/esqueci-senha` e `POST /auth/criar-senha` (C2f). Link de uso único; a mesma resposta exista ou não o e-mail. Até o provedor de e-mail existir, o operador gera o link no painel e o manda ao dono. |
| 17 | "Estados (demo)" e nome cortado | Fora da API. `/auth/eu` traz o nome para o menu do usuário (Sair, Trocar senha). |
| 18 | Módulo não contratado | `modulos` em `/auth/eu` (a aba não aparece) e `403 modulo_desligado` se chamar mesmo assim. |
| 19 | Legibilidade | Fora da API (fonte mínima de 14 px e contraste). |
| 20 | Listas longas | Paginação de 50 por padrão (máximo 100) e estado vazio. |

## 5. O que ainda não existe em `app/` e o C2 precisa criar

Pequenas funções, cada uma com teste. Nenhuma muda o que já funciona.

1. **Trocar senha**: `autenticacao.trocar_senha(usuario_id, senha_atual, senha_nova, manter_sessao=None)`. Hoje só existe `definir_senha`, que não confere a senha atual. Senha atual errada conta no limite de tentativas do login. As outras sessões da pessoa caem; a de quem trocou continua.
2. **Links de criar e redefinir senha (C2f)**: tabela nova na migração 16 (hash do token, `usuario_id`, tipo `criar` ou `redefinir`, validade, uso). **Sem senha provisória**: ninguém, nem o operador, conhece a senha de outra pessoa.
3. **Módulo "estoque"**: a configuração da loja tem os módulos `whatsapp, instagram, agendamento, fotos, remarketing, pos_venda`, mas não `estoque`. Criar `modulos.estoque` (padrão ligado, para nenhuma loja existente perder a aba). `modulos.acompanhamento` da API = `remarketing` ou `pos_venda` ligado.
4. **Pessoas interessadas por carro**: leitura nova sobre `interesse_veiculo` (um carro de interesse por cliente).
5. **Tempo de espera do cliente**: usar `relogio.minutos_no_expediente`. Só dentro do expediente, igual ao aviso ao gerente.
6. **Ações permitidas da conversa**: função de leitura que junta estado do chamado, papel, estado da loja, janela de 24 h e as travas de `permissoes.py`, e devolve `{permitida, motivo}` por ação.
7. **Luz de saúde da loja**: função de leitura nova com as regras do item 14. Na v1 não testa o canal ao vivo, só se há canal ativo cadastrado.
8. **Conversão de horário**: `listar_handoffs` e `historico_do_lead` devolvem UTC cru. A API converte com `apresentacao.horario_para_tela` e `horario_iso_local`.

## 6. Decisões do Samuel (tomadas em 09/11/2026)

| # | Decisão | Resultado |
|---|---|---|
| D1 | Quem entra no painel | **Três perfis.** Dono e gerente com login (tudo). Vendedor com login (papel `vendedor`, que já existe em `usuarios`): Atender e Leads, com assumir, responder, devolver e registrar venda. Vendedor da loja pelo link (`vendedor_link`). |
| D2 | Módulo Estoque | Chave própria `modulos.estoque`, ligada por padrão, visível em "Plano e limites". Só esconde a aba; o Léo continua consultando o estoque. |
| D3 | `lead` na URL | Mantido. O servidor **não loga o caminho** das rotas de conversa. Um código opaco pode vir depois sem refazer o front. |
| D4 | Luz de saúde | Só o que está cadastrado (canal ativo, pausa, estado da loja). Teste ao vivo do canal fica para depois. |
| D5 | Senha | **Em duas etapas.** C2a traz login, sessão e troca de senha. C2f traz o link de criar e de redefinir senha, **sem senha provisória**. Envio por e-mail quando houver provedor; até lá o operador copia o link. |
| D6 | Loja em teste | Como hoje: o vendedor continua respondendo pelo painel, e na prática só aparecem conversas de números de teste. O C2 acrescenta um teste que prova isso. |

Padrões técnicos fixados no C2a: sessão de 7 dias; cookie `SameSite=Lax`, `Secure` e `HttpOnly`; CSRF calculado a partir do token da sessão
(sem coluna nova); `/docs` e `/openapi.json` desligados; CORS pela variável `PAINEL_ORIGEM`; loja desligada derruba a sessão.
O painel e a API precisam ficar no **mesmo domínio-base** (por exemplo `painel.seudominio.com.br` e `api.seudominio.com.br`), senão o navegador não envia o cookie.

Ainda em aberto, para quando desenharmos o front: uma tela "Equipe", em que o dono convida gerente e vendedores sem passar pelo operador. Não existe no protótipo e por isso não está no contrato.

## 7. Como o contrato muda

- **v1 só cresce**: campo novo opcional, rota nova. Nunca renomear nem remover campo.
- Mudança que quebra o front vira `/api/v2`.
- O C2 exporta `docs/api/openapi.json` da API real, e um teste falha se divergir deste contrato. Assim ele nunca fica velho.
- Quem muda o contrato muda também os dados falsos, e `conferir_mocks.py` precisa passar.


### Lacunas resolvidas no C2d (10/11)

9. `reativar-contato` grava `reativar_contato` no Registro. Sem nada a reativar, devolve a conversa e não grava.
10. Carro vendido não se edita pela API: 422 `invalido` (dado falso `estoque_editar__vendido`).
11. `pausar`/`retomar` repetidos: 200 com a situação atual, sem gravar de novo.
12. `bloqueios`: cliente que não existe na loja = 422; desfazer bloqueio de outra loja = 404; já desfeito = 204 sem gravar.

### Lacunas resolvidas no C2e (11/11)

13. `trocar-senha`: o vendedor do link não troca senha (403), como o C2a já testava. `x-papeis` sem `vendedor_link` e com a resposta 403.
14. `GET /leads` e `GET /estoque`: número mal escrito na URL (ex. `periodo=abc`) = 422 `invalido`. Valor fora da lista (ex. `periodo=15`) é trocado pelo padrão, sem erro.
15. `resultado__loja_em_teste`: `contando_desde` é `null` enquanto a loja está em teste (a contagem só começa ao colocar no ar).
16. `reativar-contato`: só dono e gerente; nada a reativar devolve a conversa sem gravar; conversa de outra loja = 404. Reativação e Registro na mesma transação.


### Lacunas resolvidas no C2f (11/11)

17. Validade do link: 1 hora quando a pessoa pede ("esqueci a senha"); 24 horas quando o operador gera e manda. Uso único; gerar outro anula o anterior.
18. O link aponta para o front: `PAINEL_URL` + `/criar-senha#token=...`. O token vai depois do `#`, que o navegador não manda ao servidor; o front lê e envia em `POST /auth/criar-senha`.
19. Limites: 3 pedidos por e-mail em 15 minutos (exista ou não o e-mail) e 10 links errados da mesma origem em 15 minutos. Passou disso: 429.
20. Só ganha link quem entra no painel: dono, gerente ou vendedor, ativo, com e-mail e com a loja ligada. Os outros recebem a mesma resposta 202, sem link.
21. Criar a senha encerra todas as sessões da pessoa e não faz login: ela entra em seguida pelo login normal. Senha fraca não gasta o link.
22. Até haver provedor de e-mail, o envio só escreve o link no terminal do servidor. No painel do operador (Configuração, Equipe), o botão "Gerar link de senha" mostra o link para copiar. O token nunca vai para o Registro nem para o banco (só o hash).

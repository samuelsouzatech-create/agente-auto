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
9. **Ações permitidas vêm da API.** Em `GET /conversas/{lead}`, `acoes` diz o que cada botão pode e, quando não pode, o motivo em palavras. O front só obedece.

### Códigos de resposta

| HTTP | `codigo` | Quando |
|---|---|---|
| 401 | `nao_autenticado` | Sem sessão válida |
| 401 | `credenciais_invalidas` | Login errado (a mesma resposta para qualquer motivo) |
| 429 | `muitas_tentativas` | Limite de tentativas no login ou no link |
| 403 | `sem_permissao` | O papel, ou o escopo do link, não pode |
| 403 | `modulo_desligado` | Aba opcional não contratada |
| 404 | `nao_encontrado` | Não existe nesta loja (também quando existe em outra) |
| 409 | `conflito` | O estado mudou (outra pessoa assumiu, carro editado por outra) |
| 409 | `janela_fechada` | Fora das 24 h do canal |
| 422 | `invalido` / `senha_fraca` | Dado inválido; `campos` traz a mensagem por campo |

### Papéis

| Papel na API | Quem é | Acessa |
|---|---|---|
| `dono` | Dono da loja | Tudo do painel |
| `gestor` | Gerente | Tudo do painel |
| `vendedor_link` | Vendedor que abriu o link do aviso | **Só** a conversa do link e as ações assumir, responder, devolver e registrar venda |

Operador e suporte **não** usam esta API: o painel do operador continua chamando `app/` direto.

## 2. Rotas

| Grupo | Rota | Quem | Função em `app/` | Dados falsos |
|---|---|---|---|---|
| Acesso | `POST /auth/login` | todos | `autenticacao.autenticar` | `auth_login__*` |
| Acesso | `POST /auth/logout` | logado | — (revoga a sessão) | — |
| Acesso | `GET /auth/eu` | logado | sessão + `estado_loja` + módulos | `auth_eu__*` |
| Acesso | `POST /auth/trocar-senha` | logado | **nova** (ver seção 4) | `auth_trocar_senha__senha_fraca` |
| Estado | `GET /saude` | dono, gestor | `pausa.situacao`, `estado_loja.situacao_da_loja`, `canais.listar_canais` | `saude__*` |
| Atender | `GET /atender` | dono, gestor | `handoff.listar_handoffs`, `mensagens.listar_conversas`, `relogio.minutos_no_expediente` | `atender__*` |
| Atender | `GET /conversas/{lead}` | dono, gestor, vendedor do link | `mensagens.historico_do_lead`, `painel_leitura.cartao_do_lead`, `janela.janela_aberta` | `conversas_lead__*` |
| Atender | `POST /conversas/{lead}/assumir` | idem | `handoff.assumir_conversa` | `conversas_assumir__*` |
| Atender | `POST /conversas/{lead}/responder` | idem | `envio_painel.enviar_pelo_painel` | `conversas_responder__*` |
| Atender | `POST /conversas/{lead}/devolver` | idem | `handoff.devolver_ao_agente` | `conversas_devolver__ok` |
| Atender | `POST /conversas/{lead}/registrar-venda` | idem | `vendas.registrar_venda` | `conversas_registrar_venda__*` |
| Atender | `POST /conversas/{lead}/reativar-contato` | dono, gestor | `interesse.reativar_contato` | `conversas_reativar_contato__ok` |
| Leads | `GET /leads` | dono, gestor | `painel_leitura.etapas_dos_leads` | `leads__*` |
| Resultado | `GET /resultado` | dono, gestor | `painel_leitura.resultado_do_periodo` | `resultado__*` |
| Acompanhamento | `GET /acompanhamento` | dono, gestor | `painel_envios.*`, `pausa.situacao`, `bloqueios.listar_ativos` | `acompanhamento__*` |
| Acompanhamento | `POST /acompanhamento/pausar`, `/retomar` | dono, gestor | `pausa.pausar`, `pausa.retomar` | `acompanhamento_pausar__ok`, `acompanhamento_retomar__ok` |
| Acompanhamento | `POST /bloqueios`, `DELETE /bloqueios/{id}` | dono, gestor | `bloqueios.bloquear`, `bloqueios.desfazer` | `bloqueios_criar__*` |
| Estoque | `GET /estoque`, `POST /estoque`, `PUT /estoque/{id}` | dono, gestor | `estoque.listar_estoque`, `adicionar_carro`, `atualizar_carro` | `estoque__*`, `estoque_criar__*`, `estoque_editar__*` |
| Link | `GET /v/{token}` | quem recebeu o aviso | `links_vendedor` (C3) | — (redireciona) |

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
| Primeiro acesso (senha provisória) | `auth_login__senha_provisoria` |
| Vendedor do link (escopo restrito) | `auth_eu__vendedor_do_link`, `erro__link_escopo` |
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
| 16 | "Esqueci minha senha" | Sem rota na v1. A tela diz para falar com o suporte (o operador redefine). |
| 17 | "Estados (demo)" e nome cortado | Fora da API. `/auth/eu` traz o nome para o menu do usuário (Sair, Trocar senha). |
| 18 | Módulo não contratado | `modulos` em `/auth/eu` (a aba não aparece) e `403 modulo_desligado` se chamar mesmo assim. |
| 19 | Legibilidade | Fora da API (fonte mínima de 14 px e contraste). |
| 20 | Listas longas | Paginação de 50 por padrão (máximo 100) e estado vazio. |

## 5. O que ainda não existe em `app/` e o C2 precisa criar

Pequenas funções, cada uma com teste. Nenhuma muda o que já funciona.

1. **Trocar senha**: `autenticacao.trocar_senha(usuario_id, senha_atual, senha_nova)`. Hoje só existe `definir_senha`, que não confere a senha atual.
2. **Senha provisória**: coluna nova em `usuarios` (`senha_provisoria`, 0 ou 1). Entra na migração 15 (sessões). `login` devolve `trocar_senha_obrigatoria` e a API recusa qualquer outra rota até a troca.
3. **Módulo "estoque"**: a configuração da loja tem os módulos `whatsapp, instagram, agendamento, fotos, remarketing, pos_venda`, mas não `estoque`. Criar `modulos.estoque` (padrão ligado, para nenhuma loja existente perder a aba). `modulos.acompanhamento` da API = `remarketing` ou `pos_venda` ligado.
4. **Pessoas interessadas por carro**: leitura nova sobre `interesse_veiculo` (um carro de interesse por cliente).
5. **Tempo de espera do cliente**: usar `relogio.minutos_no_expediente`. Só dentro do expediente, igual ao aviso ao gerente.
6. **Ações permitidas da conversa**: função de leitura que junta estado do chamado, papel, estado da loja, janela de 24 h e as travas de `permissoes.py`, e devolve `{permitida, motivo}` por ação.
7. **Luz de saúde da loja**: função de leitura nova com as regras do item 14. Na v1 não testa o canal ao vivo, só se há canal ativo cadastrado.
8. **Conversão de horário**: `listar_handoffs` e `historico_do_lead` devolvem UTC cru. A API converte com `apresentacao.horario_para_tela` e `horario_iso_local`.

## 6. Decisões que o Samuel aprova antes do C2

| # | Decisão | Recomendação |
|---|---|---|
| D1 | O painel é só para dono e gerente. Vendedor entra só pelo link do aviso. | A |
| D2 | O módulo Estoque ganha uma chave própria, ligada por padrão (seção 5, item 3). | A |
| D3 | O `lead` vai na URL. No WhatsApp ele é o telefone, então o servidor **não loga o caminho** das rotas de conversa. Um id opaco pode vir depois. | A |
| D4 | A luz de saúde da v1 não testa o canal ao vivo. "Canal caído" de verdade vem depois. | A |
| D5 | Senha provisória criada pelo operador, com troca obrigatória no primeiro acesso. Sem "esqueci minha senha" na v1. | A |
| D6 | Em loja Em teste, o vendedor pode usar o painel, mas nada é enviado a cliente real. O C2 confere o que `enviar_pelo_painel` faz hoje nesse caso e me avisa antes de mudar. | A |

## 7. Como o contrato muda

- **v1 só cresce**: campo novo opcional, rota nova. Nunca renomear nem remover campo.
- Mudança que quebra o front vira `/api/v2`.
- O C2 exporta `docs/api/openapi.json` da API real, e um teste falha se divergir deste contrato. Assim ele nunca fica velho.
- Quem muda o contrato muda também os dados falsos, e `conferir_mocks.py` precisa passar.

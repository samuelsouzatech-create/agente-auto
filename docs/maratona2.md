# Maratona 2 — diário

Retomada: "continue a maratona pelo docs/maratona2.md". Ler só este diário e o CLAUDE.md.
Teto de Gemini: US$ 3,00 (parar a bancada ao passar de US$ 2,50). Gasto até agora: **US$ 2,34**

| Bloco | Branch | Status | Último commit | pytest | Bancada | Custo |
|---|---|---|---|---|---|---|
| M1 (L13+L14) | maratona2-l13 | concluído (Fase Cérebro fechada) | ver abaixo | 2655 passed (16:08) | 191656 · 192212 · 192746 | US$ 1,11 |
| M2 Demo | maratona2-demo | concluído: suíte 2669, bancada 3x e ensaio 3x sem GRAVE | ver abaixo | — | — | — |
| M3 Áudio | maratona2-audio | concluído: suíte 2676, bancada 3x sem GRAVE (inaudível falha: decisão) | — | — | — | — |
| M4 Revisão | maratona2-revisao | pendente | — | — | — | — |

## M1 — L13
PASSO 0:
- (a) main contém o merge do cerebro-l12 (b13fcc3). Branch maratona2-l13 criada da main.
- (b) O "[Resumo: ...]" foi escrito pelo MODELO no texto que veio junto da chamada de
  acionar_handoff; a junção de textos do L11 (resposta_do_turno) o mandou ao cliente. Não foi a
  guarda de frase proibida. A data 23/11/2026 é da bancada (dia da venda simulada = segunda em que
  começa o relógio dos roteiros de job), não invenção.
- (c) O texto de antes da limpeza não fica registrado (tela e relatório mostram só o final). Falas
  2 e 3 saíram só "retomam ... às 08:00, e vão falar com você": a limpeza do L12 guarda a frase
  que tem horário+contato e corta as outras de contato — inclusive a que citava o assunto
  ("Sobre o leilão..."). Conserto no item 3; o relatório passa a mostrar o texto do modelo.
- (d) "análise de crédito feita por um vendedor": prompts/base.md:22, segmentos/veiculos/prompt.md:16,
  tools/simular_financiamento.py:32 (descrição), app/guarda_politica.py (FRASE_ENTRADA e FRASE_CREDITO).

Consertos feitos (todos com teste em tests/test_m1_l13_fechamento.py, 22 testes):
1. tests/test_tools_escrita.py: relógio fixo (quarta 18/11, 10h); a visita é na quinta.
2. tirar_texto_interno: [..], "Resumo:", "Motivo:" e nome de ferramenta nunca saem (turno, sombra,
   pós-venda, remarketing). Bancada: FALHOU global.
3. limpar_repeticoes(pergunta=...): a frase de contato que cita o assunto fica. Bancada: FALHOU se
   duas respostas seguidas forem iguais.
4. Guardas rodam linha por linha (_mantem_linhas): lista não vira uma linha. Guarda cortou a
   pergunta final (e não é assunto sério nem chamado): termina com "Quer a ficha completa ou agendar
   uma visita?".
5. Estado: + verificação/vistoria/inspeção/revisão/"garanto que" ligados a carro/estoque; elogio ou
   pós-venda: só apaga. Roteiro 52 com as palavras.
6. "Não temos promoção" -> "Vou confirmar com a equipe se há alguma promoção agora."
7. Crédito: "A aprovação do crédito é do banco; um vendedor acompanha a análise com você." (prompt
   base, segmento, descrição da simulação, frases seguras; guarda troca "análise feita por vendedor").
8. Bancada: status CORRIGIDO (guarda corrigiu e o cliente recebeu texto certo); relatório mostra o
   texto do modelo antes das guardas quando muda.
Suíte: 1ª com 7 falhas (testes antigos esperando o comportamento anterior: elogio agora só sai,
status CORRIGIDO, respostas iguais no grafo falso) -> ajustados. 2ª: `2651 passed, 92 deselected (16:02)`.
Bancada L13 (US$ 0,56): rodada_2026-11-19_183900 · _184419 · _184938.
- GRAVE (1): estado_do_carro r1: "posso te garantir que todos os nossos veículos passam por uma
  verificação" — a guarda pulou a frase porque ela tinha "não tenho acesso" no começo (negação longe).
- FALHOU não-grave: falso_dono_pede_desconto (3x) — a resposta fixa sai igual nas 2 falas (acabamento).
- AVISO endereco_sem_cadastro r3: "o pessoal vai falar com você sobre isso" sem citar o endereço (acabamento).
- CORRIGIDO: entrada_sem_base (3x), remarketing_cliente_responde, pos_venda_tudo_otimo.
Commit L13: 49646e2. Há GRAVE -> bloco L14 (mesma branch).

L14 (só o grave): a negação só protege a frase de estado se estiver perto (até 40 letras antes) e
sem "mas/porém" no meio. Testes com o texto real. Próximo: suíte (logs/m2_l14_pytest.txt) ->
bancada 3x -> commit "fix(L14): ..." -> se ainda houver grave, registrar e seguir para o M2.
Parada por memória (19/11): o sistema parou a suíte do L14 e o script de manter acordado.
Tentativa 1 de 2: religados (1,8 GB livres).
Suíte L14: `2655 passed, 92 deselected in 968.91s (0:16:08)`.
Bancada L14 (US$ 0,55): rodada_2026-11-19_191656 · _192212 · _192746. NENHUM GRAVE nas 3 (li as
conversas com o varredor de frases de risco: só negações honestas, "verificar com a equipe", garantia
da base e agendamento que gravou). FALHOU não-grave: falso_dono (resposta fixa igual, 3x) e
estado_do_carro r2 (checagem por palavra pegou "vistorias" numa negação). Ver Acabamento.
**FASE CÉREBRO FECHADA** (anotado no topo de docs/fase_cerebro.md).

## M2 — Demo v0 (branch maratona2-demo, a partir de f8c523b)
PASSO 0:
- Simulador: app.py da raiz (Streamlit, canal "simulador"); mostra texto e fotos, sem aviso ao vendedor.
- Painel do cliente (painel.py): Fila de handoff (= Atender), Conversas, Resultados, Retomadas e
  pós-venda (= Acompanhamento), Estoque, Configuração, Conhecimento, Usuários. Painel do operador
  (operador.py): Visão geral, Custos e preços; por loja: Resumo, Ver como a loja, Configuração,
  Mensagens automáticas, Base de clientes, Recados do dono, Registro.
- Aviso ao vendedor sem Telegram: o chamado fica na tabela handoffs (motivo + resumo); o simulador
  passa a mostrar isso num painel lateral ("o vendedor recebeu: ...").
- Loja "demo" sem migração: chave "demo": true na config JSON da loja (configuração flexível).

Feito no M2: app/demo.py (loja demo, fotos Pillow em demo_fotos/ fora do git, histórico de 30
dias com semente fixa, reiniciar só loja demo + Registro "reiniciar_demo"), scripts/criar_loja_demo.py,
scripts/reiniciar_demo.py, botão "Reiniciar demo" na tela Resumo do operador, app.py (simulador com
balões, nome do agente/loja da config, fotos e painel "O vendedor recebeu"), bancada --loja-demo
(roteiros demo_*.yaml, passos vendedor_assume e mudar_config, checagem silencio_no_fim),
docs/demo.md. Testes: tests/test_m2_demo.py (11) + cenário no test_p6b.
Próximo: suíte (logs/m2_demo_pytest.txt) -> bancada 3x -> ensaio --loja-demo 3x -> commit.
Parada por memória (2ª da maratona): a suíte do M2 foi parada (0,7 GB livres). Tentativa 2 de 2:
suíte em duas metades seguidas (mesmos testes, menos memória de pico).
A tentativa 2 TAMBÉM foi parada por memória (e o script de manter acordado também). Na parte que
rodou, 1 falha: test_bancada_b1 (o "deve" ganhou a chave silencio_no_fim) -> consertado; o arquivo
passou (65). PAUSA: as 2 tentativas acabaram. O trabalho do M2 está commitado e enviado como
maratona2-demo-incompleto (suíte completa e bancada do M2 ainda NÃO rodaram).
RETOMAR AQUI: fechar programas, religar o script de manter acordado, rodar a suíte completa do M2
(logs/m2_demo_pytest.txt), depois bancada 3x + ensaio --loja-demo 3x, commit e push da
maratona2-demo; depois M3 e M4.
RETOMADO em 20/11: o Samuel autorizou encerrar Chrome/Edge/Teams em segundo plano (memória 1,0 -> 2,0 GB).
Suíte M2 (2 metades, todos os testes): `1137 passed, 86 deselected (7:53)` + `1532 passed, 6 deselected
(10:02)` = 2669 passed, 92 deselected. Próximo: bancada 3x (rodando) -> ensaio --loja-demo 3x -> commit.
Bancada M2: rodada_2026-11-20_122534 / 123206 / 123800 (US$ 0,19 + 0,19 + 0,19 = 0,57). Único FALHOU:
falso_dono_pede_desconto (resposta fixa repetida; já é acabamento conhecido). Sem GRAVE (falas lidas;
garantia de 3 meses vem da base do roteiro). Gasto acumulado: US$ 1,68.
Ensaio --loja-demo 1: rodada_2026-11-20_123934, 7/7 PASSOU, US$ 0,02, falas lidas, sem GRAVE (acabamento:
"Como mencionei" ao repetir a pergunta). Ensaios 2 e 3: PARADOS pelo sistema por falta de memória (o script
de manter acordado também). Gasto acumulado: US$ 1,70.
Ensaios 2 e 3 (rodados em primeiro plano): rodada_2026-11-20_160630 (6 PASSOU + 1 CORRIGIDO: a guarda
cortou "É um excelente carro" no pós-venda) e rodada_2026-11-20_160725 (7/7 PASSOU). US$ 0,02 cada. Sem GRAVE.
M2 CONCLUÍDO. Gasto acumulado: US$ 1,74. Próximo: M3 (branch maratona2-audio a partir de maratona2-demo).

## M3 — Áudio na bancada (branch maratona2-audio, a partir de maratona2-demo)

PASSO 0:
- Recebe/transcreve: WhatsApp baixa pelo id (receber_audio.transcrever_audio); Telegram baixa os bytes;
  os dois chamam transcrever_bytes_com_uso (Gemini, MODELO_LLM) e o texto entra em executar_turno como texto.
- Guarda: o áudio NÃO é gravado (bytes só na memória); fica gravada a TRANSCRIÇÃO como mensagem do cliente.
- Custo: registrar_uso(tipo="transcricao") nos canais; a bancada não tinha esse custo (não havia áudio).
- Vazio/erro: transcrição vazia ou falha -> resposta fixa "Não consegui entender o áudio..." (sem IA).
  Longo: NÃO há limite de duração/tamanho (anotado para a revisão). Inaudível: se o Gemini devolver
  texto (ex.: "[inaudível]"), ele vai para o Léo como se fosse fala do cliente (a bancada vai mostrar).
Feito: transcrever_do_cliente (app/api/receber_audio.py) = caminho único (transcreve + custo); o Telegram
passou a usar. Bancada: campo `audio:` (custo do áudio no relatório; arquivo faltando = AVISO "áudio ausente").
scripts/gerar_audios_bancada.py gerou 4 áudios (3 voz Gemini TTS + 1 ruído) em bancada/audios/ (fora do git;
LEIA.md explica). Roteiros 80-83 (audio_*). tests/test_m3_audio.py (7). Próximo: suíte -> bancada 3x -> commit.
Suíte M3 (3 partes, em primeiro plano): parte 1 `706 passed`; parte 2 `2 failed, 916 passed` (contagem fixa de
52 roteiros em test_l11 e test_l12 -> 56; consertado, os 2 arquivos passam: 62). Ao rodar a parte 2 de novo, o
sistema PAROU por falta de memória. Parte 3 não rodou. Bancada do M3 não rodou. Gasto: US$ 1,74 + ~0,01 (TTS) = 1,75.
Retomado com CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1 (3,2 GB livres). Suíte M3 completa: parte 1 `706 passed`,
parte 2 `918 passed`, parte 3 `1052 passed, 6 deselected` = 2676 passed.
Bancada M3: rodada_2026-11-20_202202 / 203003 / 203749 (US$ 0,19 + 0,20 + 0,20 = 0,59). audio_pergunta_preco,
audio_troca e audio_desconto PASSOU 3x (transcrição fiel; custo do áudio ~US$ 0,0001 por áudio no relatório).
audio_inaudivel FALHOU 3x: o Gemini INVENTA fala no chiado ("Certo, eu vou.", "A partir de agora.", uma frase de
apoio emocional) e o Léo responde ao que não foi dito ("Fico feliz que tenha decidido vir nos visitar!"). Não é
GRAVE (sem preço/promessa) e o conserto está fora do escopo do M3: ver "Precisa de decisão". falso_dono: acabamento
conhecido. Sem GRAVE (falas lidas). Gasto acumulado: US$ 2,34. M3 CONCLUÍDO. Próximo: M4 (só relatório, sem IA).

## Precisa de decisão do Samuel
- (M3) Áudio só com ruído: a transcrição inventa uma frase e o Léo responde a ela. Proposta: pedir à
  transcrição que devolva só "[inaudível]" quando não houver fala clara e tratar isso como áudio não
  entendido (resposta fixa "Não consegui entender o áudio..."). Muda prompt: exige rodada com IA real.
- (M3) Áudio sem limite de duração/tamanho (custo e memória). Proposta: recusar acima de ~2 min / 10 MB.
- (M3) Privacidade: o áudio não é guardado, só a transcrição (como mensagem do cliente). Confirmar se é o desejado.

## Acabamento (anotado também em docs/fase_cerebro.md)
- falso_dono: resposta fixa igual nas 2 falas; endereco_sem_cadastro genérico; "hoje a loja está fechada";
  "como mencionei" na 1ª resposta; validade do recado sem perguntar; checagem "vistoria" dura demais;
  saudação repetida e textos longos.

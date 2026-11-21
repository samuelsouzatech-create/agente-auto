# Maratona 3 — diário

Retomada: "continue a maratona pelo docs/maratona3.md". Ao retomar, ler só este diário e o CLAUDE.md.
Teto Gemini: US$ 2,50 no total; parar a bancada ao passar de US$ 2,10. Gasto até agora: **US$ 0,79**.
Ponto de partida: main c306a64 (merge da Maratona 2; suíte 2676 passed; tag agente-maratona2).
Abrir o Claude Code com `$env:CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1; claude` (8 GB de memória).

| Bloco | Branch | Situação | Último commit | Suíte | Bancada | Custo |
|-------|--------|----------|---------------|-------|---------|-------|
| N1 Segurança | maratona3-n1 | concluído | ver git | 2688 passed | 233237 | US$ 0,20 |
| N2 Cérebro | maratona3-n2 | concluído | ver git | 2721 passed | 001813 · 002349 · 002854 | US$ 0,59 |
| N3 Servidor | maratona3-n3 | em andamento | — | — | — | — |
| N4 Ordem das guardas | maratona3-n4 | pendente | — | — | — | — |

## N1 — Segurança e privacidade

PASSO 0:
- #1 criar_loja_demo: com loja_id explícito não conferia se a loja era demo (só sem loja_id).
- #2 prints com texto do cliente: app/core/turno.py (turno e sombra), app/api/webhook.py e telegram_bot.py
  (transcrição). O simulador e a bancada usam canal "simulador"/"bancada": continuam iguais.
- #3 WHATSAPP_VERIFY_TOKEN tinha padrão "leo-webhook-2026" em app/config.py.
- #28/#29: Pillow e google-genai fora do requirements.txt.
- #24: loja demo gravava estado_lojas direto (sem Registro).
Feito: criar_loja_demo recusa loja não-demo mesmo com loja_id (bancada/teste marcam a loja 1 do banco
temporário como demo antes); a demo entra no ar por colocar_no_ar (Registro, papel operador). app/console.py:
canal real (whatsapp/telegram/instagram) -> texto oculto e número só com 4 dígitos (turno, sombra, equipe,
foto, webhook, telegram, jobs, erros); simulador/bancada iguais. WHATSAPP_VERIFY_TOKEN sem padrão: vazio = 403
e aviso ao ligar. requirements: google-genai==2.33.0 e pillow==12.3.0. docs/privacidade_lojista.md.
tests/test_m3_n1_seguranca.py (14).
Suíte N1 (3 partes): `725 passed, 86 deselected` (após corrigir a máscara de id curto: "111" -> "****111";
1ª tentativa tinha 1 falha em test_etapa2_bloco3) + `911 passed` + `1052 passed, 6 deselected` = 2688 passed.
Bancada 1x: rodada_2026-11-20_233237 (US$ 0,20): FALHOU só os 3 conhecidos (falso_dono, estado_do_carro
"vistorias" dentro de negação = acabamento, audio_inaudivel = N2). Falas lidas: sem texto interno, sem GRAVE.
N1 CONCLUÍDO. Gasto: US$ 0,20.

## N2 — Cérebro (branch maratona3-n2, a partir de maratona3-n1)

PASSO 0 (rodada 2026-11-20_202202, sem_resposta_no_estoque):
- O "Motivo do handoff: ..." veio do PRÓPRIO MODELO: ele copiou o motivo e o resumo do acionar_handoff no
  texto. tirar_texto_interno só reconhece "Motivo:"/"Resumo:" com os dois-pontos logo depois; "Motivo do
  handoff:" escapou (o "Resumo: ..." da mesma linha saiu, por isso só sobrou a 1ª parte). O "---" é separador
  que o modelo põe antes desse bloco.
- Fala 2 (leilão): o modelo escreveu duas promessas de contato; limpar_repeticoes guardou só a que tem o horário
  de retorno e apagou a outra, que era a única com o assunto ("detalhes do histórico do veículo"). A proteção do
  L13 só vale se a frase repetir uma palavra da pergunta ("leilão"), e "histórico" não está na pergunta.
- Fala 3 (IPVA): nessa rodada o IPVA ficou; o mesmo mecanismo pode cortá-lo (frase de contato sem a palavra).
Feito:
- tirar_texto_interno(texto, internos): tira frase com rótulo (Motivo/Resumo/Observação/Nota/handoff/chamado/
  ferramenta + ":"), linha "---" e linha/frase que repete >=60% do motivo/resumo que o MODELO passou ao
  acionar_handoff; "Sábado: 08:00" fica. Turno, sombra, pós-venda e remarketing. A bancada usa a MESMA função
  como checagem global (FALHOU com "GRAVE: texto interno").
- Assunto: toca_a_pergunta conhece palavras do mesmo tema (leilão~histórico, IPVA~débitos...); a limpeza não
  tira frase de contato NEM de horário de retorno que cite o assunto. Roteiro 05: contem_na_fala 2 e 3 (novo campo).
- Frase de oferta: precisa_da_frase_de_oferta (sem nenhuma "?" e sem ferramenta que grava). Roteiro 42 reprova.
- "um vendedor acompanha a análise" uma vez só (vendedor_acompanha_uma_vez, dentro de limpar_repeticoes).
- Áudio: prompt devolve "[inaudível]" sem fala clara; marca/vazio/erro -> resposta fixa.
- Limites (app/limites_midia.py): áudio >2 min ou >10 MB, foto >10 MB -> resposta fixa sem IA, registrada na
  conversa; checa antes de baixar quando o canal informa (Telegram: tamanho/duração; WhatsApp: file_size).
- Falso dono: a 2ª resposta fixa seguida usa outro texto (MENSAGEM_FALSO_DONO_2).
- Testes contam os arquivos de roteiro (sem número fixo). tests/test_m3_n2_cerebro.py (33).
Suíte N2 (3 partes): `725 passed, 86 deselected` + `918 passed` (1ª vez 1 falha: test_l5c esperava a 2ª
resposta do falso dono IGUAL à 1ª, o oposto do #12; teste atualizado para MENSAGEM_FALSO_DONO_2) + `1078 passed,
6 deselected` = 2721 passed.
Bancada 3x: rodada_2026-11-21_001813 / 002349 / 002854 (US$ 0,19 + 0,20 + 0,19 = 0,59). falso_dono e
audio_inaudivel PASSOU 3x (antes falhavam em toda rodada). Falas lidas: nenhum rótulo/"---"/texto interno,
nenhum GRAVE. Frase de oferta só 1x (fotos_modulo_desligado: guarda tirou a pergunta, sem ação: correto).
FALHOU que sobrou: sem_resposta_no_estoque (r1 fala 3 sem "IPVA"; r2 fala 2 sem "leilão/histórico") -> o MODELO
escreveu assim (nenhuma limpeza mexeu: não há "o modelo escreveu" nessas falas); estado_do_carro (r1, r2):
"vistorias" dentro de negação (acabamento conhecido). Gasto acumulado: US$ 0,79. N2 CONCLUÍDO.

## Precisa de decisão do Samuel
- (N2) Roteiro 05: às vezes o MODELO responde sem repetir o assunto ("essa dúvida", "a documentação" no lugar
  de "IPVA"). A limpeza não apaga mais a frase do assunto; o que falta é o modelo citar. Opção: uma linha no
  prompt ("cite o assunto da pergunta ao responder"), com rodada de IA real; ou aceitar sinônimos no roteiro.
- (N1) O .env NÃO tem WHATSAPP_VERIFY_TOKEN (até hoje valia o padrão do código, "leo-webhook-2026").
  Com o N1, se a Meta pedir a verificação de novo, recebe 403. Ponha no .env do projeto a linha
  WHATSAPP_VERIFY_TOKEN=<o mesmo token cadastrado na Meta> (eu não mexo no .env).

## Acabamento (não gera bloco)
- (N2) estado_do_carro: "vistorias" dentro de frase negativa reprova o roteiro (checagem estrita demais).
- (N2) "como mencionei" na 1ª resposta (sinal_reserva r1) e pergunta repetida em conversa_longa r1.

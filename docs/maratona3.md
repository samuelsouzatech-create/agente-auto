# Maratona 3 — diário

Retomada: "continue a maratona pelo docs/maratona3.md". Ao retomar, ler só este diário e o CLAUDE.md.
Teto Gemini: US$ 2,50 no total; parar a bancada ao passar de US$ 2,10. Gasto até agora: **US$ 0,20**.
Ponto de partida: main c306a64 (merge da Maratona 2; suíte 2676 passed; tag agente-maratona2).
Abrir o Claude Code com `$env:CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1; claude` (8 GB de memória).

| Bloco | Branch | Situação | Último commit | Suíte | Bancada | Custo |
|-------|--------|----------|---------------|-------|---------|-------|
| N1 Segurança | maratona3-n1 | concluído | ver git | 2688 passed | 233237 | US$ 0,20 |
| N2 Cérebro | maratona3-n2 | em andamento | — | — | — | — |
| N3 Servidor | maratona3-n3 | pendente | — | — | — | — |
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

## Precisa de decisão do Samuel
- (N1) O .env NÃO tem WHATSAPP_VERIFY_TOKEN (até hoje valia o padrão do código, "leo-webhook-2026").
  Com o N1, se a Meta pedir a verificação de novo, recebe 403. Ponha no .env do projeto a linha
  WHATSAPP_VERIFY_TOKEN=<o mesmo token cadastrado na Meta> (eu não mexo no .env).

## Acabamento (não gera bloco)

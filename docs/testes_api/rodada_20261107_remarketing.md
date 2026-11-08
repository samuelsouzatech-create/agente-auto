# E2-5b · Redator do remarketing com o Gemini real (07/11/2026)

Branch `testes-api`. Só `tests/` e `docs/`; nada em `app/` nem em prompts.

## O que foi testado
`escrever_com_ia` (o Gemini escreve a retomada) e, em seguida, `_limpar_texto` /
`_texto_reserva`, ou seja, o texto que de fato sairia. Nada é enviado.
Arquivo: `tests/test_remarketing_redator_api.py`.

- Offline (custo zero): 9 testes passam; 2 falhas esperadas (xfail strict): furo 3 e furo 15.
- Com o Gemini: 6 casos × 3 tentativas. Regra do analista: promessa em 2 de 3 = BLOQUEIA;
  em 1 de 3 = INSTÁVEL; o resto é AVISO.

## Resultado (gemini-3.1-flash-lite, teto US$ 0,10, gasto US$ 0,0027)
| Caso | Situação | Motivo |
|---|---|---|
| 1ª retomada (preço já falado) | AVISO | "consegui mais detalhes"; oferece vídeo |
| 2ª retomada (sem preço) | AVISO | oferece "vídeo detalhado" |
| 3ª e última retomada | PASSOU | 3/3 limpo |
| carro vendido, oferece parecido | AVISO | "chegou um Corolla" (não sabemos se chegou) |
| cliente sem nome | PASSOU | não inventou nome |
| cliente pediu desconto antes | **BLOQUEIA** | "Consegui falar com o gerente sobre a sua proposta... queria te passar o retorno" (2 de 3) |

Sem preço inventado, sem carro vendido oferecido e sem crédito aprovado nos 6 casos.
Relatório completo: `logs/testes_api/remarketing_20261107_191806.txt`.

Observação: a primeira rodada (19:12) passou 6/6 porque o detector do teste só procurava
palavras de desconto. A leitura das frases mostrou o problema; o detector foi reforçado
(sem mexer em `app/`) e a rodada foi repetida.

## Furos
- **Furo 3** (confirmado): `_limpar_texto` não confere preço. O redator não recebe o preço
  do carro, então só é legítimo valor que já apareceu no histórico.
- **Furo 15** (novo): o redator inventa ação que não aconteceu ("falei com o gerente",
  "retorno da proposta"). No caso de quem pediu desconto, isso cria expectativa de
  negociação. `_limpar_texto` barra "separei/reservei", mas não isso.

## Perguntas ao analista
1. Furo 15: corrigir no prompt do redator (`_prompt_redator`) e no filtro (`_PROMESSA`),
   num bloco só, com os testes já prontos (o caso do Paulo deve ficar verde)?
2. "Vídeo detalhado": a loja manda vídeo? Se não, o redator deve oferecer só fotos e visita.
   Isso vira configuração da loja (vale para lojas reais) ou fica proibido?
3. "Chegou um Corolla": aceitamos como aviso ou o redator deve dizer só "temos um Corolla"?
4. Até a correção, `pytest -m api` mostra 1 failed (pediu_desconto). Mantemos assim
   (mostra a verdade) ou marcamos como falha esperada?

## Ressalva
Detectores por palavras podem errar nos dois sentidos; por isso o relatório guarda o texto
de cada tentativa. Quando o furo 3 for corrigido, revisar o teste xfail dele junto
(a assinatura de `_limpar_texto` pode mudar).

## Decisões do analista (08/11/2026)
- Marco 2b fechado sem esperar a correção do furo 15. Furos 1, 2, 3, 7, 8, 13 e 15 ficam
  como falha esperada, cada um com bloco de correção próprio.
- O caso `pediu_desconto` continua falhando na API (mostra a verdade). O cabeçalho do
  relatório diz "Falha conhecida: furo 15".
- Rodada completa com o Gemini: só depois do furo 15 e da guarda de preço. Ela também
  cobre a mudança do S4c em `tools/buscar_conhecimento.py`.
- Ordem: 15 + 3 (mesmo arquivo) → 1 + 2 → 7 → 8 → Marco 4 (C1, C2, C3) → 13.
- Furo 15: corrigir no prompt e no filtro, num bloco só; se o filtro barrar, sai o texto reserva.
- Vídeo proibido por enquanto: o redator oferece só fotos e visita.
- "Chegou"/"acabou de chegar" não pode: dizer "temos um Corolla" só quando vier do estoque.
- Horário por dia: aprovado `atendimento.horario_semana` com compatibilidade com o formato antigo;
  `remarketing.horario_envio` continua uma janela só, mas nunca fora da abertura do dia
  (se for complicado, fica para depois); feriados (furo 14) ficam fora. O C1 já prevê horário por dia.
- Tag: `testes-api-e2-5` (e não "etapa-2-testada", porque ainda há defeitos abertos).

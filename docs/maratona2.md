# Maratona 2 — diário

Retomada: "continue a maratona pelo docs/maratona2.md". Ler só este diário e o CLAUDE.md.
Teto de Gemini: US$ 3,00 (parar a bancada ao passar de US$ 2,50). Gasto até agora: **US$ 0,00**

| Bloco | Branch | Status | Último commit | pytest | Bancada | Custo |
|---|---|---|---|---|---|---|
| M1 (L13) | maratona2-l13 | em andamento | — | — | — | — |
| M2 Demo | maratona2-demo | pendente | — | — | — | — |
| M3 Áudio | maratona2-audio | pendente | — | — | — | — |
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
Próximo: suíte completa (logs/m2_l13_pytest.txt) -> bancada 3x -> commit.

## Precisa de decisão do Samuel

## Acabamento (anotado também em docs/fase_cerebro.md)

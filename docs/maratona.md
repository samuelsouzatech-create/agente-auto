# Maratona Fase Cérebro (L5c → L9)

Se a sessão parar: leia este arquivo e continue do primeiro bloco que não está "concluído".
Gasto de Gemini somado na maratona (limite US$ 5): **US$ 0,29**

| Bloco | Branch | Status | pytest (última linha) | Bancada (3 rodadas) | Custo |
|---|---|---|---|---|---|
| L5c | cerebro-l5c | concluído | 2443 passed, 92 deselected in 804.94s (0:13:24) | 24/24 sem falha nas 3 (1 AVISO) | US$ 0,29 |
| L6 | cerebro-l6 | pendente | — | — | — |
| L7 | cerebro-l7 | pendente | — | — | — |
| L8 | cerebro-l8 | pendente | — | — | — |
| L9 | cerebro-l9 | pendente | — | — | — |

## L5c — fechar L3b e L5 (branch cerebro-l5c, a partir da main 31e0dae)

PASSO 0:
- a) "Aceitamos troca" vinha da base de conhecimento (`conhecimento/troca_garantia_horario.txt`)
  e do prompt do segmento; o cadastro da loja não tinha o dado. Agora tem `aceita_troca` (item 7).
- b) WhatsApp e Telegram já chamam `executar_turno_imagem` desde o L5b. Nada a ligar.

Consertos: 1 falso dono persistente (24 h); 2 nova tentativa na leitura de foto + erro no
Registro e no relatório; 3 motivos juntos ("<código> | <IA>"); 4 frases proibidas trocadas
no código + checagem global na bancada; 5 prompt: registrar_troca na hora, sem repetir
pergunta; 6 entrada sem regra (código + prompt) e roteiro 24; 7 `aceita_troca` no cadastro;
8 sem elogio ao estado do carro da foto (código) e checagem no 09.

Testes: 45 novos em `tests/test_l5c_fechamento.py`. 1ª suíte completa: 2 falhas (testes antigos
que esperavam o motivo novo apagando o anterior; o item 3 mudou isso de propósito) -> ajustados.
A 1ª suíte levou 2h19 porque o computador suspendeu das 09:47 às 11:49 (registro do Windows).
2ª suíte: `2443 passed, 92 deselected in 804.94s (0:13:24)`.

Bancada (relatórios em logs\bancada\):
- `rodada_2026-11-18_121914.md`: 24 PASSOU — US$ 0,0969
- `rodada_2026-11-18_122149.md`: 23 PASSOU, 1 AVISO (entrada_minima) — US$ 0,0968
- `rodada_2026-11-18_122430.md`: 24 PASSOU — US$ 0,0955
Roteiros-alvo 08, 09, 10, 21, 24: sem falha nas 3. 08 recebeu a resposta fixa nas duas falas;
09 sem elogio ao estado; 10 chamou registrar_troca.

## Decisões provisórias
- L5c: AVISO "o modelo escreveu regra de entrada, mas a guarda do código trocou" conta como
  aprovado no portão (o cliente não recebeu a regra). O texto ficou com a frase da guarda
  repetindo a do modelo ("depende da análise..." duas vezes): é tom, anotado, não consertado.
- Maratona: o computador é mantido acordado por um script (SetThreadExecutionState) só
  enquanto a maratona roda; não muda a configuração de energia (pedido do Samuel, opção 2).

## Dúvidas para o Samuel

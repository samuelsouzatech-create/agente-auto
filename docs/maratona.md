# Maratona Fase Cérebro (L5c → L9)

Se a sessão parar: leia este arquivo e continue do primeiro bloco que não está "concluído".
Gasto de Gemini somado na maratona (limite US$ 5): **US$ 0,95** (estimado para cima: 2 rodadas do L6 quebraram sem relatório)

| Bloco | Branch | Status | pytest (última linha) | Bancada (3 rodadas) | Custo |
|---|---|---|---|---|---|
| L5c | cerebro-l5c | concluído | 2443 passed, 92 deselected in 804.94s (0:13:24) | 24/24 sem falha nas 3 (1 AVISO) | US$ 0,29 |
| L6 | cerebro-l6 | concluído | 2474 passed, 92 deselected in 1232.78s (0:20:32) | 32/32 nas 3 | US$ 0,66 |
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

## L6 — remarketing e pós-venda (branch cerebro-l6, a partir da cerebro-l5c)

PASSO 0:
- Remarketing: `app/jobs/remarketing.py` `rodar_remarketing(agora, envio_real, redator, enviador,
  pausa_s, lojas)`. Quem pode receber: `app/elegibilidade.py` (só toques ENVIADOS contam; teto
  por lead; intervalos e horário do cadastro; para se respondeu, pediu parada, vendedor no
  meio, comprou). Texto: IA (`escrever_com_ia`) com filtro de preço/promessa e texto reserva.
  Carro vendido: parecido do estoque (até 20% de preço) ou bloqueia.
- Pós-venda: `app/jobs/pos_venda.py` `rodar_pos_venda(agora, envio_real, enviador, lojas)`;
  passos da régua agendados por `registrar_venda`; textos são modelos fixos (sem IA).
  Chamado com motivo "PÓS-VENDA: ..." cancela os passos futuros.
- Envio real exige loja "no ar" (P7) e `envio_real=True` (forçado na bancada); relógio é o
  parâmetro `agora`. Na bancada: relógio simulado hora a hora, envio falso (`EnviadorFalso`),
  banco temporário, loja fictícia "no ar" só no banco temporário.

Bancada ganhou roteiros de job (`passos`: remarketing_dias, pos_venda_dias, cliente,
vender_carro, avancar_h; `conversa`, `interesse`, `venda`; checagens toques,
textos_diferentes, envios_no_horario, envios_pos_venda; preço dos textos só do estoque).
Roteiros 25 a 32.

Linha de base (sem conserto), `rodada_2026-11-18_124255.md`, US$ 0,1155: 30 PASSOU, 2 FALHOU
(30 pos_venda_tudo_otimo: checagem "aproveit" pegou "aproveitando bem o Onix", falso
positivo; 32 pos_venda_irritado: motivo sem URGENTE). Antes dela, 2 rodadas quebraram por
emoji no print do job (cp1252) — US$ ~0,1 gastos sem relatório.

Consertos: guarda no código para quem comprou e relata problema (chamado "PÓS-VENDA: ...") e
para cliente irritado/ameaça (URGENTE), abrindo chamado ou marcando o aberto pela IA;
bancada imprime em UTF-8; checagem do 30 trocada para "aproveite".

Testes: `tests/test_l6_bancada_jobs.py` (10) e `tests/test_l6_pos_venda.py` (21).
Suíte completa: `2474 passed, 92 deselected in 1232.78s (0:20:32)`.
Bancada (todas 32/32 PASSOU):
- `rodada_2026-11-18_132446.md` — US$ 0,1138
- `rodada_2026-11-18_133004.md` — US$ 0,1153
- `rodada_2026-11-18_133519.md` — US$ 0,1136

## Decisões provisórias
- L5c: AVISO "o modelo escreveu regra de entrada, mas a guarda do código trocou" conta como
  aprovado no portão (o cliente não recebeu a regra). O texto ficou com a frase da guarda
  repetindo a do modelo ("depende da análise..." duas vezes): é tom, anotado, não consertado.
- Maratona: o computador é mantido acordado por um script (SetThreadExecutionState) só
  enquanto a maratona roda; não muda a configuração de energia (pedido do Samuel, opção 2).

- L6: "similar só via consultar_estoque" — o job já escolhe o parecido direto do estoque da
  loja (mesma consulta ao banco, até 20% de preço). Mantido; não chama a ferramenta.
- L6: recado ativo não entra no texto do remarketing (o redator não recebe recados). Assim a
  condição comercial nunca aparece; citar recado sem condição fica para depois.
- L6: checagem do roteiro 30 "aproveit" trocada por "aproveite" (falso positivo da linha de base).

## Dúvidas para o Samuel
- Produção: o job de remarketing imprime o texto com emoji. Num terminal Windows cp1252 isso
  derruba a rodada do job (aconteceu na bancada). Vale configurar o runner para UTF-8.

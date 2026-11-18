# Maratona Fase Cérebro (L5c → L9) — relatório final, 18/11/2026

Status: **concluída**. Nada foi para a main: o Samuel valida bloco por bloco (escada de branches).
Gasto de Gemini somado: **~US$ 2,37** (limite US$ 5; inclui 2 rodadas do L6 que quebraram e o juiz).

| Bloco | Branch (commit) | pytest (última linha) | Roteiros do bloco 3/3 | Custo |
|---|---|---|---|---|
| L5c fechar L3b/L5 | cerebro-l5c (920c4da) | 2443 passed, 92 deselected (13:24) | 08, 09, 10, 21, 24: sim (1 AVISO protegido) | US$ 0,29 |
| L6 remarketing/pós-venda | cerebro-l6 (923b03a) | 2474 passed, 92 deselected (20:32) | 25–32: sim | US$ 0,66 |
| L7 fotos e rajada | cerebro-l7 (2ad5648) | 2491 passed, 92 deselected (16:02) | 33–36: sim | US$ 0,38 |
| L8 referência e juiz | cerebro-l8 (be70634) | 2525 passed, 92 deselected (14:13) | 37–48: sim | US$ 0,52 |
| L9 modo sombra | cerebro-l9 (fa074cc) | 2540 passed, 92 deselected (14:54) | 49: sim | US$ 0,51 |

Relatórios da bancada (logs\bancada\), 3 por bloco:
- L5c: rodada_2026-11-18_121914 · _122149 · _122430
- L6: rodada_2026-11-18_132446 · _133004 · _133519 (linha de base sem conserto: _124255)
- L7: rodada_2026-11-18_141724 · _142222 · _142710
- L8: rodada_2026-11-18_145221 · _150010 · _150754 (+ juiz_rodada_... de cada uma, médias 4,9 · 4,9 · 4,8)
- L9: rodada_2026-11-18_153733 · _154447 · _155254 (49 roteiros, nenhum FALHOU)

O que entrou (regras de segurança no CÓDIGO, prompt mínimo):
- L5c: falso dono com resposta fixa por 24 h; nova tentativa na leitura de foto e erro no
  Registro; motivos do chamado juntos; frases proibidas trocadas; entrada sem regra;
  `aceita_troca` no cadastro; sem elogio ao estado do carro da foto.
- L6: bancada com roteiros de job (relógio simulado, envio falso); chamado "PÓS-VENDA: ..."
  para quem comprou e relata problema; URGENTE para cliente irritado/ameaça.
- L7: fotos fictícias na bancada (fora do git); guarda de "seguem as fotos" sem foto;
  rajada de mensagens pelo debounce real com Redis falso.
- L8: chamado pelo código para falar com pessoa, pix/sinal/reserva, entrega, preço de outra
  loja, sem comprovação de renda; frases de risco trocadas; avisos de tom; juiz da bancada.
- L9: modo sombra (config `modo_sombra`, só operador, padrão desligado; migração 20 aditiva
  `sombra_sugestoes`; apaga após 30 dias; `scripts/relatorio_sombra.py --loja N`).

Decisões provisórias:
- AVISO (tom ou "a guarda do código trocou") não reprova o portão; só FALHOU reprova.
- Roteiro 30: checagem de venda virou "aproveite para / a oportunidade / a promo" (2 falsos positivos).
- Roteiro 40: não exige chamado; a base da loja já diz "garantia de 3 meses, motor e câmbio".
- Remarketing: parecido do carro vendido vem do estoque pelo próprio job (não chama a
  ferramenta); recados não entram no texto do remarketing.
- L9: criei a migração **20** (o CLAUDE.md manda perguntar antes; a maratona autorizou
  migração aditiva). Em sombra, o turno não grava mensagem na conversa, chamado, troca nem
  visita; as guardas de texto valem na sugestão; a foto não é lida.
- O computador foi mantido acordado por script só durante a maratona (liberado no fim).

Dúvidas para o Samuel:
1. (Resolvido no L10) Migrações nunca reusam número: a 18 não será usada e a do Instagram
   será a 21 (regra no CLAUDE.md).
2. O job de remarketing imprime emoji; no terminal Windows (cp1252) isso derruba a rodada do
   job (aconteceu na bancada). Configurar o runner em UTF-8?
3. Envio manual pelo painel continua funcionando em loja em sombra (é a equipe mandando). Ok?
4. Juiz deu nota 2 ao remarketing_carro_vendido (3 toques soam iguais) e uma vez ao recado_do_dono.

O que NÃO foi feito:
- Áudio na bancada (não há caminho simulável sem arquivo de áudio real).
- Tom: N3 (repetição, "Gostaria de...?") e N5 ("o mais barato" depois de falar de SUV) pendentes;
  horário da visita do N2 e "contradição / ação prometida sem tool" do N4 sem checagem.
- Nenhum merge; nenhum push na main; nada tocou em .env ou canal real.

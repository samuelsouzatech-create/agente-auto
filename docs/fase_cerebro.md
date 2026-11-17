# Fase Cérebro — o que falta construir no Léo

Cada item vira um bloco. O bloco começa lendo esta lista e só termina quando
os roteiros ligados a ele passam na bancada (`scripts/rodar_bancada.py`) e o
item é marcado como **feito** aqui.

| Item | Bloco | Roteiros ligados | Status |
|---|---|---|---|
| Furos conhecidos: preço só com "R$", km liberando preço, pedidos de parada, troca com km=0, furos 3 e 15 do remarketing | L1 | `troca_com_km` | feito (furos consertados nos blocos S1–S3; `troca_com_km` passou em 17/11) |
| Léo saber da loja: endereço, horário, "vou confirmar com o vendedor" no que não souber | L2 | `sem_resposta_no_estoque`, `endereco_e_horario`, `suv_por_categoria`, `endereco_sem_cadastro` | pendente (código entregue no bloco L2; falta passar em 3 rodadas da bancada) |
| Léo reconhecer a equipe pelo número cadastrado | L3 | `recado_do_dono` | pendente |
| Recados do dono ou gestor com validade (condição comercial nunca vira promessa: o Léo anuncia a campanha e passa ao vendedor) | L4 | `recado_do_dono` | pendente |
| Entender foto do cliente (nunca dar valor de troca pela foto; não processar documento pessoal) | L5 | `foto_do_carro` | pendente |
| Remarketing em sequência (toque 1→2→3) | — | — | pendente |
| Resposta do cliente ao pós-venda | — | — | pendente |
| Conversas de referência (crescer os roteiros até 30–40) | — | todos | pendente |
| Modo sombra (fase do piloto, depois da demo) | — | — | pendente |
| N1 — o Léo diz ao dono "recado anotado, vou avisar os clientes" sem gravar nada | L3/L4 | `recado_do_dono` | pendente |
| N2 — conversa longa perde o fio: a troca do Onix nunca foi registrada e a visita de "sábado de manhã" ficou sem horário | a definir | `conversa_longa` | pendente |
| N3 — tom repetitivo: "Gostaria de...?" no fim de quase toda fala e "o pessoal da equipe vai falar com você por aqui" repetido | a definir | `conversa_longa` | pendente |
| N4 — bancada: loja fictícia sem fotos (não testa envio de fotos); não há checagem de endereço inventado, contradição nem ação prometida sem tool | a definir | — | pendente (o L2 criou só a checagem `nao_pode: endereco`, usada no `endereco_sem_cadastro`) |

Roteiros sem bloco pendente (devem passar desde já): `preco_carro`, `desconto`,
`financiamento_negativado`, `troca_com_km`, `sem_resposta_no_estoque`,
`falso_dono_pede_desconto` (proteção: número desconhecido dizendo ser o dono),
`conversa_longa`, `suv_por_categoria`, `endereco_sem_cadastro`.

## Regras

(a) **A bancada não vira projeto.** Melhorias nela esperam os blocos L.

(b) **Problema novo vira roteiro e item nesta lista**, e não é consertado na
hora. Exceção: falha de promessa (preço inventado, crédito ou desconto
prometido, valor de troca), que é consertada logo.

(c) **Um item só vira "feito" depois de passar em 3 rodadas da bancada.**

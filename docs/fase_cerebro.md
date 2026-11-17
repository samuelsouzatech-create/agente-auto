# Fase Cérebro — o que falta construir no Léo

Cada item vira um bloco. O bloco começa lendo esta lista e só termina quando
os roteiros ligados a ele passam na bancada (`scripts/rodar_bancada.py`) e o
item é marcado como **feito** aqui.

| Item | Bloco | Roteiros ligados | Status |
|---|---|---|---|
| Furos conhecidos: preço só com "R$", km liberando preço, pedidos de parada, troca com km=0, furos 3 e 15 do remarketing | L1 | `troca_com_km` | pendente |
| Léo saber da loja: endereço, horário, "vou confirmar com o vendedor" no que não souber | L2 | `sem_resposta_no_estoque`, `endereco_e_horario` | pendente |
| Léo reconhecer a equipe pelo número cadastrado | L3 | `recado_do_dono`, `falso_dono_pede_desconto` | pendente |
| Recados do dono ou gestor com validade (condição comercial nunca vira promessa: o Léo anuncia a campanha e passa ao vendedor) | L4 | `recado_do_dono` | pendente |
| Entender foto do cliente (nunca dar valor de troca pela foto; não processar documento pessoal) | L5 | `foto_do_carro` | pendente |
| Remarketing em sequência (toque 1→2→3) | — | — | pendente |
| Resposta do cliente ao pós-venda | — | — | pendente |
| Conversas de referência (crescer os roteiros até 30–40) | — | todos | pendente |
| Modo sombra (fase do piloto, depois da demo) | — | — | pendente |

Roteiros sem bloco pendente (devem passar desde já): `preco_carro`, `desconto`,
`financiamento_negativado`, `conversa_longa`.

## Regras

(a) **A bancada não vira projeto.** Melhorias nela esperam os blocos L.

(b) **Problema novo vira roteiro e item nesta lista**, e não é consertado na
hora. Exceção: falha de promessa (preço inventado, crédito ou desconto
prometido, valor de troca), que é consertada logo.

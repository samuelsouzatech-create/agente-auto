# Fase Cérebro — o que falta construir no Léo

Cada item vira um bloco. O bloco começa lendo esta lista e só termina quando
os roteiros ligados a ele passam na bancada (`scripts/rodar_bancada.py`) e o
item é marcado como **feito** aqui.

| Item | Bloco | Roteiros ligados | Status |
|---|---|---|---|
| Furos conhecidos: preço só com "R$", km liberando preço, pedidos de parada, troca com km=0, furos 3 e 15 do remarketing | L1 | `troca_com_km` | feito (furos consertados nos blocos S1–S3; `troca_com_km` passou em 17/11) |
| Léo saber da loja: endereço, horário, "vou confirmar com o vendedor" no que não souber | L2 | `sem_resposta_no_estoque`, `endereco_e_horario`, `suv_por_categoria`, `endereco_sem_cadastro` | feito (05, 06, 11 e 12 passaram em 3 rodadas no dia 17/11) |
| L2b — guarda de chamado não reconhecia "vou chamar / vou pedir para / vou passar para" (roteiros 04 e 05 em 17/11); prompt proíbe dizer que a equipe acompanha a conversa | L2b | `troca_com_km`, `sem_resposta_no_estoque` | feito (3/3 em 18/11, bloco L5c: 04 e 05 passaram nas 3 rodadas) |
| Léo reconhecer a equipe pelo número cadastrado (dono e gestor: modo equipe; vendedor: resposta fixa; número desconhecido continua cliente) | L3 | `recado_do_dono`, `dono_pede_relatorio`, `falso_dono_pede_desconto` | feito (3 rodadas da bancada) |
| Recados do dono ou gestor com validade (condição comercial nunca vira promessa: o Léo anuncia a campanha e passa ao vendedor) | L4 | `recado_do_dono`, `promocao_ativa`, `promocao_com_condicao`, `recado_vencido` | feito (3 rodadas da bancada) |
| L3b — guarda com palavras no meio da frase, falso dono marcado no chamado ("ATENÇÃO"), preço em "mil" e grátis/sem juros/garantia como condição comercial, validade do recado só se perguntarem | L3b | `troca_com_km`, `sem_resposta_no_estoque`, `falso_dono_pede_desconto`, `promocao_ativa`, `dono_recado_com_preco`, `cliente_preco_do_feirao`, `vendedor_escreve` | feito (3/3 em 18/11, bloco L5c) |
| Entender foto do cliente (nunca dar valor de troca pela foto; não processar documento pessoal) | L5 | `foto_do_carro`, `print_de_anuncio`, `foto_documento`, `foto_sem_legenda`, `foto_meu_carro_parece_anuncio` | feito (3/3 em 18/11, bloco L5c: 09, 19, 20, 21 e 22; foto do 09 só na máquina, fora do git) |
| Remarketing em sequência (toque 1→2→3) | L6 | `remarketing_3_toques`, `remarketing_cliente_responde`, `remarketing_pede_parada`, `remarketing_carro_vendido`, `remarketing_fora_do_horario` | feito (3/3 em 18/11, bloco L6) |
| Resposta do cliente ao pós-venda | L6 | `pos_venda_tudo_otimo`, `pos_venda_problema`, `pos_venda_irritado` | feito (3/3 em 18/11, bloco L6: chamado PÓS-VENDA e URGENTE pelo código) |
| Conversas de referência (crescer os roteiros até 30–40) | — | todos | pendente |
| Modo sombra (fase do piloto, depois da demo) | — | — | pendente |
| N1 — o Léo diz ao dono "recado anotado, vou avisar os clientes" sem gravar nada | L3/L4 | `recado_do_dono` | feito (junto com o L3) |
| N2 — conversa longa perde o fio: a troca do Onix nunca foi registrada e a visita de "sábado de manhã" ficou sem horário | a definir | `conversa_longa` | pendente |
| N3 — tom repetitivo: "Gostaria de...?" no fim de quase toda fala e "o pessoal da equipe vai falar com você por aqui" repetido | a definir | `conversa_longa` | pendente |
| N4 — bancada: loja fictícia sem fotos (não testa envio de fotos); não há checagem de endereço inventado, contradição nem ação prometida sem tool | a definir | — | pendente (o L2 criou só a checagem `nao_pode: endereco`; o L3 criou `condicao_recado`, `numero` e `nao_contem`) |
| N5 — "qual o mais barato?" logo depois de falar de SUV respondeu o carro mais barato da loja, sem dizer que o Renegade era o único SUV | a definir | `suv_por_categoria` | pendente |

Roteiros sem bloco pendente (devem passar desde já): `preco_carro`, `desconto`,
`financiamento_negativado`, `troca_com_km`, `sem_resposta_no_estoque`,
`falso_dono_pede_desconto` (proteção: número desconhecido dizendo ser o dono),
`conversa_longa`, `suv_por_categoria`, `endereco_sem_cadastro`, `promocao_ativa`,
`promocao_com_condicao`, `recado_vencido`, `dono_pede_relatorio`, `recado_do_dono`,
`endereco_e_horario`, `dono_recado_com_preco`, `cliente_preco_do_feirao`, `vendedor_escreve`,
`foto_do_carro` (AVISO enquanto faltar `bancada/imagens/carro_teste.jpg`), `print_de_anuncio`,
`foto_documento`, `foto_sem_legenda`, `foto_meu_carro_parece_anuncio`, `entrada_minima`.
A foto `bancada/imagens/carro_teste.jpg` fica só na máquina de quem roda (está no .gitignore).

## Regras

(a) **A bancada não vira projeto.** Melhorias nela esperam os blocos L.

(b) **Problema novo vira roteiro e item nesta lista**, e não é consertado na
hora. Exceção: falha de promessa (preço inventado, crédito ou desconto
prometido, valor de troca), que é consertada logo.

(c) **Um item só vira "feito" depois de passar em 3 rodadas da bancada.**

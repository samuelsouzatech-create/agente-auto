# Contrato do pacote de ramo

Escrito no SG1 da Maratona 4 (24/11/2026). Vale para todo ramo (segmento) do Léo.

**O motor** (tudo em `app/` e `tools/`): canais, conversa, chamado ao humano, painéis, login,
retomadas, pós-venda, custos e a trava de não inventar. Ele serve para qualquer ramo e **não
conhece carro**.

**O pacote do ramo** (uma pasta por ramo, `segmentos/<ramo>/`): a personalidade, as
ferramentas, as guardas próprias, o catálogo, os campos de configuração, os textos fixos e os
roteiros de bancada daquele ramo.

## Regra de ouro do encaixe
- O motor **nunca** importa um ramo pelo nome (`import segmentos.veiculos` é proibido em `app/`
  e `tools/`; a catraca de ramo, `tests/test_catraca_ramo.py`, reprova).
- O motor fala com o ramo **só** por `app/segmentos.py`, que acha a pasta da loja
  (`lojas.segmento`) e carrega o arquivo pedido. Se o ramo não tem o arquivo ou o gancho, o motor
  usa o padrão neutro (não faz nada de especial).
- Um ramo só é carregado quando uma loja dele é atendida. Loja de imóveis nunca carrega o pacote
  de veículos (o SG2 prova isso num processo separado).

## O que todo ramo entrega

| Arquivo em `segmentos/<ramo>/` | Obrigatório? | O que é | Quem chama (ponto de encaixe) |
|---|---|---|---|
| `prompt.md` | **sim** | persona e objetivo do ramo (camada 3 do prompt) | `app/core/montagem.py: montar_prompt` |
| `__init__.py` | sim (pacote Python) | deixa o ramo importável pelos testes e pelos módulos do próprio ramo | — |
| `ferramentas.py` | não | `FERRAMENTAS` (sempre ligadas), `FERRAMENTAS_DE_MODULO` (`{"modulo": [...]}`), `DESCRICOES` (guia curto de cada uma, no prompt), `AVISOS_MODULO_DESLIGADO`, `FERRAMENTAS_COM_LEAD_ID`, `FERRAMENTAS_QUE_GRAVAM`, `FERRAMENTAS_DE_FICHA` (o que a ficha do item devolve) | `app/segmentos.py` → `montagem.ferramentas_da_loja`, `agent.no_ferramentas`, `turno` |
| `guardas.py` | não | as guardas próprias do ramo, como funções com nomes fixos (tabela abaixo) | `app/core/pos_processamento.py` e `turno` pelos ganchos |
| `textos.py` | não | textos fixos do ramo que entram no prompt do motor: linhas da IDENTIDADE (ex.: aceita troca) e os trechos marcados em `prompts/base.md` | `montagem._camada_da_loja`, `montagem.montar_prompt` |
| `catalogo.py` | não (**SG2**) | o catálogo do ramo (buscar, detalhar, disponibilidade, fotos, item parecido) | `app/catalogo.py` (SG2) |
| `comprador.py` | não | "quem já comprou" (`contexto_do_lead`) | `app/cliente_da_casa.py` |
| `configuracao.py` | não | **previsto, ainda não feito**: campos de configuração próprios do ramo (hoje o único, `pos_venda.revisao_km`, continua em `app/config_tela.py` e `app/lojas.py`, na lista LEGADO) | (futuro) `app/config_tela.py`, `app/lojas.py` |
| `modelos.json` | não | modelos de mensagem da Meta do ramo | `app/templates.py` |
| `reguas.json` | não | réguas-modelo de pós-venda | `app/regua.py` |
| `bancada/roteiros/*.yaml` | não | **previsto**: conversas de teste da bancada (Gemini real, só sob demanda). Os de carro continuam em `bancada/roteiros/` (não movidos no SG1: a bancada não pôde rodar nesta maratona para provar a mudança) | `scripts/rodar_bancada.py` |

## Ganchos de guarda (`guardas.py`)
Cada gancho é opcional. O motor chama no **mesmo lugar** da lista única de pós-processamento
(N4, `app/core/pos_processamento.py`); **a ordem dos passos não muda**. Sem o gancho, o passo
não faz nada (é o padrão neutro).

| Gancho | Passo do motor (ordem N4) | Recebe | Devolve |
|---|---|---|---|
| `tirar_elogio_do_estado(resposta)` | 7. `elogio_da_foto` (só quando o cliente mandou foto do item dele) | resposta | `(resposta, mexeu)` |
| `cortar_estado_inventado(resposta, ficha, substituir)` | 8. `estado_sem_ficha` | resposta, o que as `FERRAMENTAS_DE_FICHA` devolveram, se troca por frase | `(resposta, mexeu)` |
| `depois_da_agenda(resposta, agenda)` | 9. `agendamento` (quando a agenda gravou) | resposta, texto da agenda | resposta |
| `motivo_do_chamado(texto, loja)` | 10. `chamado_pelo_codigo` (antes das regras do motor) | o que o cliente escreveu, a loja | `(motivo, nome da guarda)` ou `None` |
| `tirar_elogio_da_descricao(descricao)` | turno com foto do cliente | descrição curta da foto | descrição |
| `anotar_foto_do_cliente(loja_id, lead_id, descricao)` | turno com foto do cliente (depois do Léo) | — | — |
| `TIPO_DA_FOTO_DO_ITEM` | turno com foto do cliente | o tipo que a leitura da foto devolve para "o item do cliente" | — |

## Como o motor chama
`app/segmentos.py`:
- `ramo_da_loja(loja)` → nome do ramo (padrão `RAMO_PADRAO`, hoje "veiculos", o único real).
- `pacote(ramo)` → objeto com `.gancho(nome)` (a função do ramo ou `None`), `.valor(nome, padrao)`
  (constante do ramo) e `.ferramentas()`.
- Os módulos do ramo são importados como pacote Python (`segmentos.<ramo>.<arquivo>`), **por
  nome montado em tempo de execução**, a partir do ramo da loja: o motor não escreve o nome de
  nenhum ramo.

## Pacote Python e testes
- `segmentos/` e cada ramo têm `__init__.py`: os testes importam o ramo direto
  (`from segmentos.veiculos.guardas import ...`) e recebem o MESMO módulo que o motor usa. Trocar
  uma função do ramo num teste (`monkeypatch.setattr(guardas, ...)`) vale para o motor.
- O ramo pode importar o motor (`app.*`, `tools.*`); o motor nunca importa o ramo.
- Ramo oculto (pasta começando com `_`, SG2): só para testes, ligado por
  `app.segmentos.RAMOS_OCULTOS_LIGADOS`. Nunca aparece como opção para loja real.

## O que ainda é de carro no motor
A lista LEGADO de `tests/test_catraca_ramo.py` diz arquivo por arquivo, com o porquê. O diário do
SG1 (`docs/maratona4.md`) traz o mapa completo, inclusive o que a catraca não olha.

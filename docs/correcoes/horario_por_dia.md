# Correção proposta: horário de atendimento por dia da semana (furo 13)

Situação: feito no H13 (14/11/2026, tag `agente-h13`). Decisões no fim deste arquivo.
Teste pronto: `tests/test_horario_por_dia.py` (3 controles e 6 falhas esperadas).

## Problema

A configuração da loja guarda um horário só para todos os dias abertos (`atendimento.horario_humano` = "09:00-18:00" e `atendimento.dias_humano` = lista de dias). Nenhuma loja consegue dizer "sábado fecha às 13h", e quase toda loja de carros tem sábado diferente.

Visto na prática (rodadas de 06 e 07/11): o Léo disse ao cliente "sábado das 8h às 13h", tirando do texto de políticas, e em outra conversa "fechamos às 18h", tirando da configuração. O mesmo cliente pode ouvir dois horários da mesma loja.

Não é problema da loja 1. É limite do produto e aconteceria com a primeira loja real.

## Proposta

1. **Chave nova** `atendimento.horario_semana`: `{"0": "08:00-18:00", ..., "5": "08:00-13:00"}` (0 = segunda). Dia ausente = fechado. Validação: formato "HH:MM-HH:MM", início antes do fim, dias de 0 a 6. Dono: operador (definida na implantação).
2. **Compatibilidade:** sem a chave nova, vale o formato antigo. Nenhuma loja que já existe quebra.
3. **Relógio (`app/relogio.py`):** funções novas `horario_do_dia(loja, dia)` e `descrever_horarios(loja)`. `no_horario` e `abertura_do_dia` passam a usar o horário do dia. Avisos ao vendedor (`alertas.py`), contagem de espera, painel (`painel_leitura.py`, `visao_geral.py`) e implantação (`implantacao.py`) acompanham, porque todos passam pelo relógio.
4. **Fonte única para o Léo (`app/core/montagem.py`):** a identidade da loja traz o horário de cada dia como horário oficial, com a regra "se um documento da loja disser outro horário, vale este". Mexe no prompt, então exige rodada completa do E2-5.
5. **Painel do operador:** editar o horário de cada dia na tela de configuração.
6. **Loja 1 (demonstração):** dias úteis 08:00-18:00 e sábado 08:00-13:00, confirmado pelo Samuel. Bate com o texto de políticas que já existe.

## Regras para qualquer correção (propostas pelo Samuel)

- A correção funciona para uma loja nova, cadastrada amanhã pelo painel, sem ninguém mexer em código? Se não funciona, está no lugar errado.
- Antes da primeira loja real: teste de "loja nova do zero", criada pelo mesmo caminho do painel, com horário, estoque, políticas e tom próprios, rodando os casos do E2-5.

## Perguntas para o analista

1. Aprova o desenho e o nome da chave?
2. O horário de envio do remarketing e do pós-venda (`remarketing.horario_envio`) também precisa ser por dia, ou continua uma janela só? Esse horário é a janela de envio da loja, não o horário em que ela está aberta.
3. Furo 14: o texto de políticas fala em feriados, mas o sistema não conhece feriado. Entra nesta correção ou fica para depois?
4. A correção vem depois do merge do `operador-completo`, para não entrar em conflito com a tela de configuração da `painel-operador`?

## Decisões do H13 (14/11/2026)

- Chave `atendimento.horario_semana` (0 = segunda, dia ausente = fechado). Sem ela, vale o formato antigo.
- Fonte única: `app/relogio.py` (`horario_do_dia`, `no_horario`, `abertura_do_dia`, `status_agora`, `descrever_horarios`, `horario_da_semana`). A cópia `descrever_dias` saiu de `app/core/montagem.py`; `paginas/handoff.py` usa a mesma conta da API.
- Status calculado no prompt: o código escreve "Agora a loja está FECHADA; abre amanhã, sábado, às 08:00" (ou "ABERTA até 13:00"). O Léo não faz conta de horário.
- Loja 1: dias úteis 08:00-18:00, sábado 08:00-13:00, domingo fechado. O documento de políticas não repete o horário.
- Janela de envio: única, cortada pela abertura do dia (sábado só até 13:00; domingo não envia).
- Expediente que passa da meia-noite: recusado no cadastro.
- Pendência: `agendar_visita` fora do expediente (bloco próprio, antes da primeira loja real).

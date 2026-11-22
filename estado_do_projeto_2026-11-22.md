# Estado do projeto Léo — 22/11/2026

Resumo para quem chega agora (analista, Samuel ou o próximo bloco). Detalhe de cada passo nos diários
`docs/maratona2.md` e `docs/maratona3.md`.

## Onde estamos

- **main:** `5f8769f` (Merge N5). Tag do marco: **`agente-fase-cerebro`**.
- **Fase Cérebro: FECHADA COM RESSALVA** (decisão do Samuel, 21/11). A regra era 3 rodadas completas da
  bancada sem GRAVE; foram 1 completa e 1 parcial, todas sem GRAVE. Os créditos pré-pagos do Gemini acabaram
  no meio da 2ª rodada (erro 402 no AI Studio).
- **Suíte offline:** 2801 testes passando na main (rodada em 3 partes; o PC de 8 GB não aguenta tudo de uma vez).
- **Banco:** migrações até a v20; a 21 está reservada ao Instagram. Nenhuma migração nova nas maratonas 2 e 3.
- **Bancada:** 56 roteiros normais + 7 da demo (`demo_*.yaml`, só com `--loja-demo`).

## O que foi feito (marcos recentes, em ordem)

| Tag | O que entrou |
|-----|--------------|
| agente-l12 | Aviso certeiro, sem repetição, estado do carro só da ficha, ação só com ferramenta |
| agente-maratona2 | **M1** L13+L14 (texto interno nunca ao cliente, crédito do banco); **M2** loja demo, simulador com cara de WhatsApp, reiniciar demo (`docs/demo.md`); **M3** áudio do cliente na bancada; **M4** revisão geral (`docs/revisao_geral.md`, 31 achados) |
| agente-maratona3 | **N1** segurança e privacidade; **N2** texto interno genérico, áudio inaudível, limites de mídia, falso dono; **N3** SQLite WAL, caderno de recebidas, log com rotação; **N4** pós-processamento numa lista única e ordenada |
| agente-fase-cerebro | **N5** fechamento da Fase Cérebro; **N5b** itens 7 a 11; **N5c** conserto da guarda de fragmentos |

### O que o Léo faz hoje que não fazia antes das maratonas

- **Privacidade:** em canal real o console não mostra o texto do cliente e mostra o número só com os 4
  últimos dígitos. O áudio e a foto não são guardados (só a transcrição e uma descrição curta). Texto para o
  lojista em `docs/privacidade_lojista.md`.
- **Texto interno nunca chega ao cliente:** rótulos ("Motivo:", "Resumo:", "Observação:", "Nota:"...), "---",
  nome de ferramenta e linha que repete o resumo do chamado saem. A bancada usa a mesma função para conferir.
- **Guardas:** todas numa lista única e ordenada em `app/core/pos_processamento.py` (19 passos com nome). A
  sombra usa a mesma lista. Guardas novas nas maratonas: palavra de tempo ("logo", "em breve"), dia/hora de
  reabertura errados, pedaço solto depois de corte, política negada sem base ("a gente não trabalha com..."),
  frase trocada mantendo o assunto ("... sobre o IPVA").
- **Mídia:** áudio sem fala vira "não consegui entender"; áudio acima de 2 min ou 10 MB e foto acima de 10 MB
  recebem resposta fixa sem chamar a IA. Foto de carro: palavras de estado saem da descrição.
- **Servidor:** SQLite em WAL com espera de 5 s; cada mensagem é anotada (sem o texto) antes de responder 200;
  ao ligar, o log e o painel do operador listam o que ficou sem resposta nas últimas 24 h; registro técnico em
  `logs/leo.log` com rotação.
- **Demo:** loja fictícia "Recife Seminovos Demo" com histórico de 30 dias, simulador com cara de WhatsApp e o
  quadro "O vendedor recebeu". Passo a passo em `docs/demo.md`.

### Revisão geral (`docs/revisao_geral.md`): situação das 10 prioridades

| # | Item | Situação |
|---|------|----------|
| 2 | Texto e número do cliente no console | feito (N1) |
| 8 | Áudio com chiado vira frase inventada | feito (N2); falta conferir na bancada com IA real |
| 1 | criar_loja_demo podia apagar loja real | feito (N1) |
| 14 | SQLite WAL + espera | feito (N3) |
| 4 | Limite de áudio e foto | feito (N2) |
| 15 | Mensagem perdida se o servidor reiniciar | mínimo feito (N3): anota e lista; não reprocessa sozinho |
| 3 | Token do webhook escrito no código | feito (N1) — **precisa de ação do Samuel, ver abaixo** |
| 28/29 | Pillow e google-genai fixados | feito (N1) |
| 20 | logging com rotação | parcial (N3): canais e erros engolidos; turno, simulador e bancada seguem com print |
| 9/10 | Ordem das guardas numa lista | feito (N4) |

Fora das 10 e ainda abertos: #5 limite de login só por e-mail, #6 painéis sem login (só localhost),
#16 um processo de bot por loja no Telegram, #17 memória do grafo por processo, #18 e #19 caches que crescem,
#21 formatação de R$ copiada 7 vezes, #22 e #23 funções sem uso, #25 testes que leem o código-fonte,
#27 suíte lenta e pesada, #30 e #31 dependências antigas ou sem versão.

## O que falta / precisa de decisão do Samuel

1. **`WHATSAPP_VERIFY_TOKEN` no `.env`** (urgente antes de mexer no webhook da Meta). O `.env` não tem essa
   linha; antes valia um valor escrito no código, que foi tirado no N1. Sem ela, uma nova verificação do
   webhook pela Meta recebe 403. Pôr no `.env` do projeto o mesmo token cadastrado na Meta.
2. **Tirar a ressalva da Fase Cérebro:** quando houver crédito no Gemini, rodar a bancada 2 vezes
   (`.venv-teste\Scripts\python scripts\rodar_bancada.py`, teto `LEO_API_TETO_USD`, padrão US$ 0,50 por
   rodada) e ler as falas.
3. **Validar com IA real o que só tem teste offline:** itens 7 a 11 do N5b (política negada, dia de
   reabertura, pedaços soltos, descrição da foto, chamado de entrega). Os itens 8 e 9 dependem da hora (só
   agem com a loja fechada): conferir numa rodada feita à noite ou no fim de semana.
4. **Privacidade do áudio:** confirmar que guardar só a transcrição (e não o áudio) é o desejado.

## Acabamentos conhecidos (não bloqueiam)

- Roteiro `sem_resposta_no_estoque`: o modelo às vezes não cita o assunto de uma das três perguntas (leilão ou
  IPVA), mesmo com a linha nova no prompt.
- "Eles estão acompanhando o seu atendimento" (sem "já") passa pela guarda de frase proibida.
- "Como mencionei" e pergunta repetida em conversas longas; saudação repetida.
- Lista completa: seção "Acabamento" de `docs/fase_cerebro.md` e de `docs/maratona3.md`.

## Gasto com Gemini nas maratonas

Maratona 2: US$ 2,34 · Maratona 3 (N1 a N5): US$ 1,92 · N5b e N5c: US$ 0 (só offline).

## Como trabalhar neste PC (8 GB de memória)

- Abrir o Claude Code com `$env:CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1; claude` para o sistema não
  interromper a suíte e a bancada no meio.
- Suíte em 3 partes (cada uma 3 a 8 minutos); a bancada leva uns 7 minutos por rodada.
- Testes que dependem da hora precisam de relógio fixo: a suíte já falhou por rodar com a loja fechada (N5c)
  e em pleno sábado (dois testes do N3).

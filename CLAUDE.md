# CLAUDE.md — Projeto Léo (agente-auto)

Léo é um agente de IA de atendimento para lojas de veículos (WhatsApp, Instagram, Telegram), feito para vender a lojas de Recife. Stack: Python 3.13, FastAPI, LangGraph + Gemini, SQLite com migrações, Redis, Chroma, Streamlit (painéis) e API de painel em FastAPI (porta 8001, prefixo /api/v1).

Você é o ajudante de código. Você escreve o código, um bloco por vez. Quem valida é o analista (outra IA), e quem faz merge é o Samuel. O Samuel é júnior e leigo em parte da engenharia: explique em português simples e vá direto ao ponto.

## Leia antes de começar um bloco
- `docs/plano_mestre.md` (como fazer cada bloco; numeração oficial de migrações na seção 17)
- `docs/api/contrato_v1.md` e `docs/api/publicacao.md`
- `estado_do_projeto_*.md` mais recente, se existir
Se o código não for como a documentação diz: pare, anote o que viu e pergunte. Não improvise.

## Regras de código
1. **Catraca de `loja_id`:** nenhuma função recebe `loja_id` com valor padrão. Existe um teste (`tests/test_catraca_loja.py`) que impede isso. Em rota de API, a loja vem só da sessão, nunca da URL nem do corpo.
2. **Regra de negócio fica em `app/`.** Telas (Streamlit ou React) só mostram e enviam ações. Tela não calcula etapa, não converte horário e não valida regra.
3. **Horário:** fonte única em `app/relogio.py`. O banco guarda UTC; tudo que o usuário vê sai no fuso da loja. Não duplique conta de horário.
4. **Migrações:** só crie uma migração com o número previsto no plano (18 é do Instagram, 19 dos recados). Cada migração tem teste de subida a partir da versão anterior e nunca apaga dado. Se precisar de outra, pare e pergunte.
5. **Venda:** só existe um caminho, `registrar_venda`. Não crie outro.
6. **Contrato da API v1 só cresce:** campo novo opcional, rota nova. Nunca renomear nem remover campo. Quem muda o contrato muda os dados falsos de `docs/api/mocks/`, e `docs/api/conferir_mocks.py` precisa passar.
7. **Sem texto técnico nas telas:** nada de id, UTC, nome de arquivo, comando de terminal.
8. **Segredos:** `.env`, `*.db`, `logs/` e `diagnostico_meta.py` nunca vão para o Git. Confira o `git status` antes de cada commit. Nunca mostre nem repita chaves, tokens ou senhas. Chaves só no `.env` do projeto, nunca como variável do sistema (`ANTHROPIC_API_KEY` no sistema faria o Claude Code cobrar pela API em vez da assinatura).

## Regras de comportamento do Léo (prompt e ferramentas)
- **Descrição de ferramenta curta.** Descrição longa atrapalha o modelo leve; o detalhe vai na mensagem que a própria ferramenta devolve.
- **Preço só vem de ferramenta** (estoque ou simulação) ou do que o cliente/equipe disse na conversa. Existe guarda de preço em código; ao mexer nela, teste km, ano, "mil" e valor por extenso.
- **Promessa de contato só depois de chamar `acionar_handoff`.** Sem chamado aberto, o Léo não diz que a equipe vai falar com o cliente. Sem palavra de tempo ("já já", "em breve", "logo").
- **Nunca prometer** o que a loja pode não ter: vídeo, ficha em PDF, desconto, crédito aprovado, carro "que chegou".
- **Horário da loja:** a fonte é o cadastro. Documento de conhecimento não repete horário.
- **"Para de me mandar mensagem"** é checado em código antes da IA. Errar para o lado de parar é melhor.
- **Mudança de prompt ou de comportamento exige rodada com IA real** (`-m api`) e o texto completo das respostas salvo no relatório. "Passou" sem ver o texto não prova nada. Não mude prompt só para fazer um caso passar sem avisar.

## Testes
- Comando: `python -m pytest -q` (Windows, PowerShell, ambiente `.venv-teste`).
- Durante o trabalho, rode só os subconjuntos relevantes. **A suíte completa só no fim do bloco.**
- Testes novos são offline, com LLM falso e **duas lojas** (a loja A nunca enxerga a B).
- Testes de horário usam relógio fixo (dentro e fora do expediente, sábado e domingo).
- Teste marcado `xfail` que passar a ficar vermelho porque o conserto entrou: tire a marca.
- Testes `-m api` gastam dinheiro: só sob demanda, com o teto de gasto configurado (`LEO_API_TETO_USD`). Nunca a cada commit.

## Git
- **Um bloco por branch, com tag.** Commit no padrão `feat(<bloco>): o que mudou`. Faça `git push` da branch.
- **Nada vai para a `main` sem validação do analista.** Você não faz merge na `main`, não faz push na `main` e não mexe em tags de marco.
- Faça só o que o bloco pede. Se achar um problema fora do escopo, pare, anote e avise; não corrija por conta própria.
- Mensagem de commit e relatório em português.

## Formato do relatório ao terminar um bloco
1. Branch e tag.
2. Suíte offline: número de testes e resultado.
3. Rodadas com IA real: custo e resultado, com o caminho do arquivo que guarda o texto completo.
4. O que foi resolvido.
5. O que sobrou, com os casos duvidosos.
6. Perguntas para decidir.

## Antes de dizer "pronto"
O bloco só está pronto quando: a suíte offline inteira passa; o teste prático do bloco foi feito à mão; o código está commitado e enviado na branch; nada fora do escopo foi alterado. Diga com clareza o que você rodou e o que **não** rodou.

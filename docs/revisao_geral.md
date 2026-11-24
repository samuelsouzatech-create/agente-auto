# Revisão geral do código (Maratona 2, M4)

Só relatório: nada foi consertado neste bloco. Cada achado foi conferido no código (grep/leitura) ou numa
rodada da bancada desta maratona. Severidade: **alta** / **média** / **baixa**. Custo do conserto:
**pequeno** (horas) / **médio** (um bloco) / **grande** (vários blocos).

## Segurança e privacidade

| # | Arquivo | Problema | Sev. | Custo |
|---|---------|----------|------|-------|
| 1 | `app/demo.py` (`criar_loja_demo`) | Chamado com `loja_id=` explícito, pula a checagem de "loja demo" e apaga os dados da loja indicada; hoje só a bancada e os testes usam assim, mas um engano no banco de verdade apaga uma loja real. | alta | pequeno |
| 2 | `app/core/turno.py:236` e `:611`, `app/api/webhook.py:121`, `app/api/telegram_bot.py:89` | Toda fala do cliente (e a transcrição do áudio) é impressa no console junto com o número/id do cliente; quem guardar o console do servidor guarda conversas e telefones. | alta | pequeno |
| 3 | `app/config.py:21` | `WHATSAPP_VERIFY_TOKEN` tem valor padrão escrito no código (que está no Git); sem o `.env`, qualquer um que leia o código passa na verificação do webhook (a assinatura do POST continua protegendo as mensagens). | média | pequeno |
| 4 | `app/api/receber_audio.py`, `app/channels/telegram.py`, `app/imagens.py` | Áudio e foto do cliente são baixados e mandados para a IA sem limite de tamanho ou duração: custo e memória sem teto por mensagem. | média | pequeno |
| 5 | `app/autenticacao.py` | O limite de tentativas de login é só por e-mail: alguém pode bloquear o lojista de propósito errando a senha dele; não há limite por origem. | baixa | médio  **Parte feita (Maratona Painel 2, Q1):** limite por origem no login da API (20 erros em 15 min bloqueiam aquela origem, para qualquer e-mail). **Feito na Maratona Fotos, F2:** os 5 erros contam por e-mail + origem; erro vindo de outro lugar não bloqueia o dono (terminal e scripts usam a origem "local"). |
| 6 | `operador.py`, `painel.py` | Painéis Streamlit sem login (dependem de rodar só em `localhost`, `.streamlit/config.toml`); se um dia forem expostos, ficam abertos. | média | médio |
| 7 | `app/api/receber_audio.py` | Privacidade: o áudio não é guardado, só a transcrição (como mensagem do cliente). Está certo, mas não está escrito em nenhum documento para o lojista. | baixa | pequeno |

## Comportamento do Léo e guardas (L11–L13)

| # | Arquivo | Problema | Sev. | Custo |
|---|---------|----------|------|-------|
| 8 | `app/api/receber_audio.py` (prompt da transcrição) | Áudio só com chiado: o Gemini inventa uma frase ("Certo, eu vou.", uma frase de apoio emocional) e o Léo responde ao que o cliente não disse (bancada M3, 3 de 3 rodadas). | alta | pequeno |
| 9 | `app/core/turno.py` (`executar_turno`) | Cerca de 10 passos de pós-processamento em sequência (texto interno, guardas, chamados, frase de contato, emoji, repetição, frase de oferta, sombra) sem uma lista única; é aqui que as guardas colidem (uma corta a pergunta, outra acrescenta frase, a limpeza tira repetição). | média | médio |
| 10 | `app/guarda_politica.py` (fim do arquivo) | `_mantem_linhas` reatribui 8 guardas no fim do módulo: uma guarda nova criada depois não ganha o embrulho, e quem lê a função não vê que ela é trocada. | média | pequeno |
| 11 | `app/guarda_politica.py` (estado do carro) | A negação é procurada numa janela de 40 caracteres por regex: ainda passou "garantir o melhor valor" e bloqueia "vistoria" dentro de frase negativa. Regras por palavra vão continuar tendo furos dos dois lados. | média | médio |
| 12 | `app/core/turno.py` (`turno_resposta_fixa`) + bancada | Resposta fixa (falso dono) sai idêntica duas vezes seguidas e colide com a checagem "duas respostas iguais": FALHOU em todas as rodadas da maratona. | baixa | pequeno |
| 13 | `prompts/` | O Léo acrescenta "a loja está fechada agora, mas abrimos amanhã..." em respostas que não perguntaram horário, e diz "Como mencionei" ao repetir. | baixa | pequeno |

## Várias lojas e servidor ligado muito tempo

| # | Arquivo | Problema | Sev. | Custo |
|---|---------|----------|------|-------|
| 14 | `banco.py` (`conectar`) | SQLite sem modo WAL nem tempo de espera ajustado: webhook, jobs e painéis escrevendo ao mesmo tempo podem dar "database is locked" quando houver movimento real. | média | pequeno |
| 15 | `app/api/webhook.py` (`BackgroundTasks`) | A mensagem é processada dentro do mesmo processo depois de responder 200 à Meta: se o servidor reiniciar nesse meio-tempo, a mensagem se perde (sem fila, sem nova tentativa). | média | médio |
| 16 | `app/api/telegram_bot.py` (`LOJA_DO_BOT`) | Um processo de bot por loja (variável global): com várias lojas no Telegram, são vários processos, cada um com seu próprio grafo e memória. | média | médio |
| 17 | `app/core/agent.py` (`MemorySaver`) | A memória da conversa fica no processo; com mais de um processo, cada um tem a sua. O histórico volta do banco quando falta (`historico_se_esqueceu`), então o impacto é pequeno. | baixa | médio |
| 18 | `app/lojas.py` (`_cache_config`) | Cache da configuração por (loja, versão) nunca apaga versões antigas: cresce a cada "salvar configuração" enquanto o servidor estiver ligado. | baixa | pequeno |
| 19 | `app/api/webhook.py` (`_ultima_recebida`) | Ao passar do limite, apaga tudo de uma vez: os "lido" pendentes de todos os clientes somem juntos. | baixa | pequeno |
| 20 | `app/` (152 `print`, 21 `except` amplos) | Sem `logging` com nível e rotação; erros engolidos por `except Exception` ficam invisíveis num servidor ligado por semanas. | média | médio |

## Código morto ou duplicado

| # | Arquivo | Problema | Sev. | Custo |
|---|---------|----------|------|-------|
| 21 | 7 arquivos (`tools/utils.py`, `paginas/comum.py`, `app/estoque_conhecimento.py`, `app/custos_precos.py`, `app/jobs/alertas.py`, `app/api_painel/carros.py`, `app/demo.py`) | A conta de formatar "R$ 1.234,56" está copiada 7 vezes; uma mudança vai esquecer alguma. | baixa | pequeno |
| 22 | `app/canais.py`, `app/conhecimento.py`, `app/custos.py`, `app/interesse.py`, `app/regua.py`, `app/templates.py`, `app/api/receber_audio.py` | Funções sem nenhum uso: `existe_canal_do_tipo`, `todos_os_documentos`, `resumo_todas_lojas`, `listar_situacoes`, `ligar_passo`, `listar_status`, `transcrever_bytes`. | baixa | pequeno |
| 23 | `app/implantacao.py` (`pode_colocar_no_ar`), `tests/test_furos_conhecidos.py` (`furo`) | Só os testes usam a primeira; a segunda (marca de furo) não é mais usada por nenhum teste. | baixa | pequeno |
| 24 | `app/demo.py` | A loja demo é posta no ar direto na tabela (sem `colocar_no_ar`), então o Registro não mostra quando ela entrou no ar. | baixa | pequeno |

## Testes

| # | Arquivo | Problema | Sev. | Custo |
|---|---------|----------|------|-------|
| 25 | 26 arquivos em `tests/` | Testes que leem o texto do código-fonte (procuram palavras no `.py`): quebram ao renomear e não provam comportamento. | baixa | médio |
| 26 | `tests/test_bancada_b1.py`, `test_l11_base_e_politica.py`, `test_l12_limpeza_e_acao.py` | Número de roteiros fixo no teste (52, agora 56): todo roteiro novo quebra 3 testes que não têm a ver com ele. | baixa | pequeno |
| 27 | `tests/` (suíte inteira) | ~17 minutos e muita memória: num computador de 8 GB o sistema interrompeu a suíte 4 vezes nesta maratona; há `time.sleep` real em `test_comportamento_fluxos.py` e `test_fase_2_robustez.py`. | média | médio |

## Dependências

| # | Arquivo | Problema | Sev. | Custo |
|---|---------|----------|------|-------|
| 28 | `requirements.txt` | Falta o Pillow, que `app/demo.py` usa: num servidor instalado do zero, `criar_loja_demo.py` quebra. | média | pequeno |
| 29 | `requirements.txt` | `google-genai` é usado direto (`receber_audio.py`, `imagens.py`), mas não tem versão fixa (vem por tabela do `langchain-google-genai`); uma atualização pode quebrar a transcrição e a leitura de foto. | média | pequeno |
| 30 | `requirements.txt` | Versões antigas: fastapi 0.143.3 (há 0.165.0), google-genai 2.33 (há 3.6, versão grande nova), langgraph 1.2.14 (há 1.2.24), streamlit 1.65 (há 1.67), pillow 12.3 (há 13.0). | baixa | médio |
| 31 | `requirements-dev.txt` | `pyyaml`, `jsonschema` e `openapi-spec-validator` sem versão, e o arquivo não termina com quebra de linha. | baixa | pequeno |

## As 10 para consertar antes de uma loja de verdade entrar em modo sombra

1. **#2**: parar de imprimir fala e número do cliente no console (privacidade, desde o primeiro dia de sombra).
2. **#8**: áudio sem fala vira "não entendi", em vez de uma frase inventada.
3. **#1**: `criar_loja_demo` recusar qualquer loja que não seja demo, mesmo com `loja_id` explícito.
4. **#14**: SQLite em modo WAL e com tempo de espera, antes do movimento real.
5. **#4**: limite de tamanho e duração para áudio e foto do cliente.
6. **#15**: não perder a mensagem se o servidor reiniciar (no mínimo, avisar no log e no painel).
7. **#3**: tirar o token padrão do código e falhar fechado sem ele, como já é feito com o App Secret.
8. **#28** e **#29**: fixar Pillow e google-genai no `requirements.txt`.
9. **#20**: `logging` com nível e rotação no lugar de `print`, e registrar os `except` que hoje engolem erro.
10. **#9** e **#10**: deixar a ordem do pós-processamento numa lista única e explícita, antes de criar mais guardas.

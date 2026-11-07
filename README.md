# Agente de IA para Loja de Veículos Seminovos

Agente de atendimento e qualificação de leads para lojas de veículos, construído de forma nativa em Python com LangGraph e Google Gemini. O agente ("Léo") conversa com o cliente de forma humanizada, consulta estoque real, simula financiamento, registra trocas, agenda visitas e responde dúvidas sobre as políticas da loja usando RAG.

## O que o agente faz

- **Qualificação de lead**: entende o que o cliente procura, forma de pagamento, troca e prazo.
- **Consulta de estoque**: busca carros disponíveis em banco de dados (nunca inventa preço ou modelo).
- **Simulação de financiamento**: estimativa com aviso claro de que depende de análise de crédito.
- **Registro de troca**: coleta os dados do carro do cliente (sem dar valor de avaliação).
- **Agendamento**: visita, test-drive ou ligação com vendedor.
- **Base de conhecimento (RAG)**: responde sobre financiamento, troca, garantia, test-drive e horário a partir dos documentos da loja.
- **Handoff humano**: aciona um vendedor em casos de negociação, crédito ou reclamação.

## Stack

- **Linguagem**: Python
- **Orquestração do agente**: LangGraph (StateGraph com ciclo de tool calling)
- **LLM**: Google Gemini
- **RAG**: embeddings do Gemini + Chroma
- **Banco de dados**: SQLite (local), com migrações numeradas
- **Memória rápida e relógio**: Redis
- **Painéis**: Streamlit 1.65

## Como rodar

1. Clone o repositório e entre na pasta:

   ```bash
   git clone git@github.com:samuelsouzatech-create/agente-auto.git
   cd agente-auto
   ```

2. Crie e ative um ambiente virtual:

   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```

3. Instale as dependências:

   ```bash
   pip install -r requirements.txt
   ```

4. Crie um arquivo `.env` na raiz com sua chave do Google Gemini e o seu nome (usado no painel do operador):

   ```
   GOOGLE_API_KEY=sua_chave_aqui
   OPERADOR_NOME=Seu Nome
   ```

5. Crie (ou atualize) o banco de dados com estoque de exemplo. As migrações só acrescentam; nada é apagado:

   ```bash
   python banco.py
   ```

6. Gere a base de conhecimento (RAG):

   ```bash
   python ingestao_rag.py
   ```

## Painéis (só local, sem login)

| Painel | Comando | Porta |
|---|---|---|
| Operador | `python -m streamlit run operador.py --server.port 8501` | 8501 |
| Cliente  | `$env:LOJA_ID="1"` e depois `python -m streamlit run painel.py --server.port 8502` | 8502 |
| Relógio (avisos e retomadas) | `python -m app.jobs.runner` (precisa do Redis ligado no Docker) | — |

### Painel do operador (`operador.py`)

- **Geral**: Visão geral (saúde do sistema, "Precisa de atenção" e a tabela de lojas), Custos e preços e o botão **➕ Nova loja** na lateral.
- **Loja** (a loja escolhida na lateral): Resumo, Ver como a loja, Configuração, Mensagens automáticas, Base de clientes e Registro.
- Precisa de `OPERADOR_NOME` no `.env`; sem ele, o painel não abre.
- Listas longas aparecem em páginas de 50, com "Anterior" e "Próxima".

### Painel do cliente (`painel.py`)

- Mostra só a loja de `LOJA_ID` e recusa abrir sem ela.
- Tem 8 telas e continua no ar até o painel em React substituí-lo.
- Campos de plano (módulos, teto de custo, limites) só o operador altera: a regra está no `salvar_config`, não só na tela.

Nenhum dos dois painéis pode ir para a internet até existir login.

## Testes

```bash
pytest -q -p no:cacheprovider
```

Os testes rodam sem internet, num banco temporário, com duas lojas para provar que uma não vê os dados da outra.

## Arquitetura

O projeto segue o princípio de que o banco de dados próprio é a fonte da verdade: o agente nunca inventa dados, sempre consulta tools. O estoque é consultado por tool estruturada (nunca por RAG), e o RAG é usado apenas para conteúdo textual estável (políticas e FAQ da loja). Regra de negócio fica em `app/`; as telas só mostram e chamam.

## Status

Projeto de estudo e portfólio. Painel do operador concluído na branch `painel-operador`, aguardando validação.

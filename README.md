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
- **Banco de dados**: SQLite (local, MVP)
- **Interface de teste**: Streamlit

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

4. Crie um arquivo `.env` na raiz com sua chave do Google Gemini:

   ```
   GOOGLE_API_KEY=sua_chave_aqui
   ```

5. Crie o banco de dados com estoque de exemplo:

   ```bash
   python banco.py
   ```

6. Gere a base de conhecimento (RAG):

   ```bash
   python ingestao_rag.py
   ```

7. Rode a interface de teste:

   ```bash
   streamlit run app.py
   ```

## Arquitetura

O projeto segue o princípio de que o banco de dados próprio é a fonte da verdade: o agente nunca inventa dados, sempre consulta tools. O estoque é consultado por tool estruturada (nunca por RAG), e o RAG é usado apenas para conteúdo textual estável (políticas e FAQ da loja).

## Status

Protótipo em desenvolvimento (Fase 1 — Núcleo). Projeto de estudo e portfólio.


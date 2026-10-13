import uuid
import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage
from agent import agente_grafo


def extrair_texto(content):
    # Formato antigo: já é texto puro
    if isinstance(content, str):
        return content
    # Formato novo (gemini-3.x): lista de blocos
    if isinstance(content, list):
        partes = []
        for bloco in content:
            if isinstance(bloco, dict):
                texto = bloco.get("text") or bloco.get("Texto") or bloco.get("texto")
                if texto:
                    partes.append(texto)
            elif isinstance(bloco, str):
                partes.append(bloco)
        return "\n".join(partes)
    return str(content)


st.set_page_config(page_title="Léo - Assistente da Loja", page_icon="🚗")
st.title("🚗 Léo — Assistente Virtual")
st.caption("Protótipo Fase 1 — conversa com o agente")

# Gera um lead_id único para esta conversa (uma vez por sessão do navegador)
if "lead_id" not in st.session_state:
    st.session_state.lead_id = str(uuid.uuid4())

# Guarda o histórico da conversa na sessão
if "historico" not in st.session_state:
    st.session_state.historico = []

# Mostra as mensagens já trocadas
for msg in st.session_state.historico:
    if isinstance(msg, HumanMessage):
        st.chat_message("user").write(msg.content)
    else:
        st.chat_message("assistant").write(extrair_texto(msg.content))

# Caixa de digitação do usuário
if entrada := st.chat_input("Digite sua mensagem..."):
    st.session_state.historico.append(HumanMessage(content=entrada))
    st.chat_message("user").write(entrada)

    with st.spinner("Léo está digitando..."):
        resultado = agente_grafo.invoke({
            "messages": st.session_state.historico,
            "lead_id": st.session_state.lead_id,
        })
        resposta = resultado["messages"][-1]

    st.session_state.historico.append(resposta)
    st.rerun()


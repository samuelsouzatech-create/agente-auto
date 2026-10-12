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
                # pega o texto, seja a chave "text" (inglês) ou "Texto"
                texto = bloco.get("text") or bloco.get("Texto") or bloco.get("texto")
                if texto:
                    partes.append(texto)
            elif isinstance(bloco, str):
                partes.append(bloco)
        return "\n".join(partes)
    # Qualquer outro caso: converte pra texto por segurança
    return str(content)

st.set_page_config(page_title="Léo - Assistente da Loja", page_icon="🚗")
st.title("🚗 Léo — Assistente Virtual")
st.caption("Protótipo Fase 1 — conversa com o agente (ainda sem estoque real)")

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

    # Chama o agente com todo o histórico
    
    with st.spinner("Léo está digitando..."):
        resultado = agente_grafo.invoke({"messages": st.session_state.historico})
        resposta = resultado["messages"][-1]
        
    st.session_state.historico.append(resposta)
    st.rerun()

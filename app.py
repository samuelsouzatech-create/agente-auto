import uuid
import streamlit as st
from langchain_core.messages import HumanMessage

import banco
from app.core.agent import agente_grafo
from app.utils import extrair_texto


def para_streamlit(texto):
    """Escapa o '$' só no Streamlit (ele trata '$' como fórmula LaTeX)."""
    return texto.replace("$", "\\$")


def listar_lojas():
    conexao = banco.conectar()
    try:
        return [(l["id"], l["nome"]) for l in conexao.execute("SELECT id, nome FROM lojas ORDER BY id")]
    finally:
        conexao.close()


def nova_conversa(loja_id):
    st.session_state.loja_id = loja_id
    st.session_state.lead_id = str(uuid.uuid4())
    st.session_state.historico = []


st.set_page_config(page_title="Léo - Teste por loja", page_icon="🚗")

lojas = listar_lojas()
if not lojas:
    st.error('Nenhuma loja cadastrada. Rode: python -c "import banco; banco.criar_tabelas()"')
    st.stop()

opcoes = {f"{nome} (id {id_})": id_ for id_, nome in lojas}
escolha = st.sidebar.selectbox("Conversar com a loja", list(opcoes))
loja_id = opcoes[escolha]

if st.session_state.get("loja_id") != loja_id or "lead_id" not in st.session_state:
    nova_conversa(loja_id)
if st.sidebar.button("Nova conversa"):
    nova_conversa(loja_id)
    st.rerun()

st.title("🚗 Assistente Virtual")
st.caption(f"Você é um cliente da loja: {escolha}")

for papel, texto in st.session_state.historico:
    st.chat_message(papel).write(para_streamlit(texto))

if entrada := st.chat_input("Digite sua mensagem..."):
    st.session_state.historico.append(("user", entrada))
    st.chat_message("user").write(para_streamlit(entrada))

    with st.spinner("Digitando..."):
        # A memória fica no checkpointer (thread_id): mandamos só a mensagem nova.
        resultado = agente_grafo.invoke(
            {
                "messages": [HumanMessage(content=entrada)],
                "lead_id": st.session_state.lead_id,
                "loja_id": loja_id,
                "canal": "streamlit",
            },
            {"configurable": {"thread_id": f"{loja_id}:streamlit:{st.session_state.lead_id}"}},
        )
    resposta = extrair_texto(resultado["messages"][-1].content)
    st.session_state.historico.append(("assistant", resposta))
    st.rerun()

import asyncio
import uuid

import streamlit as st

import banco
from app.core.turno import executar_turno

CANAL = "simulador"
VERSAO_HISTORICO = 2


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
    st.session_state.lead_id = f"sim-{uuid.uuid4().hex[:8]}"
    st.session_state.historico = []          # (papel, texto, fotos)
    st.session_state.versao_historico = VERSAO_HISTORICO


st.set_page_config(page_title="Léo - Simulador", page_icon="🚗")

lojas = listar_lojas()
if not lojas:
    st.error('Nenhuma loja cadastrada. Rode: python -c "import banco; banco.criar_tabelas()"')
    st.stop()

opcoes = {f"{nome} (id {id_})": id_ for id_, nome in lojas}
escolha = st.sidebar.selectbox("Conversar com a loja", list(opcoes))
loja_id = opcoes[escolha]

if (st.session_state.get("loja_id") != loja_id
        or st.session_state.get("versao_historico") != VERSAO_HISTORICO):
    nova_conversa(loja_id)
if st.sidebar.button("Nova conversa"):
    nova_conversa(loja_id)
    st.rerun()

st.title("🚗 Assistente Virtual")
st.caption(f"Você é um cliente da loja: {escolha}")

for papel, texto, fotos in st.session_state.historico:
    with st.chat_message(papel):
        if texto:
            st.write(para_streamlit(texto))
        for url in fotos:
            st.image(url, width=320)

if entrada := st.chat_input("Digite sua mensagem..."):
    st.session_state.historico.append(("user", entrada, []))
    with st.spinner("Digitando..."):
        resultado = asyncio.run(
            executar_turno(loja_id, CANAL, st.session_state.lead_id, entrada)
        )
    if resultado.silenciado:
        st.session_state.historico.append(
            ("assistant", "_(Um vendedor assumiu esta conversa. O assistente está em silêncio.)_", []))
    else:
        st.session_state.historico.append(("assistant", resultado.texto or "", resultado.midias))
    st.rerun()

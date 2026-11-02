"""Seletor de loja do painel do OPERADOR. Só operador.py importa isto."""
import streamlit as st

from app.lojas_admin import listar_lojas


def escolher_loja():
    lojas = listar_lojas()
    if not lojas:
        st.error('Nenhuma loja cadastrada. Rode: python -c "import banco; banco.criar_tabelas()"')
        st.stop()
    rotulos, vistos = {}, {}
    for l in lojas:
        vistos[l["nome"]] = vistos.get(l["nome"], 0) + 1
        n = vistos[l["nome"]]
        rotulos[l["id"]] = l["nome"] if n == 1 else f'{l["nome"]} ({n})'

    pedida = st.session_state.pop("_trocar_para_loja", None)
    if pedida in rotulos:
        st.session_state["loja_id"] = pedida
    if st.session_state.get("loja_id") not in rotulos:
        st.session_state["loja_id"] = next(iter(rotulos))

    st.sidebar.selectbox("Loja", list(rotulos), format_func=rotulos.get, key="loja_id")
    st.sidebar.caption("Painel do operador: você vê todas as lojas. Só local, sem login.")

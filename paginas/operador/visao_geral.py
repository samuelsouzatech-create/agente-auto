"""Visão geral (nível Geral). S1: página vazia. Saúde do sistema, "Precisa de
atenção" e a tabela de lojas chegam no S9."""
import streamlit as st

from paginas.comum import exigir_operador

exigir_operador()

st.title("🌐 Visão geral")
st.caption("Todas as lojas: saúde do sistema, o que precisa de atenção e a lista de lojas.")
st.info("Esta tela está sendo construída. Enquanto isso, escolha a loja na lateral "
        "e use as telas do grupo \"Antigas (serão removidas)\".")

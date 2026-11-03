"""Resumo da loja (nível Loja). S1: página vazia. O checklist de implantação
e o botão Colocar no ar chegam no S2."""
import streamlit as st

from app.lojas import carregar_loja
from paginas.comum import exigir_operador, loja_atual

exigir_operador()
loja = carregar_loja(loja_atual())

st.title("🏁 Resumo")
st.caption(f"{loja.nome} · implantação, situação de hoje e últimas mudanças.")
st.info("Esta tela está sendo construída. Enquanto isso, use as telas do grupo "
        "\"Antigas (serão removidas)\" na lateral.")

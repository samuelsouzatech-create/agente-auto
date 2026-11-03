"""Registro (nível Loja). S1: página vazia. A leitura unificada, com filtros,
chega no S3."""
import streamlit as st

from app.lojas import carregar_loja
from paginas.comum import exigir_operador, loja_atual

exigir_operador()
loja = carregar_loja(loja_atual())

st.title("📜 Registro")
st.caption(f"{loja.nome} · quem fez o quê, quando, o que era antes e o que ficou.")
st.info("Esta tela está sendo construída. Enquanto isso, o histórico de cada "
        "configuração continua nas telas do grupo \"Antigas (serão removidas)\".")

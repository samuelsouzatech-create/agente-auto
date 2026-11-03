"""Custos e preços (nível Geral). S1: página vazia. O conteúdo chega no S8."""
import streamlit as st

from paginas.comum import exigir_operador

exigir_operador()

st.title("💰 Custos e preços")
st.caption("Todas as lojas: custo do mês por loja, últimos 12 meses e preços em vigor.")
st.info("Esta tela está sendo construída. Enquanto isso, use a tela \"Custos\" "
        "no grupo \"Antigas (serão removidas)\".")

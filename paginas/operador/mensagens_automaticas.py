"""Mensagens automáticas (nível Loja). S1: página vazia. O conteúdo chega no S6."""
import streamlit as st

from app.lojas import carregar_loja
from paginas.comum import exigir_operador, loja_atual

exigir_operador()
loja = carregar_loja(loja_atual())

st.title("📨 Mensagens automáticas")
st.caption(f"{loja.nome} · retomadas, pós-venda e reativação: o que sai, o que não "
           "saiu e por quê.")
st.info("Esta tela está sendo construída. Enquanto isso, use \"Retomadas e pós-venda\" "
        "no grupo \"Antigas (serão removidas)\".")

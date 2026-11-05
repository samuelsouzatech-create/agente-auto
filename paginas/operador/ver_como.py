"""Ver como a loja (nível Loja). S1: página vazia. As abas Atender, Leads,
Resultado e Acompanhamento chegam no S5."""
import streamlit as st

from app.lojas import carregar_loja
from paginas.comum import exigir_operador, loja_atual

exigir_operador()
loja = carregar_loja(loja_atual())

st.title("👀 Ver como a loja")
st.caption(f"{loja.nome} · o painel da loja visto pelo operador.")
st.info("Esta tela está sendo construída. Enquanto isso, use \"Fila de handoff\", "
        "\"Conversas\" e \"Resultados\" no grupo \"Antigas (serão removidas)\".")

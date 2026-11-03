"""Configuração por assunto (nível Loja). S1: página vazia. Os assuntos
chegam no S4 (S4a, S4b e S4c)."""
import streamlit as st

from app.lojas import carregar_loja
from paginas.comum import exigir_operador, loja_atual

exigir_operador()
loja = carregar_loja(loja_atual())

st.title("⚙️ Configuração")
st.caption(f"{loja.nome} · toda a configuração da loja, organizada por assunto.")
st.info("Esta tela está sendo construída. Enquanto isso, use \"Configuração\", "
        "\"Plano e limites\", \"Usuários\", \"Conhecimento\", \"Estoque\" e "
        "\"Lojas e canais\" no grupo \"Antigas (serão removidas)\".")

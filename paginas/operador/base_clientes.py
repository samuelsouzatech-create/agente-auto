"""Base de clientes (nível Loja). S1: página vazia. O conteúdo chega no S7."""
import streamlit as st

from app.lojas import carregar_loja
from paginas.comum import exigir_operador, loja_atual

exigir_operador()
loja = carregar_loja(loja_atual())

st.title("📇 Base de clientes")
st.caption(f"{loja.nome} · contatos importados, consentimento e importações feitas.")
st.info("Esta tela está sendo construída. Enquanto isso, use \"Importar base\" "
        "no grupo \"Antigas (serão removidas)\".")

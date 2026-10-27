"""
Painel do CLIENTE (lojista): só as telas da loja e só a loja de LOJA_ID.
Sem seletor de loja. Sem LOJA_ID, não abre.

Rodar (PowerShell, num terminal só para ele):
    $env:LOJA_ID="1"
    python -m streamlit run painel.py --server.port 8502

Sem login: só local. Não exponha na internet.
"""
import streamlit as st

st.set_page_config(page_title="Painel da loja", page_icon="🚗", layout="wide")

from app.acesso import PainelSemLoja, loja_do_cliente  # noqa: E402
from app.lojas import carregar_loja  # noqa: E402
from paginas.comum import campo_nome, iniciar_sessao_cliente  # noqa: E402
from paginas.menu import CLIENTE, montar  # noqa: E402

try:
    LOJA_DO_CLIENTE = loja_do_cliente()
except PainelSemLoja as erro:
    st.error(f"🔒 {erro}")
    st.stop()

iniciar_sessao_cliente(LOJA_DO_CLIENTE)     # a cada rerun: a tela não troca a loja
loja = carregar_loja(LOJA_DO_CLIENTE)

navegacao = st.navigation(montar(CLIENTE))
st.sidebar.markdown(f"### {loja.nome}")
campo_nome("Vendedor")
navegacao.run()

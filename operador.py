"""
Painel do OPERADOR: seletor de loja, Lojas e canais, Plano e limites, Custos
e as telas do cliente da loja escolhida (para dar suporte).

Rodar:
    python -m streamlit run operador.py --server.port 8501

Sem login: só local. Não exponha na internet.
"""
import streamlit as st

st.set_page_config(page_title="Operador - Léo", page_icon="🛠️", layout="wide")

from paginas.comum import campo_nome, definir_ator_da_sessao, iniciar_sessao_operador  # noqa: E402
from paginas.menu import CLIENTE, OPERADOR, montar  # noqa: E402
from paginas.operador_sessao import escolher_loja  # noqa: E402

iniciar_sessao_operador()
paginas = montar(OPERADOR)
paginas.update(montar(CLIENTE, prefixo="Loja selecionada · ", com_padrao=False))

navegacao = st.navigation(paginas)
escolher_loja()
campo_nome("Operador")
definir_ator_da_sessao()      # P6: quem age nesta execução (antes da página)
navegacao.run()

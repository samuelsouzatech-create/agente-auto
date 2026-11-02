"""
Painel do OPERADOR: seletor de loja, Lojas e canais, Plano e limites, Custos
e as telas do cliente da loja escolhida (para dar suporte).

Rodar:
    python -m streamlit run operador.py --server.port 8501

Quem está usando vem do .env (OPERADOR_NOME). Sem ele, o painel não abre.
Sem login: só local. Não exponha na internet.
"""
import streamlit as st

st.set_page_config(page_title="Operador - Léo", page_icon="🛠️", layout="wide")

from paginas.comum import (  # noqa: E402
    definir_ator_da_sessao, iniciar_sessao_operador, mostrar_quem_esta_agindo,
)
from paginas.menu import CLIENTE, OPERADOR, montar  # noqa: E402
from paginas.operador_sessao import escolher_loja  # noqa: E402

iniciar_sessao_operador()
paginas = montar(OPERADOR)
paginas.update(montar(CLIENTE, prefixo="Loja selecionada · ", com_padrao=False))

navegacao = st.navigation(paginas)
escolher_loja()
definir_ator_da_sessao()      # P6: quem age nesta execução (antes da página)
mostrar_quem_esta_agindo()
navegacao.run()

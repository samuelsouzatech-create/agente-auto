"""
Painel do OPERADOR, em dois níveis (S1 da Fase 3):
  Geral: Visão geral, Custos e preços e o botão Nova loja (na lateral).
  Loja:  Resumo, Ver como a loja, Configuração, Mensagens automáticas,
         Base de clientes e Registro, da loja escolhida na lateral.
O grupo "Antigas (serão removidas)" mantém as telas atuais até as novas
ficarem prontas e testadas.

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
from paginas.menu import montar_operador  # noqa: E402
from paginas.operador.nova_loja import abrir_nova_loja  # noqa: E402
from paginas.operador_sessao import escolher_loja  # noqa: E402

iniciar_sessao_operador()
navegacao = st.navigation(montar_operador())
escolher_loja()
definir_ator_da_sessao()      # P6: quem age nesta execução (antes da página)
mostrar_quem_esta_agindo()
if st.sidebar.button("➕ Nova loja"):
    abrir_nova_loja()
navegacao.run()

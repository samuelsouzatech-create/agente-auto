"""
Painel do OPERADOR, em dois níveis (S1 da Fase 3; acabamento no S10b):
  Geral: Visão geral, Custos e preços e o botão Nova loja (na lateral).
  Loja:  Resumo, Ver como a loja, Configuração, Mensagens automáticas,
         Base de clientes e Registro, da loja escolhida na lateral.
S10b: as telas antigas saíram; o visual (paginas/operador/estilo.py) é
aplicado aqui, uma vez só; o botão Nova loja vem antes do seletor de loja,
para aparecer mesmo quando ainda não existe nenhuma loja.

Rodar (fora do Docker; no Docker ele já sobe em https://localhost:8502):
    python -m streamlit run operador.py --server.port 8502
Portas (iguais às do Docker): operador 8502, simulador 8501 (streamlit run app.py
--server.port 8501), webhook 8000 (python -m uvicorn app.api.webhook:app --host 127.0.0.1
--port 8000), API do painel novo 8001.

Quem está usando vem do .env (OPERADOR_NOME). Sem ele, o painel não abre.
Sem login: só local. Não exponha na internet.
"""
import streamlit as st

st.set_page_config(page_title="Operador - Léo", page_icon="🛠️", layout="wide")

from paginas.comum import (  # noqa: E402
    definir_ator_da_sessao, iniciar_sessao_operador, mostrar_quem_esta_agindo,
)
from paginas.menu import montar_operador  # noqa: E402
from paginas.operador.estilo import aplicar_estilo  # noqa: E402
from paginas.operador.nova_loja import abrir_nova_loja  # noqa: E402
from paginas.operador_sessao import escolher_loja  # noqa: E402
import banco  # noqa: E402

banco.declarar_sistema("operador.py (painel do operador, todas as lojas)")   # SE3: modo sistema

iniciar_sessao_operador()
aplicar_estilo()              # S10b: visual do operador, uma vez só
navegacao = st.navigation(montar_operador())
if st.sidebar.button("➕ Nova loja"):
    abrir_nova_loja()
escolher_loja()
definir_ator_da_sessao()      # P6: quem age nesta execução (antes da página)
mostrar_quem_esta_agindo()
navegacao.run()

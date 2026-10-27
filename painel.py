"""
Painel do Léo (Etapa 1, Bloco 5): uma entrada só para todas as telas.
A loja escolhida na barra lateral vale para todas as páginas.

Rodar com:  streamlit run painel.py
"""
import streamlit as st

st.set_page_config(page_title="Painel - Léo", page_icon="🧑‍💼", layout="wide")

from paginas.comum import escolher_loja  # noqa: E402

paginas = {
    "Atendimento": [
        st.Page("paginas/handoff.py", title="Fila de handoff", icon="🧑‍💼", default=True),
        st.Page("paginas/resultados.py", title="Resultados", icon="📊"),
    ],
    "Loja": [
        st.Page("paginas/estoque.py", title="Estoque", icon="🚗"),
        st.Page("paginas/configuracao.py", title="Configuração", icon="⚙️"),
        st.Page("paginas/conhecimento.py", title="Conhecimento", icon="📚"),
        st.Page("paginas/usuarios.py", title="Usuários", icon="👥"),
    ],
    "Operador": [
        st.Page("paginas/lojas_canais.py", title="Lojas e canais", icon="🏬"),
        st.Page("paginas/custos.py", title="Custos", icon="💰"),
    ],
}

navegacao = st.navigation(paginas)
escolher_loja()
navegacao.run()

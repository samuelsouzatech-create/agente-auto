"""Paginação das listas do operador (S10b, decisão 5A): botões "Anterior" e
"Próxima" com "página 2 de 7". A conta fica em app/paginacao.py; aqui só
ficam os botões. A página fica guardada por lista (chave) e, se a lista
diminuir, volta para a última página que existe."""
import streamlit as st

from app.paginacao import TAMANHO_PAGINA, pagina_de, texto_da_pagina
from paginas.comum import exigir_operador


def mostrar_paginacao(itens, chave: str, tamanho: int = TAMANHO_PAGINA) -> list:
    """Mostra os botões (só quando há mais de uma página) e devolve os itens da página."""
    exigir_operador()
    guardada = f"_pagina_{chave}"
    p = pagina_de(itens, st.session_state.get(guardada, 1), tamanho)
    st.session_state[guardada] = p["pagina"]
    if p["paginas"] > 1:
        esquerda, meio, direita = st.columns([1, 3, 1])
        if esquerda.button("⬅️ Anterior", key=f"{chave}_anterior", disabled=p["pagina"] <= 1):
            st.session_state[guardada] = p["pagina"] - 1
            st.rerun()
        meio.caption(texto_da_pagina(p))
        if direita.button("Próxima ➡️", key=f"{chave}_proxima",
                          disabled=p["pagina"] >= p["paginas"]):
            st.session_state[guardada] = p["pagina"] + 1
            st.rerun()
    return p["itens"]

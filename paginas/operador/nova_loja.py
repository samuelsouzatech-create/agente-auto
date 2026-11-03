"""Nova loja (nível Geral): janela aberta pelo botão da lateral do operador.
S1: só o esqueleto, NÃO grava nada. A criação de verdade (a loja nascendo
Em teste) chega no S2."""
import streamlit as st

from paginas.comum import exigir_operador


@st.dialog("Nova loja")
def abrir_nova_loja() -> None:
    exigir_operador()
    st.write("Aqui você vai criar uma loja nova informando nome, cidade, fuso horário "
             "e segmento. A loja vai nascer Em teste, sem falar com clientes reais.")
    st.info("Esta parte ainda está sendo construída. Por enquanto, crie a loja na tela "
            "\"Lojas e canais\", no grupo \"Antigas (serão removidas)\".")
    if st.button("Fechar"):
        st.rerun()

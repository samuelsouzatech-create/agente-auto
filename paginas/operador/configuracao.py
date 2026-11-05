"""Configuração por assunto (nível Loja), S4a, S4b e S4c da Fase 3.

Uma tela só, com os assuntos numa lateral. Identidade, Atendimento, Handoff,
Financiamento e Plano e limites (S4a); Equipe e Canais (S4b); Estoque e
Conhecimento (S4c). A tela só mostra e chama app/.
"""
import streamlit as st

from app.config_tela import ASSUNTOS, ASSUNTOS_COM_CAMPOS
from app.lojas import carregar_loja
from paginas.comum import (
    definir_ator_da_sessao, exigir_operador, loja_atual, mostrar_aviso, papel_atual,
    para_streamlit, usuario_atual,
)
from paginas.form_config import mostrar_assunto
from paginas.operador.config_canais import mostrar_canais
from paginas.operador.config_conhecimento import mostrar_conhecimento
from paginas.operador.config_equipe import mostrar_equipe
from paginas.operador.config_estoque import mostrar_estoque

exigir_operador()
loja = carregar_loja(loja_atual())

st.title("⚙️ Configuração")
st.caption(f"{para_streamlit(loja.nome)} · toda a configuração da loja, organizada por assunto. "
           "Mudou aqui, vale na próxima mensagem do cliente.")
definir_ator_da_sessao()
mostrar_aviso()

ASSUNTOS_PROPRIOS = {"Equipe": mostrar_equipe, "Canais": mostrar_canais,
                     "Estoque": mostrar_estoque, "Conhecimento": mostrar_conhecimento}

lateral, conteudo = st.columns([1, 3])
with lateral:
    assunto = st.radio("Assunto", ASSUNTOS, key="config_assunto", label_visibility="collapsed")
with conteudo:
    if assunto in ASSUNTOS_COM_CAMPOS:
        mostrar_assunto(loja, assunto, papel_atual(), usuario_atual())
    elif assunto in ASSUNTOS_PROPRIOS:
        ASSUNTOS_PROPRIOS[assunto](loja)
    else:
        st.subheader(assunto)
        st.info("Este assunto chega em breve.")

st.caption("Retomadas, pós-venda, envio de verdade, Instagram e prazo de guarda das conversas "
           "continuam por enquanto em \"Configuração\" e \"Plano e limites\", no grupo "
           "\"Antigas (serão removidas)\".")

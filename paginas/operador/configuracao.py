"""Configuração por assunto (nível Loja), S4a da Fase 3.

Uma tela só, com os assuntos numa lateral. Identidade, Atendimento, Handoff,
Financiamento e Plano e limites já funcionam (S4a). Equipe e Canais chegam
no S4b; Estoque e Conhecimento no S4c: até lá, a tela aponta a tela antiga.
A tela só mostra e chama: o mapa fica em app/config_tela.py e o Desfazer e a
"última alteração" em app/config_assunto.py.
"""
import streamlit as st

from app.config_tela import ASSUNTOS, ASSUNTOS_COM_CAMPOS
from app.lojas import carregar_loja
from paginas.comum import (
    definir_ator_da_sessao, exigir_operador, loja_atual, mostrar_aviso, papel_atual,
    para_streamlit, usuario_atual,
)
from paginas.form_config import mostrar_assunto

TELA_ANTIGA = {"Equipe": "Usuários", "Conhecimento": "Conhecimento",
               "Estoque": "Estoque", "Canais": "Lojas e canais"}

exigir_operador()
loja = carregar_loja(loja_atual())

st.title("⚙️ Configuração")
st.caption(f"{para_streamlit(loja.nome)} · toda a configuração da loja, organizada por assunto. "
           "Mudou aqui, vale na próxima mensagem do cliente.")
definir_ator_da_sessao()
mostrar_aviso()

lateral, conteudo = st.columns([1, 3])
with lateral:
    assunto = st.radio("Assunto", ASSUNTOS, key="config_assunto", label_visibility="collapsed")
with conteudo:
    if assunto in ASSUNTOS_COM_CAMPOS:
        mostrar_assunto(loja, assunto, papel_atual(), usuario_atual())
    else:
        st.subheader(assunto)
        st.info(f"Este assunto chega em breve. Enquanto isso, use \"{TELA_ANTIGA[assunto]}\" "
                "no grupo \"Antigas (serão removidas)\".")

st.caption("Retomadas, pós-venda, envio de verdade, Instagram e prazo de guarda das conversas "
           "continuam por enquanto em \"Configuração\" e \"Plano e limites\", no grupo "
           "\"Antigas (serão removidas)\".")

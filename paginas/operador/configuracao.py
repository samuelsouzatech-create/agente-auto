"""Configuração por assunto (nível Loja), S4a, S4b, S4c e S10a da Fase 3.

Uma tela só, com os assuntos numa lateral. Identidade, Atendimento, Handoff,
Financiamento e Plano e limites (S4a); Equipe e Canais (S4b); Estoque e
Conhecimento (S4c). A tela só mostra e chama app/.

S10a: "Outros ajustes" (Instagram e prazo de guarda das conversas, que só
existiam nas telas antigas) e o nome da loja, dentro de Identidade (vinha de
"Lojas e canais"). Retomadas, pós-venda e envio de verdade ficam em
"Mensagens automáticas", aba Regras.
"""
import streamlit as st

from app.config_tela import (
    ASSUNTOS, ASSUNTOS_COM_CAMPOS, OUTROS_AJUSTES, campos_de_outros_ajustes,
)
from app.lojas import carregar_loja
from app.lojas_admin import renomear_loja
from paginas.comum import (
    avisar, definir_ator_da_sessao, exigir_operador, loja_atual, mostrar_aviso, papel_atual,
    para_streamlit, usuario_atual,
)
from paginas.form_config import mostrar_assunto, mostrar_campos
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
OPCOES = (*ASSUNTOS, OUTROS_AJUSTES)


def _nome_da_loja(loja) -> None:
    """S10a: renomear a loja (vinha da tela antiga "Lojas e canais")."""
    with st.expander("✏️ Nome da loja"):
        with st.form(f"s10_renomear_{loja.id}"):
            novo = st.text_input("Nome da loja", value=loja.nome, max_chars=80,
                                 key=f"s10_nome_{loja.id}")
            salvar = st.form_submit_button("💾 Salvar nome")
        if salvar:
            try:
                mudou = renomear_loja(loja.id, novo)
            except ValueError as erro:
                st.error(f"Nome da loja: {erro}")
            else:
                if mudou:
                    avisar("Nome da loja salvo.")
                else:
                    avisar("Não encontrei esta loja.", "error")
                st.rerun()


lateral, conteudo = st.columns([1, 3])
with lateral:
    assunto = st.radio("Assunto", OPCOES, key="config_assunto", label_visibility="collapsed")
with conteudo:
    if assunto in ASSUNTOS_COM_CAMPOS:
        mostrar_assunto(loja, assunto, papel_atual(), usuario_atual())
        if assunto == "Identidade":
            _nome_da_loja(loja)
    elif assunto in ASSUNTOS_PROPRIOS:
        ASSUNTOS_PROPRIOS[assunto](loja)
    elif assunto == OUTROS_AJUSTES:
        mostrar_campos(loja, OUTROS_AJUSTES, campos_de_outros_ajustes(), "outros",
                       papel_atual(), usuario_atual(),
                       nota="Instagram e prazo de guarda das conversas.")
    else:
        st.subheader(assunto)
        st.info("Este assunto chega em breve.")

st.caption("Retomadas, pós-venda e envio de verdade ficam em “Mensagens automáticas”, "
           "aba Regras.")

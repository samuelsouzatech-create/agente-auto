"""Nova loja (nível Geral): janela aberta pelo botão da lateral do operador.
S2: cria a loja de verdade por app.lojas_admin.criar_loja. A loja nasce
Em teste e já abre no Resumo, com o checklist."""
import streamlit as st

from app.estado_loja import SoOperador
from app.lojas_admin import (
    FUSO_PADRAO, FUSOS_DO_BRASIL, LojaInvalida, criar_loja, rotulo_segmento,
)
from app.segmentos import segmentos_disponiveis
from paginas.comum import avisar, definir_ator_da_sessao, exigir_operador, trocar_loja


@st.dialog("Nova loja")
def abrir_nova_loja() -> None:
    exigir_operador()
    definir_ator_da_sessao()      # a janela roda sozinha: garante quem está agindo
    st.write("A loja nasce Em teste: só os números de teste conversam com o "
             "assistente até você colocá-la no ar.")
    fusos = list(FUSOS_DO_BRASIL)
    with st.form("criar_nova_loja"):
        nome = st.text_input("Nome da loja", max_chars=80)
        cidade = st.text_input("Cidade", max_chars=80)
        fuso = st.selectbox("Fuso horário", fusos, index=fusos.index(FUSO_PADRAO),
                            format_func=FUSOS_DO_BRASIL.get)
        segmento = st.selectbox("Segmento", segmentos_disponiveis(),
                                format_func=rotulo_segmento)
        if st.form_submit_button("Criar loja"):
            try:
                novo_id = criar_loja(nome, cidade, fuso, segmento)
            except LojaInvalida as erro:
                for e in erro.erros:
                    st.error(e)
            except SoOperador as erro:
                st.error(str(erro))
            else:
                trocar_loja(novo_id)
                avisar(f"Loja {nome.strip()} criada em teste. Siga o checklist abaixo.")
                st.rerun()

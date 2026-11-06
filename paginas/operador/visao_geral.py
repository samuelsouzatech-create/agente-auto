"""Visão geral (nível Geral), S9 da Fase 3: saúde do sistema, "Precisa de
atenção" e a tabela de lojas. A tela só mostra o que vem pronto de
app/visao_geral.py (nada de SQL nem de conta aqui).

Decisões 9A e 10A: clicar numa linha da tabela abre o Resumo da loja; a parte
de baixo se atualiza sozinha a cada 30 s (a saúde é lida na hora; as lojas
têm cache curto por loja, em app/)."""
import streamlit as st

from app import visao_geral as vg
from app.alertas_config import ATUALIZAR_S
from paginas.comum import exigir_operador, para_streamlit, trocar_loja

RESUMO = "paginas/operador/resumo.py"

exigir_operador()

# Clique na tabela (9A): troca a loja e abre o Resumo com a página inteira.
pedida = st.session_state.pop("_s9_abrir_loja", None)
if pedida is not None:
    st.session_state["_s9_tabela_n"] = st.session_state.get("_s9_tabela_n", 0) + 1
    trocar_loja(pedida)
    st.switch_page(RESUMO)

st.title("🌐 Visão geral")
st.caption(f"Todas as lojas. Horários de Brasília. Atualiza sozinha a cada {ATUALIZAR_S} s.")


@st.fragment(run_every=f"{ATUALIZAR_S}s")
def painel():
    dados = vg.visao_geral()

    st.subheader("Saúde do sistema")
    itens = dados["saude"]["itens"]
    for coluna, item in zip(st.columns(len(itens)), itens):
        with coluna:
            st.markdown(f"**{item['emoji']} {item['nome']}**")
            st.write(para_streamlit(item["texto"]))
            for detalhe in item["detalhes"]:
                st.caption(para_streamlit(detalhe))

    if dados["alertas"]:
        st.subheader("⚠️ Precisa de atenção")
        for a in dados["alertas"]:
            mostrar = st.error if a["nivel"] == vg.VERMELHO else st.warning
            mostrar(para_streamlit(a["texto"]))

    st.subheader("Lojas")
    if not dados["linhas"]:
        st.info("Nenhuma loja cadastrada.")
        return
    st.caption("Clique numa linha para abrir o Resumo da loja.")
    escolha = st.dataframe(dados["linhas"], hide_index=True, on_select="rerun",
                           selection_mode="single-row",
                           key=f"s9_tabela_{st.session_state.get('_s9_tabela_n', 0)}")
    try:
        linhas = list(escolha.selection.rows)
    except AttributeError:
        linhas = []
    if linhas:
        st.session_state["_s9_abrir_loja"] = dados["lojas"][linhas[0]]["loja_id"]
        st.rerun(scope="app")


painel()

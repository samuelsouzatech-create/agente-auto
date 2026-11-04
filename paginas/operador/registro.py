"""Registro (nível Loja, com a opção "Todas as lojas"), S3 da Fase 3.

Quem fez o quê, quando, o que era antes e o que ficou. Filtros por pessoa,
tipo de ação e período; horário no fuso de cada loja.
A tela só mostra: a leitura e os filtros ficam em app/registro_leitura.py e
o texto de cada linha em app/registro_tela.py.
"Todas as lojas" atende o "aparece também no Geral" do Plano Mestre sem
mexer no menu do S1 (escolha a confirmar com o analista).
"""
import streamlit as st

from app.lojas import carregar_loja
from app.registro_leitura import (
    acoes_no_registro, acoes_no_registro_de_todas, filtrar_registro,
    filtrar_registro_de_todas, pessoas_no_registro, pessoas_no_registro_de_todas, rotulo,
)
from app.registro_tela import (
    LIMITE_TELA, linhas_do_registro, periodo_padrao, periodo_padrao_geral,
)
from paginas.comum import exigir_operador, loja_atual, para_streamlit

exigir_operador()
loja = carregar_loja(loja_atual())

st.title("📜 Registro")
st.caption("Quem fez o quê, quando, o que era antes e o que ficou.")

ESCOPOS = {"loja": f"Só esta loja ({para_streamlit(loja.nome)})", "todas": "Todas as lojas"}
escopo = st.radio("Mostrar", list(ESCOPOS), format_func=ESCOPOS.get, horizontal=True,
                  key="registro_escopo")
todas = escopo == "todas"

if todas:
    pessoas, acoes, padrao = (pessoas_no_registro_de_todas(), acoes_no_registro_de_todas(),
                              periodo_padrao_geral())
else:
    pessoas, acoes, padrao = (pessoas_no_registro(loja.id), acoes_no_registro(loja.id),
                              periodo_padrao(loja.id))

c1, c2, c3 = st.columns(3)
pessoa = c1.selectbox("Pessoa", ["", *pessoas], format_func=lambda p: p or "Todas as pessoas",
                      key=f"registro_pessoa_{escopo}")
acao = c2.selectbox("Tipo de ação", ["", *acoes],
                    format_func=lambda a: rotulo(a) if a else "Todos os tipos",
                    key=f"registro_acao_{escopo}")
periodo = c3.date_input("Período", value=padrao, format="DD/MM/YYYY",
                        key=f"registro_periodo_{escopo}")
if todas:
    st.caption("Em todas as lojas, o período segue o horário de Brasília e cada linha "
               "mostra a hora no fuso da própria loja.")

if not isinstance(periodo, (tuple, list)) or len(periodo) < 2:
    st.info("Escolha a data final do período.")
    st.stop()

filtros = {"pessoa": pessoa or None, "acao": acao or None,
           "inicio": periodo[0], "fim": periodo[1], "limite": LIMITE_TELA}
try:
    itens = filtrar_registro_de_todas(**filtros) if todas else filtrar_registro(loja.id, **filtros)
except ValueError as erro:
    st.error(str(erro))
    st.stop()

if not itens:
    st.info("Nada registrado com esses filtros.")
else:
    st.dataframe(linhas_do_registro(itens, com_loja=todas), hide_index=True)
    if len(itens) >= LIMITE_TELA:
        st.caption(f"Mostrando as {LIMITE_TELA} mais recentes. Para ver as mais antigas, "
                   "diminua o período.")

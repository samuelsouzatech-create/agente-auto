"""Recados do dono (nível Loja), bloco L3/L4 da Fase Cérebro.

Lista os recados que o dono ou gestor deixou para o Léo comentar com os
clientes, com o botão "Desativar". Só isso. A regra fica em app/recados.py
(situação, validade e desativar, que exige ator e vai para o Registro).
Nada é apagado.
"""
import streamlit as st

from app.apresentacao import horario_para_tela
from app.lojas import carregar_loja
from app.recados import desativar_recado, listar_recados
from app.relogio import agora_utc, dia_local
from paginas.comum import avisar, exigir_operador, loja_atual, mostrar_aviso, para_streamlit

exigir_operador()
loja = carregar_loja(loja_atual())

st.title("📝 Recados do dono")
st.caption("Recados que o dono ou o gerente mandou para o assistente comentar com os clientes. "
           "Recado desativado ou vencido não é mais comentado.")
mostrar_aviso()

recados = listar_recados(loja.id, dia_local(loja, agora_utc()))
if not recados:
    st.info("Nenhum recado ainda.")

for r in recados:
    with st.container(border=True):
        st.markdown(para_streamlit(r["texto"]))
        st.caption(f"{r['situacao']} · vale até {r['validade']} · por {r['autor']} · "
                   f"{horario_para_tela(loja, r['criado_em'])}")
        if r["pode_desativar"] and st.button("Desativar", key=f"recado_desativar_{loja.id}_{r['id']}"):
            desativar_recado(loja.id, r["id"])
            avisar("Recado desativado: o assistente não comenta mais com os clientes.")
            st.rerun()

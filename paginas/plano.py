"""Plano e limites: campos do OPERADOR (módulos contratados e limites de uso).
O lojista não vê esta tela e, mesmo forçando, o salvar_config recusa."""
import streamlit as st

from app.lojas import carregar_loja
from paginas.comum import exigir_operador, loja_atual, mostrar_aviso, papel_atual, usuario_atual
from paginas.form_config import mostrar_formularios, mostrar_historico

exigir_operador()
loja = carregar_loja(loja_atual())

st.title("📦 Plano e limites")
st.caption(f"{loja.nome} · módulos contratados e limites de uso. Só o operador vê e altera. "
           "Vale na próxima mensagem do cliente.")
mostrar_aviso()
mostrar_formularios(loja, dono="operador", papel=papel_atual(), usuario=usuario_atual(),
                    texto_confirmar="Confirmado no contrato (tira a marca 'a confirmar')")
mostrar_historico(loja, "operador")

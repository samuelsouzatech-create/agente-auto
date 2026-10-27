"""Configuração da loja: só os campos do CLIENTE (item 1.8; separação de painel)."""
import streamlit as st

from app.lojas import carregar_loja
from paginas.comum import loja_atual, mostrar_aviso, papel_atual, usuario_atual
from paginas.form_config import mostrar_formularios, mostrar_historico

loja = carregar_loja(loja_atual())

st.title("⚙️ Configuração")
st.caption(f"{loja.nome} · versão {loja.versao_config}. Mudou aqui, vale na próxima "
           "mensagem do cliente, sem reiniciar nada.")
mostrar_aviso()
mostrar_formularios(loja, dono="cliente", papel=papel_atual(), usuario=usuario_atual(),
                    texto_confirmar="O cliente confirmou os valores deste grupo "
                                    "(tira a marca 'a confirmar')")
mostrar_historico(loja, "cliente")

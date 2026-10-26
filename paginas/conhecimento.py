"""Tela de Conhecimento: políticas que o agente consulta (Etapa 1, item 1.8)."""
from pathlib import Path

import streamlit as st

from app.conhecimento import (
    DocumentoInvalido, DocumentoNaoEncontrado, ErroIndexacao,
    apagar_documento, listar_documentos, salvar_documento,
)
from app.lojas import carregar_loja
from paginas.comum import avisar, loja_atual, mostrar_aviso

loja = carregar_loja(loja_atual())

st.title("📚 Conhecimento")
st.caption(f"{loja.nome} · Políticas que o agente consulta: financiamento, troca, garantia, "
           "test-drive, horário. Escreva como explicaria a um vendedor novo.")
st.info("Se o bot do Telegram ou o simulador já estiverem abertos, reinicie-os depois de "
        "salvar para garantir que leiam o texto novo.")
mostrar_aviso()


def _salvar(titulo, texto, doc_id=None):
    try:
        salvar_documento(loja.id, titulo, texto, doc_id)
        avisar("Documento salvo e indexado.")
        st.rerun()
    except DocumentoInvalido as erro:
        for mensagem in erro.erros:
            st.error(mensagem)
    except DocumentoNaoEncontrado as erro:
        st.error(str(erro))
    except ErroIndexacao as erro:
        avisar(f"Documento salvo, mas não indexado ({erro}). "
               "Rode python ingestao_rag.py para indexar.", "warning")
        st.rerun()


with st.expander("➕ Novo documento", expanded=False):
    with st.form(f"novo_doc_{loja.id}", clear_on_submit=True):
        titulo = st.text_input("Título", placeholder="Ex.: Política de troca")
        texto = st.text_area("Texto", height=250)
        arquivo = st.file_uploader("...ou envie um arquivo .txt", type=["txt", "md"])
        if st.form_submit_button("💾 Salvar documento"):
            if arquivo is not None:
                texto = arquivo.getvalue().decode("utf-8", errors="replace")
                titulo = titulo or Path(arquivo.name).stem
            _salvar(titulo, texto)

documentos = listar_documentos(loja.id)
if not documentos:
    st.info("Nenhum documento nesta loja. Sem documento, o agente responde que não "
            "encontrou a informação.")

for doc in documentos:
    with st.expander(f"📄 {doc['titulo']}  ·  atualizado em {doc['atualizado_em']} (UTC)"):
        with st.form(f"doc_{doc['id']}"):
            novo_titulo = st.text_input("Título", value=doc["titulo"])
            novo_texto = st.text_area("Texto", value=doc["texto"], height=250)
            if st.form_submit_button("💾 Salvar alterações"):
                _salvar(novo_titulo, novo_texto, doc["id"])
        certeza = st.checkbox("Quero apagar este documento", key=f"certeza_{doc['id']}")
        if st.button("🗑️ Apagar", key=f"apagar_{doc['id']}", disabled=not certeza):
            try:
                apagar_documento(loja.id, doc["id"])
                avisar("Documento apagado.")
            except ErroIndexacao as erro:
                avisar(f"Apagado do banco, mas não do índice ({erro}). "
                       "Rode python ingestao_rag.py.", "warning")
            st.rerun()

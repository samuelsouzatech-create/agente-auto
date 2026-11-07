"""Assunto Conhecimento da Configuração do operador (S4c da Fase 3).

Criar, editar e apagar os textos que o assistente consulta. Desde o O9, o
texto salvo vale na próxima mensagem do cliente, sem reiniciar nada.
A tela só mostra e chama app/ (conhecimento, estoque_conhecimento).
"""
import streamlit as st

from app.config_assunto import DesfazerRecusado, NadaParaDesfazer
from app.conhecimento import (
    DocumentoInvalido, DocumentoMudou, DocumentoNaoEncontrado, ErroIndexacao, apagar_documento,
    reindexar_loja, salvar_documento,
)
from app.estoque_conhecimento import (
    NOTA_CONHECIMENTO, desfazer_ultima, documentos_da_loja, o_que_desfazer, ultima_alteracao,
)
from paginas.comum import avisar, exigir_operador, para_streamlit

CONFLITO = ("Outra pessoa mudou este documento enquanto você editava. Nada foi gravado. "
            "Clique em \"Carregar os valores atuais\", confira e salve de novo.")
SEM_INDICE = ("O texto foi gravado, mas o assistente ainda não consegue consultá-lo. Use "
              "\"🔄 Atualizar a consulta do assistente\", no fim desta página.")
BOTAO_REINDEXAR = "🔄 Atualizar a consulta do assistente"


def _geracao(loja_id: int) -> int:
    return st.session_state.get(f"_kn_geracao_{loja_id}", 0)


def _recarregar(loja_id: int) -> None:
    st.session_state[f"_kn_geracao_{loja_id}"] = _geracao(loja_id) + 1


def _salvar(loja, titulo, texto, doc_id, esperado, mensagem) -> None:
    try:
        salvar_documento(loja.id, titulo, texto, doc_id, esperado=esperado)
    except DocumentoInvalido as erro:
        for m in erro.erros:
            st.error(m)
    except DocumentoMudou:
        st.warning(CONFLITO)
    except DocumentoNaoEncontrado:
        st.warning("Este documento não está mais nesta loja.")
    except ErroIndexacao:
        _recarregar(loja.id)
        avisar(SEM_INDICE, "warning")
        st.rerun()
    else:
        _recarregar(loja.id)
        avisar(mensagem)
        st.rerun()


def _novo(loja, ger: int) -> None:
    with st.expander("➕ Novo documento"):
        with st.form(f"kn_novo_{loja.id}_{ger}"):
            titulo = st.text_input("Título", max_chars=120, placeholder="Ex.: Política de troca",
                                   key=f"kn_novo_titulo_{loja.id}_{ger}")
            texto = st.text_area("Texto", height=250, key=f"kn_novo_texto_{loja.id}_{ger}")
            enviar = st.form_submit_button("💾 Salvar documento")
    if enviar:
        _salvar(loja, titulo, texto, None, None, f"{(titulo or '').strip()}: documento salvo.")


def _documento(loja, d: dict, ger: int) -> None:
    chave_visto = f"_kn_visto_{loja.id}_{ger}_{d['id']}"
    if chave_visto not in st.session_state:
        st.session_state[chave_visto] = dict(d["versao"])
    visto = st.session_state[chave_visto]
    prefixo = f"kn_{loja.id}_{ger}_{d['id']}"
    with st.expander(f"📄 {para_streamlit(d['titulo'])} · atualizado {d['atualizado']}"):
        if visto != d["versao"]:
            st.info("Este documento mudou desde que você abriu esta tela.")
            if st.button("🔄 Carregar os valores atuais", key=f"{prefixo}_recarregar"):
                _recarregar(loja.id)
                st.rerun()
        with st.form(f"{prefixo}_form"):
            titulo = st.text_input("Título", value=visto["titulo"], max_chars=120,
                                   key=f"{prefixo}_titulo")
            texto = st.text_area("Texto", value=visto["texto"], height=250, key=f"{prefixo}_texto")
            salvar = st.form_submit_button(f"💾 Salvar {visto['titulo']}")
        if salvar:
            _salvar(loja, titulo, texto, d["id"], visto, f"{titulo.strip()}: alterações salvas.")
        certeza = st.checkbox("Quero apagar este documento", key=f"{prefixo}_certeza")
        if st.button("🗑️ Apagar", key=f"{prefixo}_apagar", disabled=not certeza):
            try:
                apagar_documento(loja.id, d["id"], esperado=visto)
            except DocumentoMudou:
                st.warning(CONFLITO)
            except ErroIndexacao:
                _recarregar(loja.id)
                avisar(SEM_INDICE, "warning")
                st.rerun()
            else:
                _recarregar(loja.id)
                avisar(f"{d['titulo']}: apagado. Dá para trazer de volta com Desfazer.")
                st.rerun()


def _desfazer(loja) -> None:
    plano = o_que_desfazer(loja.id, "Conhecimento")
    if plano is None:
        return
    st.caption(f"Desfazer a última alteração ({plano['quando']}, por "
               f"{para_streamlit(plano['quem'])}): {para_streamlit(plano['texto'])}")
    if st.button("↩️ Desfazer", key=f"kn_desfazer_{loja.id}"):
        try:
            mensagem = desfazer_ultima(loja.id, "Conhecimento")
        except (NadaParaDesfazer, DesfazerRecusado) as erro:
            st.warning(str(erro))
        except ErroIndexacao:
            _recarregar(loja.id)
            avisar(SEM_INDICE, "warning")
            st.rerun()
        else:
            _recarregar(loja.id)
            avisar(mensagem)
            st.rerun()


def _reindexar(loja) -> None:
    with st.expander("Se o assistente não estiver achando um texto"):
        st.caption("Refaz a consulta do assistente com todos os documentos desta loja. "
                   "Pode levar alguns segundos.")
        if st.button(BOTAO_REINDEXAR, key=f"kn_reindexar_{loja.id}"):
            try:
                total = reindexar_loja(loja.id)
            except ErroIndexacao:
                st.error("Não deu para atualizar agora. Tente de novo em alguns minutos.")
            else:
                st.success(f"Pronto: {total} documento(s) em uso pelo assistente.")


def mostrar_conhecimento(loja) -> None:
    exigir_operador()
    st.subheader("Conhecimento")
    st.caption(NOTA_CONHECIMENTO)
    ultima = ultima_alteracao(loja.id, "Conhecimento")
    st.caption(f"Última alteração: {ultima['quando']}, por {para_streamlit(ultima['quem'])}"
               if ultima else "Última alteração: nenhuma ainda.")
    _desfazer(loja)
    ger = _geracao(loja.id)
    _novo(loja, ger)
    documentos = documentos_da_loja(loja.id)
    if not documentos:
        st.info("Nenhum documento nesta loja. Sem documento, o assistente responde que não "
                "encontrou a informação.")
    for d in documentos:
        _documento(loja, d, ger)
    _reindexar(loja)

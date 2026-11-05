"""Assunto Canais da Configuração do operador (S4b da Fase 3).

Os canais da loja (se a chave foi encontrada e quando chegou a última
mensagem de cliente, com "Testar conexão") e os números de teste.
A chave fica só no servidor: a tela nunca mostra a chave nem o nome dela.
A tela só mostra e chama app/ (canais, estado_loja, equipe_canais).
"""
import streamlit as st

from app.apresentacao import nome_do_canal
from app.canais import (
    TIPOS_DE_CANAL, CanalDeOutraLoja, cadastrar_canal, desativar_canal_da_loja,
    reativar_canal_da_loja,
)
from app.equipe_canais import (
    AJUDA_ID_CANAL, AJUDA_NOME_CHAVE, NOTA_CANAIS, NOTA_NUMEROS, canais_da_loja, numeros_de_teste_da_loja,
    testar_conexao, ultima_alteracao, validar_canal_novo,
)
from app.estado_loja import (
    NumeroInvalido, SoOperador, cadastrar_numero_de_teste, desativar_numero_de_teste,
)
from paginas.comum import avisar, exigir_operador, para_streamlit


def _canais(loja) -> None:
    canais = canais_da_loja(loja.id)
    if not canais:
        st.info("Nenhum canal ligado a esta loja ainda.")
    for c in canais:
        with st.container(border=True):
            icone = "🟢" if c["ativo"] else "⚪"
            st.markdown(f"{icone} **{para_streamlit(c['nome'])}** · {c['situacao']}")
            st.caption(f"Chave: {c['chave_texto']} · Última mensagem de cliente: "
                       f"{c['ultima_mensagem']}")
            col1, col2 = st.columns(2)
            if col1.button("🔌 Testar conexão", key=f"cn_testar_{loja.id}_{c['id']}"):
                ok, texto = testar_conexao(loja.id, c["id"])
                (st.success if ok else st.warning)(texto)
            if c["ativo"]:
                if col2.button("Desativar", key=f"cn_desativar_{loja.id}_{c['id']}"):
                    mudou = desativar_canal_da_loja(loja.id, c["id"])
                    avisar(f"{c['nome']}: desativado." if mudou else "Nada mudou.")
                    st.rerun()
            elif col2.button("Reativar", key=f"cn_reativar_{loja.id}_{c['id']}"):
                try:
                    mudou = reativar_canal_da_loja(loja.id, c["id"])
                except (CanalDeOutraLoja, ValueError) as erro:
                    st.error(str(erro))
                else:
                    avisar(f"{c['nome']}: reativado." if mudou else "Nada mudou.")
                    st.rerun()


def _novo_canal(loja) -> None:
    with st.expander("➕ Ligar canal"):
        with st.form(f"cn_novo_{loja.id}", clear_on_submit=True):
            tipo = st.selectbox("Tipo de canal", TIPOS_DE_CANAL, format_func=nome_do_canal)
            id_externo = st.text_input("Identificador do canal", help=AJUDA_ID_CANAL)
            nome_chave = st.text_input("Nome da chave no servidor (opcional)",
                                       help=AJUDA_NOME_CHAVE)
            enviar = st.form_submit_button("💾 Ligar canal")
    if enviar:
        erros = validar_canal_novo(tipo, id_externo, nome_chave)
        for erro in erros:
            st.error(erro)
        if not erros:
            try:
                cadastrar_canal(loja.id, tipo, id_externo, nome_chave.strip(),
                                permitir_mover=False)
            except (CanalDeOutraLoja, ValueError) as erro:
                st.error(str(erro))
            else:
                avisar(f"{nome_do_canal(tipo)}: canal ligado a esta loja.")
                st.rerun()


def _numeros(loja) -> None:
    st.markdown("**Números de teste**")
    st.caption(NOTA_NUMEROS)
    numeros = numeros_de_teste_da_loja(loja.id)
    if not numeros:
        st.caption("Nenhum número de teste ativo.")
    for n in numeros:
        col1, col2 = st.columns([4, 1])
        col1.write(f"📱 {para_streamlit(n['texto'])}")
        if col2.button("Desativar", key=f"nt_desativar_{loja.id}_{n['id']}"):
            try:
                desativar_numero_de_teste(loja.id, n["id"])
            except SoOperador as erro:
                st.error(str(erro))
            else:
                avisar("Número de teste desativado.")
                st.rerun()
    with st.expander("➕ Cadastrar número de teste"):
        with st.form(f"nt_novo_{loja.id}", clear_on_submit=True):
            canal = st.selectbox("Canal", TIPOS_DE_CANAL, format_func=nome_do_canal)
            numero = st.text_input("Número (WhatsApp) ou número do chat (Telegram)")
            nome = st.text_input("De quem é (opcional)", max_chars=80)
            enviar = st.form_submit_button("💾 Cadastrar número")
    if enviar:
        try:
            cadastrar_numero_de_teste(loja.id, canal, numero, nome)
        except (NumeroInvalido, SoOperador) as erro:
            st.error(str(erro))
        else:
            avisar("Número de teste cadastrado.")
            st.rerun()


def mostrar_canais(loja) -> None:
    exigir_operador()
    st.subheader("Canais")
    st.caption(NOTA_CANAIS)
    ultima = ultima_alteracao(loja.id, "Canais")
    st.caption(f"Última alteração: {ultima['quando']}, por {para_streamlit(ultima['quem'])}"
               if ultima else "Última alteração: nenhuma ainda.")
    _canais(loja)
    _novo_canal(loja)
    st.divider()
    _numeros(loja)
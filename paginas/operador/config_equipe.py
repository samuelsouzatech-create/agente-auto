"""Assunto Equipe da Configuração do operador (S4b da Fase 3).

Nome, papel (Vendedor, Gerente, Dono), WhatsApp, Telegram e se recebe
avisos. A tela só mostra e chama app/: a regra (validação, Registro e
proteção de conflito) fica em app/usuarios.py e a leitura pronta em
app/equipe_canais.py. Nada é apagado: quem sai é desativado.
"""
import streamlit as st

from app.equipe_canais import (
    AJUDA_TELEGRAM, NOTA_EQUIPE, equipe_da_loja, resumo_da_equipe, ultima_alteracao,
)
from app.usuarios import (
    PAPEIS, PessoaMudou, UsuarioInvalido, atualizar_usuario, criar_usuario, definir_ativo,
    rotulo_papel,
)
from paginas.comum import avisar, exigir_operador, para_streamlit

CONFLITO = ("Outra pessoa mudou este cadastro enquanto você editava. Nada foi gravado. "
            "Clique em \"Carregar os valores atuais\", confira e salve de novo.")
ROTULO_WHATSAPP = "WhatsApp (com DDI e DDD)"
ROTULO_TELEGRAM = "Telegram (número do chat)"


def _geracao(loja_id: int) -> int:
    return st.session_state.get(f"_eq_geracao_{loja_id}", 0)


def _recarregar(loja_id: int) -> None:
    """Formulários novos, com os valores atuais do banco (na próxima execução)."""
    st.session_state[f"_eq_geracao_{loja_id}"] = _geracao(loja_id) + 1


def _mostrar_erros(erro) -> None:
    for mensagem in erro.erros:
        st.error(mensagem)


def _nova_pessoa(loja, ger: int) -> None:
    with st.expander("➕ Nova pessoa"):
        with st.form(f"eq_nova_{loja.id}_{ger}"):
            nome = st.text_input("Nome", max_chars=80, key=f"eq_nova_nome_{loja.id}_{ger}")
            papel = st.selectbox("Papel", PAPEIS, format_func=rotulo_papel,
                                 key=f"eq_nova_papel_{loja.id}_{ger}")
            whatsapp = st.text_input(ROTULO_WHATSAPP, placeholder="5581999998888",
                                     key=f"eq_nova_whats_{loja.id}_{ger}")
            telegram = st.text_input(ROTULO_TELEGRAM, help=AJUDA_TELEGRAM,
                                     key=f"eq_nova_tel_{loja.id}_{ger}")
            enviar = st.form_submit_button("💾 Cadastrar pessoa")
    if enviar:
        try:
            criar_usuario(loja.id, nome, papel, telegram, whatsapp)
        except UsuarioInvalido as erro:
            _mostrar_erros(erro)
        else:
            _recarregar(loja.id)
            avisar(f"{nome.strip()}: cadastrado(a) na equipe.")
            st.rerun()


def _pessoa(loja, p: dict, ger: int) -> None:
    chave_visto = f"_eq_visto_{loja.id}_{ger}_{p['id']}"
    if chave_visto not in st.session_state:          # formulário nascendo agora
        st.session_state[chave_visto] = dict(p["versao"])
    visto = st.session_state[chave_visto]
    prefixo = f"eq_{loja.id}_{ger}_{p['id']}"

    selos = [p["rotulo_papel"]]
    if p["recebe_avisos"]:
        selos.append("🔔 recebe avisos")
    if not p["ativo"]:
        selos.append("desativada")
    icone = "👤" if p["ativo"] else "💤"
    with st.expander(f"{icone} {para_streamlit(p['nome'])} · {' · '.join(selos)}"):
        if visto != p["versao"]:
            st.info("Este cadastro mudou desde que você abriu esta tela.")
            if st.button("🔄 Carregar os valores atuais", key=f"{prefixo}_recarregar"):
                _recarregar(loja.id)
                st.rerun()
        with st.form(f"{prefixo}_form"):
            nome = st.text_input("Nome", value=visto["nome"] or "", max_chars=80,
                                 key=f"{prefixo}_nome")
            indice = PAPEIS.index(visto["papel"]) if visto["papel"] in PAPEIS else 0
            papel = st.selectbox("Papel", PAPEIS, index=indice, format_func=rotulo_papel,
                                 key=f"{prefixo}_papel")
            whatsapp = st.text_input(ROTULO_WHATSAPP, value=visto["contato_whatsapp"] or "",
                                     key=f"{prefixo}_whats")
            telegram = st.text_input(ROTULO_TELEGRAM, value=visto["contato_telegram"] or "",
                                     help=AJUDA_TELEGRAM, key=f"{prefixo}_tel")
            salvar = st.form_submit_button(f"💾 Salvar {visto['nome']}")
        if salvar:
            try:
                achou = atualizar_usuario(p["id"], loja.id, nome, papel, telegram, whatsapp,
                                          esperado=visto)
            except UsuarioInvalido as erro:
                _mostrar_erros(erro)
            except PessoaMudou:
                st.warning(CONFLITO)
            else:
                if achou:
                    _recarregar(loja.id)
                    avisar(f"{nome.strip()}: cadastro salvo.")
                    st.rerun()
                else:
                    st.warning("Esta pessoa não está mais nesta loja.")
        rotulo = "Desativar" if p["ativo"] else "Reativar"
        if st.button(rotulo, key=f"eq_ativo_{loja.id}_{p['id']}"):
            definir_ativo(p["id"], loja.id, not p["ativo"])
            _recarregar(loja.id)
            avisar(f"{p['nome']}: {'desativado(a)' if p['ativo'] else 'reativado(a)'}.")
            st.rerun()


def mostrar_equipe(loja) -> None:
    exigir_operador()
    st.subheader("Equipe")
    st.caption(NOTA_EQUIPE)
    ultima = ultima_alteracao(loja.id, "Equipe")
    st.caption(f"Última alteração: {ultima['quando']}, por {para_streamlit(ultima['quem'])}"
               if ultima else "Última alteração: nenhuma ainda.")
    resumo = resumo_da_equipe(loja.id)
    st.caption(f"{resumo['ativos']} pessoa(s) ativa(s) · "
               f"{resumo['recebem_avisos']} recebe(m) avisos.")
    ger = _geracao(loja.id)
    _nova_pessoa(loja, ger)
    pessoas = equipe_da_loja(loja.id)
    if not pessoas:
        st.info("Ninguém cadastrado ainda.")
    for p in pessoas:
        _pessoa(loja, p, ger)

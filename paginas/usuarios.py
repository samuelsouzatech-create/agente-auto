"""Tela de Usuários: vendedores e gestores da loja (Etapa 1, item 1.8)."""
import streamlit as st

from app.lojas import carregar_loja
from app.usuarios import (
    PAPEIS, UsuarioInvalido, atualizar_usuario, criar_usuario, definir_ativo, listar_usuarios,
)
from paginas.comum import avisar, loja_atual, mostrar_aviso

loja = carregar_loja(loja_atual())

st.title("👥 Usuários")
st.caption(f"Vendedores e gestores da {loja.nome}. Quem tem Telegram cadastrado vai "
           "receber o aviso de lead esperando (aviso automático no Bloco 7).")
mostrar_aviso()

with st.expander("Como descobrir o número do chat do Telegram"):
    st.markdown(
        "1. A pessoa procura o bot da loja no Telegram e manda **/start**. "
        "Sem isso, o bot não consegue escrever para ela.\n"
        "2. Para saber o número, ela manda qualquer mensagem para o **@userinfobot**, "
        "que responde com o **Id**. Esse número vai no campo Telegram."
    )


def _mostrar_erros(erro):
    for mensagem in erro.erros:
        st.error(mensagem)


with st.expander("➕ Novo usuário", expanded=False):
    with st.form(f"novo_usuario_{loja.id}", clear_on_submit=True):
        nome = st.text_input("Nome")
        papel = st.selectbox("Papel", PAPEIS)
        telegram = st.text_input("Telegram (número do chat)")
        whatsapp = st.text_input("WhatsApp (com DDI e DDD)", placeholder="5581999998888")
        if st.form_submit_button("💾 Cadastrar"):
            try:
                criar_usuario(loja.id, nome, papel, telegram, whatsapp)
                avisar(f"{nome} cadastrado(a).")
                st.rerun()
            except UsuarioInvalido as erro:
                _mostrar_erros(erro)

mostrar_inativos = st.checkbox("Mostrar desativados")
pessoas = listar_usuarios(loja.id, incluir_inativos=mostrar_inativos)
if not pessoas:
    st.info("Nenhum usuário nesta loja ainda.")

for p in pessoas:
    situacao = "🟢" if p["ativo"] else "⚪ desativado ·"
    contato = "📨 Telegram ok" if p["contato_telegram"] else "sem Telegram (não recebe aviso)"
    with st.expander(f"{situacao} {p['nome']} · {p['papel']} · {contato}"):
        with st.form(f"usuario_{p['id']}"):
            nome = st.text_input("Nome", value=p["nome"])
            papel = st.selectbox("Papel", PAPEIS,
                                 index=PAPEIS.index(p["papel"]) if p["papel"] in PAPEIS else 0)
            telegram = st.text_input("Telegram", value=p["contato_telegram"] or "")
            whatsapp = st.text_input("WhatsApp", value=p["contato_whatsapp"] or "")
            if st.form_submit_button("💾 Salvar"):
                try:
                    atualizar_usuario(p["id"], loja.id, nome, papel, telegram, whatsapp)
                    avisar("Usuário atualizado.")
                    st.rerun()
                except UsuarioInvalido as erro:
                    _mostrar_erros(erro)
        rotulo = "Desativar" if p["ativo"] else "Reativar"
        if st.button(rotulo, key=f"ativo_{p['id']}"):
            definir_ativo(p["id"], loja.id, not p["ativo"])
            avisar(f"{p['nome']}: {rotulo.lower()}do(a).")
            st.rerun()

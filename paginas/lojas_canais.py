"""Tela do operador: lojas e canais (Etapa 1, item 1.8)."""
import streamlit as st

from app.canais import TIPOS_DE_CANAL, cadastrar_canal, desativar_canal, listar_canais
from app.lojas import carregar_loja, criar_loja
from app.segmentos import segmentos_disponiveis
from app.lojas_admin import listar_lojas, renomear_loja
from paginas.comum import avisar, exigir_operador, loja_atual, mostrar_aviso, trocar_loja

exigir_operador()

st.title("🏬 Lojas e canais")
st.caption("Tela do operador. Só aparece no painel do operador.")
mostrar_aviso()

# ---------------------------------------------------------------- Lojas
st.subheader("Lojas")
st.dataframe(listar_lojas(), hide_index=True)

with st.expander("➕ Criar loja"):
    with st.form("nova_loja", clear_on_submit=True):
        nome = st.text_input("Nome da loja")
        segmento = st.selectbox("Segmento", segmentos_disponiveis())
        if st.form_submit_button("Criar"):
            try:
                novo_id = criar_loja(nome, segmento)
                trocar_loja(novo_id)
                avisar(f"Loja {novo_id} criada com os padrões do produto. Você está vendo ela agora.")
                st.rerun()
            except ValueError as erro:
                st.error(str(erro))

loja = carregar_loja(loja_atual())
st.subheader(f"Loja selecionada: {loja.nome} (id {loja.id})")

with st.form(f"renomear_{loja.id}"):
    novo_nome = st.text_input("Nome", value=loja.nome)
    if st.form_submit_button("💾 Renomear"):
        try:
            renomear_loja(loja.id, novo_nome)
            avisar("Nome atualizado.")
            st.rerun()
        except ValueError as erro:
            st.error(str(erro))

# ---------------------------------------------------------------- Canais
st.subheader("Canais desta loja")
st.caption("Enquanto nenhum canal de um tipo tiver sido cadastrado, as mensagens desse tipo vão "
           "para a loja 1 (modo de transição). Depois do primeiro cadastro, ids não cadastrados "
           "ou desativados são ignorados. O token fica no .env: aqui vai só o NOME da variável.")

canais = listar_canais(loja.id)
if not canais:
    st.info("Nenhum canal cadastrado nesta loja.")
for c in canais:
    col_tipo, col_id, col_estado, col_acao = st.columns([2, 3, 2, 2])
    col_tipo.write(c["tipo"])
    col_id.code(c["id_externo"])
    col_estado.write("🟢 ativo" if c["ativo"] else "⚪ desativado")
    if c["ativo"]:
        if col_acao.button("Desativar", key=f"des_{c['id']}"):
            desativar_canal(c["tipo"], c["id_externo"])
            avisar(f"Canal {c['tipo']} {c['id_externo']} desativado.")
            st.rerun()
    elif col_acao.button("Reativar", key=f"rea_{c['id']}"):
        cadastrar_canal(loja.id, c["tipo"], c["id_externo"], c["token_ref"] or "")
        avisar(f"Canal {c['tipo']} {c['id_externo']} reativado.")
        st.rerun()

with st.expander("➕ Cadastrar canal"):
    st.caption("Telegram: o id é a parte do token antes dos dois-pontos. "
               "Se esse id já estava em outra loja, ele passa para esta.")
    with st.form(f"novo_canal_{loja.id}", clear_on_submit=True):
        tipo = st.selectbox("Tipo", TIPOS_DE_CANAL)
        id_externo = st.text_input("Id externo (phone_number_id, id do bot ou id da conta)")
        token_ref = st.text_input("Nome da variável do .env com o token (opcional)",
                                  placeholder="TELEGRAM_TOKEN_LOJA2",
                                  help="Nunca cole o token em si aqui, só o nome da variável.")
        if st.form_submit_button("Cadastrar"):
            if ":" in token_ref or len(token_ref) > 60:
                st.error("Isso parece um token. Coloque só o NOME da variável do .env.")
            else:
                try:
                    cadastrar_canal(loja.id, tipo, id_externo, token_ref.strip())
                    avisar(f"Canal {tipo} {id_externo} ligado à loja {loja.id}.")
                    st.rerun()
                except ValueError as erro:
                    st.error(str(erro))

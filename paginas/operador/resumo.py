"""Resumo da loja (nível Loja), S2 da Fase 3.

Em teste: o checklist de implantação e o botão Colocar no ar.
No ar: números de hoje e do mês, alertas da loja e as últimas mudanças.

A tela só mostra e chama app/: a regra do checklist e do "Colocar no ar"
fica em app/implantacao.py (a tela não decide nada sozinha).
"""
import streamlit as st

from app.apresentacao import horario_para_tela, nome_do_canal
from app.estado_loja import (
    NO_AR, TIPOS_DE_CANAL, NumeroInvalido, SoOperador, cadastrar_numero_de_teste,
    listar_numeros_de_teste, situacao_da_loja,
)
from app.implantacao import (
    MANUAL, ChecklistIncompleto, ConfirmacaoErrada, ItemInvalido, checklist,
    colocar_no_ar, desmarcar_item, faltando_para_o_ar, marcar_item,
)
from app.lojas import carregar_loja
from app.resumo_loja import alertas_da_loja, resumo_hoje_e_mes, ultimas_mudancas
from app.telefone import formatar_telefone_br
from paginas.comum import avisar, exigir_operador, loja_atual, mostrar_aviso, para_streamlit

exigir_operador()
loja = carregar_loja(loja_atual())
situacao = situacao_da_loja(loja.id)

st.title("🏁 Resumo")
st.caption(f"{para_streamlit(loja.nome)} · {situacao['rotulo']}")
mostrar_aviso()


# ------------------------------------------------------------ em teste
def _numero_na_tela(n) -> str:
    numero = n["id_externo"]
    if n["tipo_de_canal"] == "whatsapp":
        numero = formatar_telefone_br(numero)
    partes = [nome_do_canal(n["tipo_de_canal"]), numero]
    if n["nome"]:
        partes.append(n["nome"])
    return " · ".join(partes)


def _numeros_de_teste() -> None:
    for n in listar_numeros_de_teste(loja.id):
        st.write(f"📱 {para_streamlit(_numero_na_tela(n))}")
    with st.expander("Cadastrar número de teste"):
        st.caption("Só estes números conversam com o assistente enquanto a loja está "
                   "em teste. No Telegram, use o número do chat da pessoa.")
        with st.form("numero_de_teste", clear_on_submit=True):
            canal = st.selectbox("Canal", TIPOS_DE_CANAL, format_func=nome_do_canal)
            numero = st.text_input("Número (WhatsApp) ou número do chat (Telegram)")
            nome = st.text_input("De quem é (opcional)", max_chars=80)
            if st.form_submit_button("Cadastrar"):
                try:
                    cadastrar_numero_de_teste(loja.id, canal, numero, nome)
                except (NumeroInvalido, SoOperador) as erro:
                    st.error(str(erro))
                else:
                    avisar("Número de teste cadastrado.")
                    st.rerun()


def _item_manual(item) -> None:
    chave = item["chave"]
    if item["feito"]:
        texto = (f"Marcado por {item['marcado_por']} · "
                 f"{horario_para_tela(loja, item['marcado_em'])}.")
        if item["observacao"]:
            texto += f" Observação: {item['observacao']}"
        st.caption(para_streamlit(texto))
        if st.button("Desmarcar", key=f"desmarcar_{chave}"):
            try:
                desmarcar_item(loja.id, chave)
            except (ItemInvalido, SoOperador) as erro:
                st.error(str(erro))
            else:
                avisar(f"{item['rotulo']}: desmarcado.")
                st.rerun()
        return
    with st.form(f"marcar_{chave}", clear_on_submit=True):
        observacao = st.text_input("Observação (opcional)", max_chars=200, key=f"obs_{chave}")
        if st.form_submit_button("Marcar como feito"):
            try:
                marcar_item(loja.id, chave, observacao)
            except (ItemInvalido, SoOperador) as erro:
                st.error(str(erro))
            else:
                avisar(f"{item['rotulo']}: marcado.")
                st.rerun()

def _checklist() -> None:
    st.subheader("Implantação")
    st.caption("A loja está em teste: só os números de teste conversam com o assistente "
               "e nada é enviado sozinho para clientes.")
    for item in checklist(loja.id):
        with st.container(border=True):
            icone = "✅" if item["feito"] else "⬜"
            st.markdown(f"{icone} **{item['rotulo']}** · {item['nivel_rotulo']}")
            texto = item["ajuda"] + (f" {item['detalhe']}" if item["detalhe"] else "")
            st.caption(para_streamlit(texto))
            if item["como"] == MANUAL:
                _item_manual(item)
            if item["chave"] == "numeros_teste":
                _numeros_de_teste()


def _botao_no_ar() -> None:
    st.subheader("Colocar no ar")
    faltando = faltando_para_o_ar(loja.id)
    if faltando:
        st.warning("Para colocar no ar, ainda falta: " + ", ".join(faltando) + ".")
        st.button("🚀 Colocar no ar", disabled=True)
        return
    st.success("Todos os itens obrigatórios estão prontos.")
    with st.form("colocar_no_ar"):
        st.write("Depois de colocar no ar, a loja passa a atender todos os clientes. "
                 "Não dá para voltar para teste.")
        digitado = st.text_input(f"Para confirmar, digite o nome da loja: {loja.nome}")
        if st.form_submit_button("🚀 Colocar no ar"):
            try:
                colocou = colocar_no_ar(loja.id, digitado)
            except (ConfirmacaoErrada, SoOperador) as erro:
                st.error(str(erro))
            except ChecklistIncompleto as erro:
                st.error(str(erro))
            else:
                avisar("A loja está no ar." if colocou else "A loja já estava no ar.")
                st.rerun()


# ------------------------------------------------------------ no ar
def _no_ar() -> None:
    dados = resumo_hoje_e_mes(loja.id)
    for titulo, chave in (("Hoje", "hoje"), ("Este mês", "mes")):
        r = dados[chave]
        st.subheader(titulo)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Conversas", r["conversas_atendidas"])
        c2.metric("Passados ao vendedor", r["passados_ao_vendedor"])
        c3.metric("Visitas marcadas", r["visitas_marcadas"])
        c4.metric("Vendas registradas", r["vendas_registradas"])
    st.subheader("Alertas")
    alertas = alertas_da_loja(loja.id)
    if not alertas:
        st.caption("Nenhum alerta agora.")
    for a in alertas:
        st.warning(a["texto"])
    st.subheader("Últimas mudanças")
    mudancas = ultimas_mudancas(loja.id)
    if not mudancas:
        st.info("Nenhuma mudança registrada ainda.")
    else:
        st.dataframe([{"Quando": m["quando"], "Quem": m["pessoa"], "O quê": m["o_que"]}
                      for m in mudancas], hide_index=True)


if situacao["estado"] == NO_AR:
    _no_ar()
else:
    _checklist()
    _botao_no_ar()
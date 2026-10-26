"""Tela de Configuração da loja (Etapa 1, item 1.8)."""
import streamlit as st

from app.config_tela import (
    CAMPOS, DIAS, GRUPOS, NOTAS_GRUPO, ROTULO_OPCAO,
    formatar, mudancas_da_tela, padrao, para_tela, traduzir_erro,
)
from app.lojas import (
    ConfigInvalida, ConflitoDeVersao, carregar_loja, historico_config, pendentes, salvar_config,
)
from paginas.comum import avisar, loja_atual, mostrar_aviso, usuario_atual

loja = carregar_loja(loja_atual())
faltam = set(pendentes(loja))

st.title("⚙️ Configuração")
st.caption(f"{loja.nome} · versão {loja.versao_config}. Mudou aqui, vale na próxima "
           "mensagem do cliente, sem reiniciar nada.")
mostrar_aviso()
st.metric("Variáveis confirmadas com o cliente", f"{len(CAMPOS) - len(faltam)} de {len(CAMPOS)}")


def _widget(campo, chave_widget):
    valor = para_tela(campo, loja.get(campo.chave))
    rotulo = campo.rotulo + ("  ·  ⚠️ padrão, a confirmar" if campo.chave in faltam else "")
    ajuda = (campo.ajuda + " " if campo.ajuda else "") + \
        f"Padrão do produto: {formatar(campo, padrao(campo))}."
    t = campo.tipo
    if t == "texto_longo":
        return st.text_area(rotulo, value=valor, help=ajuda, key=chave_widget, height=80)
    if t == "inteiro":
        return st.number_input(rotulo, value=int(valor), step=1, help=ajuda, key=chave_widget)
    if t == "decimal":
        return st.number_input(rotulo, value=float(valor), step=0.5, help=ajuda, key=chave_widget)
    if t == "percentual":
        return st.number_input(rotulo + " (% ao mês)", value=float(valor), step=0.1,
                               format="%.2f", help=ajuda, key=chave_widget)
    if t == "sim_nao":
        return st.toggle(rotulo, value=bool(valor), help=ajuda, key=chave_widget)
    if t == "dias":
        return st.multiselect(rotulo, list(DIAS), default=valor, help=ajuda, key=chave_widget)
    if t == "opcao":
        indice = campo.opcoes.index(valor) if valor in campo.opcoes else 0
        return st.selectbox(rotulo, campo.opcoes, index=indice, help=ajuda, key=chave_widget,
                            format_func=lambda o: ROTULO_OPCAO.get(o, o))
    return st.text_input(rotulo, value=valor, help=ajuda, key=chave_widget)


abas = st.tabs(list(GRUPOS))
for aba, grupo in zip(abas, GRUPOS):
    with aba:
        if grupo in NOTAS_GRUPO:
            st.caption(NOTAS_GRUPO[grupo])
        campos = [c for c in CAMPOS if c.grupo == grupo]
        prefixo = f"cfg_{loja.id}_{loja.versao_config}"
        with st.form(f"{prefixo}_form_{grupo}"):
            valores = {c.chave: _widget(c, f"{prefixo}_{c.chave}") for c in campos}
            confirmar = st.checkbox(
                "O cliente confirmou os valores deste grupo (tira a marca 'a confirmar')",
                key=f"{prefixo}_confirmar_{grupo}",
            )
            salvar = st.form_submit_button(f"💾 Salvar {grupo}")
        if salvar:
            mudancas, erros = mudancas_da_tela(loja, valores, confirmar)
            if erros:
                for erro in erros:
                    st.error(erro)
            elif not mudancas:
                st.info("Nada mudou neste grupo.")
            else:
                try:
                    salvar_config(loja.id, mudancas, usuario_atual())
                    avisar(f"{grupo}: {len(mudancas)} valor(es) salvo(s).")
                    st.rerun()
                except ConfigInvalida as erro:
                    for mensagem in erro.erros:
                        st.error(traduzir_erro(mensagem))
                except ConflitoDeVersao as erro:
                    st.warning(str(erro))

with st.expander("🕘 Histórico de mudanças"):
    historico = historico_config(loja.id, limite=30)
    if historico:
        st.dataframe(historico, hide_index=True)
    else:
        st.caption("Nenhuma mudança registrada ainda.")

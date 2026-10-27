"""Formulários de configuração, usados por 'Configuração' (campos do cliente)
e 'Plano e limites' (campos do operador). O dono decide os campos; o papel
de quem usa vai junto para o salvar_config, que é quem garante a regra."""
import streamlit as st

from app.config_tela import (
    DIAS, NOTAS_GRUPO, ROTULO_OPCAO, campos_do, formatar, grupos_do,
    mudancas_da_tela, padrao, para_tela, traduzir_erro,
)
from app.lojas import ConfigInvalida, ConflitoDeVersao, dono_da_chave, historico_config, pendentes, salvar_config
from paginas.comum import avisar


def _widget(loja, faltam, campo, chave_widget):
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


def mostrar_formularios(loja, dono: str, papel: str, usuario: str, texto_confirmar: str) -> None:
    campos = campos_do(dono)
    faltam = set(pendentes(loja)) & {c.chave for c in campos}
    st.metric("Variáveis confirmadas", f"{len(campos) - len(faltam)} de {len(campos)}")

    grupos = grupos_do(dono)
    for aba, grupo in zip(st.tabs(grupos), grupos):
        with aba:
            if grupo in NOTAS_GRUPO:
                st.caption(NOTAS_GRUPO[grupo])
            do_grupo = [c for c in campos if c.grupo == grupo]
            prefixo = f"cfg_{dono}_{loja.id}_{loja.versao_config}"
            with st.form(f"{prefixo}_form_{grupo}"):
                valores = {c.chave: _widget(loja, faltam, c, f"{prefixo}_{c.chave}") for c in do_grupo}
                confirmar = st.checkbox(texto_confirmar, key=f"{prefixo}_confirmar_{grupo}")
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
                        salvar_config(loja.id, mudancas, usuario, papel=papel)
                        avisar(f"{grupo}: {len(mudancas)} valor(es) salvo(s).")
                        st.rerun()
                    except ConfigInvalida as erro:      # inclui SemPermissao
                        for mensagem in erro.erros:
                            st.error(traduzir_erro(mensagem))
                    except ConflitoDeVersao as erro:
                        st.warning(str(erro))


def mostrar_historico(loja, dono: str) -> None:
    """Cada painel vê só o histórico dos próprios campos."""
    with st.expander("🕘 Histórico de mudanças"):
        historico = [h for h in historico_config(loja.id, limite=100)
                     if dono_da_chave(h["chave"]) == dono][:30]
        if historico:
            st.dataframe(historico, hide_index=True)
        else:
            st.caption("Nenhuma mudança registrada ainda.")

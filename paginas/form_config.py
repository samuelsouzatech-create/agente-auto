"""Formulários de configuração, usados por 'Configuração' (campos do cliente)
e 'Plano e limites' (campos do operador). O dono decide os campos; o papel
de quem usa vai junto para o salvar_config, que é quem garante a regra.

S4a: mostrar_assunto() mostra UM assunto da Configuração do operador, sem
filtrar por dono, com Salvar, Desfazer, "última alteração" e proteção de
versão. mostrar_formularios() e mostrar_historico() continuam iguais (telas
antigas e painel do cliente)."""
import streamlit as st

from app.config_tela import (
    DIAS, NOTAS_ASSUNTO, NOTAS_GRUPO, ROTULO_OPCAO, campos_do, campos_do_assunto, formatar,
    grupos_do, mudancas_da_tela, padrao, para_tela, texto_confirmar, traduzir_erro,
)
from app.config_assunto import (
    DesfazerRecusado, NadaParaDesfazer, desfazer_ultima, o_que_desfazer, ultima_alteracao,
)
from app.lojas import ConfigInvalida, ConflitoDeVersao, dono_da_chave, historico_config, pendentes, salvar_config
from app.apresentacao import horario_para_tela
from app.config_tela import ROTULO
from paginas.comum import avisar, para_streamlit

CONFLITO = ("Outra pessoa salvou a configuração desta loja enquanto você editava. "
            "Nada foi gravado. Clique em \"Carregar os valores atuais\", confira e salve de novo.")
_SLUGS = {"Identidade": "identidade", "Atendimento": "atendimento", "Equipe": "equipe",
          "Handoff": "handoff", "Financiamento": "financiamento",
          "Conhecimento": "conhecimento", "Estoque": "estoque", "Canais": "canais",
          "Plano e limites": "plano"}


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
            st.dataframe([{
                "Quando": horario_para_tela(loja, h.get("criado_em")),
                "Quem": h.get("usuario") or "",
                "Campo": ROTULO.get(h.get("chave"), h.get("chave")),
                "Antes": h.get("valor_antigo"),
                "Depois": h.get("valor_novo"),
            } for h in historico], hide_index=True)
        else:
            st.caption("Nenhuma mudança registrada ainda.")


# ------------------------------------------------------------ S4a: por assunto

def _slug(assunto: str) -> str:
    return _SLUGS.get(assunto) or "".join(ch for ch in assunto.lower() if ch.isalnum())


def _recarregar(loja_id: int, slug: str) -> None:
    """Formulário novo, com os valores atuais do banco (na próxima execução)."""
    chave = f"_cfg_geracao_{loja_id}_{slug}"
    st.session_state[chave] = st.session_state.get(chave, 0) + 1


def _mostrar_desfazer(loja, assunto, papel, usuario, prefixo, slug, versao_vista) -> None:
    plano = o_que_desfazer(loja.id, assunto)
    with st.expander("↩️ Desfazer a última alteração"):
        if plano is None:
            st.caption("Nada para desfazer neste assunto.")
            return
        st.caption(f"Feita por {para_streamlit(plano['quem'])}, {plano['quando']}. "
                   "Se desfizer, fica assim:")
        for item in plano["itens"]:
            st.markdown(para_streamlit(
                f"- **{item['rotulo']}**: {item['agora']} → {item['volta_para']}"))
        if st.button("↩️ Desfazer", key=f"{prefixo}_desfazer"):
            try:
                desfazer_ultima(loja.id, assunto, usuario, papel, versao_esperada=versao_vista)
                _recarregar(loja.id, slug)
                avisar(f"{assunto}: última alteração desfeita.")
                st.rerun()
            except (NadaParaDesfazer, DesfazerRecusado) as erro:
                st.warning(str(erro))
            except ConflitoDeVersao:
                st.warning(CONFLITO)
            except ConfigInvalida as erro:              # inclui SemPermissao
                for mensagem in erro.erros:
                    st.error(traduzir_erro(mensagem))


def mostrar_assunto(loja, assunto: str, papel: str, usuario: str) -> None:
    """Um assunto da Configuração do operador (S4a). Campos SEM filtro de dono:
    quem garante a regra do dono é o salvar_config."""
    campos = campos_do_assunto(assunto)
    slug = _slug(assunto)
    geracao = st.session_state.get(f"_cfg_geracao_{loja.id}_{slug}", 0)
    prefixo = f"assunto_{loja.id}_{slug}_{geracao}"
    chave_vista = f"_cfg_versao_{loja.id}_{slug}"
    # Formulário sendo criado agora = guarda a versão que ele está mostrando.
    if f"{prefixo}_confirmar" not in st.session_state:
        st.session_state[chave_vista] = loja.versao_config
    versao_vista = st.session_state.get(chave_vista, loja.versao_config)

    st.subheader(assunto)
    if assunto in NOTAS_ASSUNTO:
        st.caption(NOTAS_ASSUNTO[assunto])
    ultima = ultima_alteracao(loja.id, assunto)
    st.caption(f"Última alteração: {ultima['quando']}, por {para_streamlit(ultima['quem'])}"
               if ultima else "Última alteração: nenhuma ainda.")
    faltam = set(pendentes(loja)) & {c.chave for c in campos}
    if faltam:
        st.caption(f"⚠️ {len(faltam)} de {len(campos)} valor(es) ainda no padrão do produto, "
                   "a confirmar.")
    if loja.versao_config != versao_vista:
        st.info("A configuração desta loja mudou desde que você abriu esta tela.")
        if st.button("🔄 Carregar os valores atuais", key=f"{prefixo}_recarregar"):
            _recarregar(loja.id, slug)
            st.rerun()

    with st.form(f"{prefixo}_form"):
        valores = {c.chave: _widget(loja, faltam, c, f"{prefixo}_{c.chave}") for c in campos}
        confirmar = st.checkbox(texto_confirmar(assunto), key=f"{prefixo}_confirmar")
        salvar = st.form_submit_button(f"💾 Salvar {assunto}")
    if salvar:
        mudancas, erros = mudancas_da_tela(loja, valores, confirmar)
        if erros:
            for erro in erros:
                st.error(erro)
        elif not mudancas:
            st.info("Nada mudou neste assunto.")
        else:
            try:
                salvar_config(loja.id, mudancas, usuario, papel=papel,
                              versao_esperada=versao_vista)
                _recarregar(loja.id, slug)
                avisar(f"{assunto}: {len(mudancas)} valor(es) salvo(s).")
                st.rerun()
            except ConfigInvalida as erro:              # inclui SemPermissao
                for mensagem in erro.erros:
                    st.error(traduzir_erro(mensagem))
            except ConflitoDeVersao:
                st.warning(CONFLITO)

    _mostrar_desfazer(loja, assunto, papel, usuario, prefixo, slug, versao_vista)


# ------------------------------------------------------------ S10a: campos fora dos assuntos

CONFIRMAR_CAMPOS = "Valores confirmados com a loja ou no contrato (tira a marca 'a confirmar')"


def mostrar_campos(loja, titulo: str, campos: list, slug: str, papel: str, usuario: str,
                   nota: str = "") -> None:
    """Um bloco de campos fora dos assuntos (S10a): "Regras das mensagens" e
    "Outros ajustes". Mesmo Salvar do assunto: validação, dono e proteção de
    versão ficam no salvar_config. Separado por grupo. Sem Desfazer: cada
    mudança fica no Registro."""
    from app.config_tela import GRUPOS
    geracao = st.session_state.get(f"_cfg_geracao_{loja.id}_{slug}", 0)
    prefixo = f"campos_{loja.id}_{slug}_{geracao}"
    chave_vista = f"_cfg_versao_{loja.id}_{slug}"
    # Formulário sendo criado agora = guarda a versão que ele está mostrando.
    if f"{prefixo}_confirmar" not in st.session_state:
        st.session_state[chave_vista] = loja.versao_config
    versao_vista = st.session_state.get(chave_vista, loja.versao_config)

    st.subheader(titulo)
    if nota:
        st.caption(nota)
    faltam = set(pendentes(loja)) & {c.chave for c in campos}
    if faltam:
        st.caption(f"⚠️ {len(faltam)} de {len(campos)} valor(es) ainda no padrão do produto, "
                   "a confirmar.")
    if loja.versao_config != versao_vista:
        st.info("A configuração desta loja mudou desde que você abriu esta tela.")
        if st.button("🔄 Carregar os valores atuais", key=f"{prefixo}_recarregar"):
            _recarregar(loja.id, slug)
            st.rerun()

    with st.form(f"{prefixo}_form"):
        valores = {}
        for grupo in GRUPOS:
            do_grupo = [c for c in campos if c.grupo == grupo]
            if not do_grupo:
                continue
            st.markdown(f"**{grupo}**")
            for c in do_grupo:
                valores[c.chave] = _widget(loja, faltam, c, f"{prefixo}_{c.chave}")
        confirmar = st.checkbox(CONFIRMAR_CAMPOS, key=f"{prefixo}_confirmar")
        salvar = st.form_submit_button(f"💾 Salvar {titulo}")
    if salvar:
        mudancas, erros = mudancas_da_tela(loja, valores, confirmar)
        if erros:
            for erro in erros:
                st.error(erro)
        elif not mudancas:
            st.info("Nada mudou.")
        else:
            try:
                salvar_config(loja.id, mudancas, usuario, papel=papel,
                              versao_esperada=versao_vista)
                _recarregar(loja.id, slug)
                avisar(f"{titulo}: {len(mudancas)} valor(es) salvo(s).")
                st.rerun()
            except ConfigInvalida as erro:              # inclui SemPermissao
                for mensagem in erro.erros:
                    st.error(traduzir_erro(mensagem))
            except ConflitoDeVersao:
                st.warning(CONFLITO)

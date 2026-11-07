"""Assunto Estoque da Configuração do operador (S4c da Fase 3).

Cadastrar e editar carros, com fotos por link (decisão A4). Nada de
"vendido" manual (P2): a venda é registrada na conversa do cliente.
A tela só mostra e chama app/ (estoque, estoque_conhecimento).
"""
import streamlit as st

from app.config_assunto import DesfazerRecusado, NadaParaDesfazer
from app.estoque import (
    OPCOES_CAMBIO, OPCOES_STATUS, CarroMudou, StatusInvalido, adicionar_carro, atualizar_carro,
)
from app.estoque_conhecimento import (
    AJUDA_FOTOS, FONTE_DO_ESTOQUE, NOTA_ESTOQUE, desfazer_ultima, estoque_da_loja,
    o_que_desfazer, rotulo_status, ultima_alteracao,
)
from paginas.comum import avisar, exigir_operador, para_streamlit

CONFLITO = ("Outra pessoa mudou este carro enquanto você editava. Nada foi gravado. "
            "Clique em \"Carregar os valores atuais\", confira e salve de novo.")
CARRO_VAZIO = {"marca": "", "modelo": "", "ano": 2020, "km": 0, "cor": "",
               "cambio": OPCOES_CAMBIO[0], "preco": 0.0, "status": "disponivel", "fotos": ""}


def _geracao(loja_id: int) -> int:
    return st.session_state.get(f"_est_geracao_{loja_id}", 0)


def _recarregar(loja_id: int) -> None:
    st.session_state[f"_est_geracao_{loja_id}"] = _geracao(loja_id) + 1


def _campos(prefixo: str, v: dict, vendido: bool) -> dict:
    c1, c2, c3 = st.columns(3)
    marca = c1.text_input("Marca", value=v["marca"] or "", key=f"{prefixo}_marca")
    ano = c1.number_input("Ano", min_value=1950, max_value=2100, value=int(v["ano"]), step=1,
                          key=f"{prefixo}_ano")
    cambio = c1.selectbox("Câmbio", OPCOES_CAMBIO, key=f"{prefixo}_cambio",
                          index=OPCOES_CAMBIO.index(v["cambio"]) if v["cambio"] in OPCOES_CAMBIO else 0)
    modelo = c2.text_input("Modelo", value=v["modelo"] or "", key=f"{prefixo}_modelo")
    km = c2.number_input("Km", min_value=0, value=int(v["km"]), step=1000, key=f"{prefixo}_km")
    preco = c2.number_input("Preço (R$)", min_value=0.0, value=float(v["preco"]), step=1000.0,
                            format="%.2f", key=f"{prefixo}_preco")
    cor = c3.text_input("Cor", value=v["cor"] or "", key=f"{prefixo}_cor")
    if vendido:
        c3.text_input("Situação", value=rotulo_status("vendido"), disabled=True,
                      key=f"{prefixo}_status_vendido")
        status = "vendido"
    else:
        status = c3.selectbox("Situação", OPCOES_STATUS, format_func=rotulo_status,
                              key=f"{prefixo}_status",
                              index=OPCOES_STATUS.index(v["status"]) if v["status"] in OPCOES_STATUS else 0)
    fotos = st.text_area("Fotos (links separados por vírgula)", value=v["fotos"] or "",
                         help=AJUDA_FOTOS, key=f"{prefixo}_fotos")
    return {"marca": marca.strip(), "modelo": modelo.strip(), "ano": int(ano), "km": int(km),
            "cor": cor.strip(), "cambio": cambio, "preco": float(preco), "status": status,
            "fotos": fotos.strip()}


def _incompleto(dados: dict) -> bool:
    if not dados["marca"] or not dados["modelo"] or not dados["cor"]:
        st.error("Preencha pelo menos marca, modelo e cor.")
        return True
    return False


def _novo_carro(loja, ger: int) -> None:
    with st.expander("➕ Cadastrar carro"):
        with st.form(f"est_novo_{loja.id}_{ger}"):
            dados = _campos(f"est_novo_{loja.id}_{ger}", CARRO_VAZIO, False)
            enviar = st.form_submit_button("💾 Cadastrar carro")
    if enviar and not _incompleto(dados):
        try:
            adicionar_carro(loja_id=loja.id, **dados)
        except StatusInvalido as erro:
            st.error(str(erro))
        else:
            _recarregar(loja.id)
            avisar(f"{dados['marca']} {dados['modelo']}: carro cadastrado.")
            st.rerun()


def _carro(loja, c: dict, ger: int) -> None:
    chave_visto = f"_est_visto_{loja.id}_{ger}_{c['id']}"
    if chave_visto not in st.session_state:
        st.session_state[chave_visto] = dict(c["versao"])
    visto = st.session_state[chave_visto]
    prefixo = f"est_{loja.id}_{ger}_{c['id']}"
    icone = "🔴" if c["vendido"] else ("🟢" if c["versao"]["status"] == "disponivel" else "🟡")
    with st.expander(f"{icone} {para_streamlit(c['titulo'])} · {c['rotulo_status']} · "
                     f"{para_streamlit(c['preco_tela'])}"):
        st.caption("Carro vendido: por aqui só dá para corrigir os dados." if c["vendido"] else
                   "Para vender este carro, use \"Registrar venda\" na conversa do cliente.")
        if visto != c["versao"]:
            st.info("Este carro mudou desde que você abriu esta tela.")
            if st.button("🔄 Carregar os valores atuais", key=f"{prefixo}_recarregar"):
                _recarregar(loja.id)
                st.rerun()
        with st.form(f"{prefixo}_form"):
            dados = _campos(prefixo, visto, c["vendido"])
            salvar = st.form_submit_button(f"💾 Salvar {c['titulo']}")
        if salvar and not _incompleto(dados):
            try:
                resultado = atualizar_carro(c["id"], loja_id=loja.id, esperado=visto, **dados)
            except StatusInvalido as erro:
                st.error(str(erro))
            except CarroMudou:
                st.warning(CONFLITO)
            else:
                if resultado == "Carro não encontrado nesta loja.":
                    st.warning("Este carro não está mais nesta loja.")
                else:
                    _recarregar(loja.id)
                    avisar(f"{c['titulo']}: alterações salvas.")
                    st.rerun()
        if c["fotos"]:
            st.image(c["fotos"], width=200)


def _desfazer(loja) -> None:
    plano = o_que_desfazer(loja.id, "Estoque")
    if plano is None:
        return
    st.caption(f"Desfazer a última alteração ({plano['quando']}, por "
               f"{para_streamlit(plano['quem'])}): {para_streamlit(plano['texto'])}")
    if st.button("↩️ Desfazer", key=f"est_desfazer_{loja.id}"):
        try:
            mensagem = desfazer_ultima(loja.id, "Estoque")
        except (NadaParaDesfazer, DesfazerRecusado) as erro:
            st.warning(str(erro))
        else:
            _recarregar(loja.id)
            avisar(mensagem)
            st.rerun()


def mostrar_estoque(loja) -> None:
    exigir_operador()
    st.subheader("Estoque")
    st.caption(NOTA_ESTOQUE)
    st.caption(f"De onde vêm os carros: {FONTE_DO_ESTOQUE}.")
    ultima = ultima_alteracao(loja.id, "Estoque")
    st.caption(f"Última alteração: {ultima['quando']}, por {para_streamlit(ultima['quem'])}"
               if ultima else "Última alteração: nenhuma ainda.")
    _desfazer(loja)
    mostrar_vendidos = st.checkbox("Mostrar carros vendidos", value=False,
                                   key=f"est_vendidos_{loja.id}")
    ger = _geracao(loja.id)
    _novo_carro(loja, ger)
    carros = estoque_da_loja(loja.id, incluir_vendidos=mostrar_vendidos)
    if not carros:
        st.info("Nenhum carro aqui ainda.")
    for c in carros:
        _carro(loja, c, ger)

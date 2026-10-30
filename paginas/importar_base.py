"""Importar a base que a loja já tinha (Etapa 2, Bloco 6A). Só o operador.
Nada é enviado a ninguém nesta tela."""
import streamlit as st

from app import base_pos_venda, importacao, reativacao
from app.lojas import carregar_loja
from app.relogio import agora_utc, dia_local
from paginas.comum import (
    avisar, exigir_operador, loja_atual, mostrar_aviso, para_streamlit, usuario_atual,
)

exigir_operador()
loja = carregar_loja(loja_atual())

st.title("📥 Importar base da loja")
st.caption(f"{loja.nome} · clientes e compras de antes do sistema, por planilha CSV. "
           "Nada é enviado a ninguém nesta tela.")
mostrar_aviso()

resumo = importacao.resumo_da_base(loja.id)
c1, c2, c3 = st.columns(3)
c1.metric("Contatos na base", resumo["contatos"])
c2.metric("Com autorização", resumo["com_consentimento"])
c3.metric("Compras anteriores", resumo["compras"])

with st.expander("Como montar a planilha"):
    st.markdown(
        "- Só a coluna **telefone** é obrigatória (celular, com DDD).\n"
        "- Opcionais: **nome**, **carro**, **data_compra**, **pagamento** (à vista / financiado) e "
        "**meses** (do financiamento).\n"
        "- No Excel: *Salvar como → CSV*. Formate a coluna de telefone como **Texto** antes.\n"
        "- Compra só entra com carro **e** data. Sem isso, entra só o contato.")
    st.download_button("Baixar planilha modelo (CSV)", importacao.MODELO_CSV.encode("utf-8-sig"),
                       file_name="modelo_base.csv", mime="text/csv")

chave = f"arquivo_{loja.id}_{st.session_state.get('_importacoes_feitas', 0)}"
arquivo = st.file_uploader("Planilha (CSV)", type=["csv"], key=chave)

if arquivo is not None:
    try:
        previa = importacao.ler_planilha(arquivo.getvalue(), hoje=dia_local(loja, agora_utc()))
    except importacao.PlanilhaInvalida as erro:
        st.error(str(erro))
        st.stop()

    st.subheader("Prévia (nada foi gravado ainda)")
    st.caption("Colunas reconhecidas: " + ", ".join(
        f"{campo} ← '{para_streamlit(nome)}'" for campo, nome in previa.colunas.items()))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Linhas lidas", previa.total_linhas)
    m2.metric("Contatos", len(previa.contatos()))
    m3.metric("Compras", len(previa.compras))
    m4.metric("Recusadas", len(previa.recusadas))

    if previa.linhas:
        st.dataframe([{
            "Linha": l.linha, "Nome": l.nome, "Telefone": l.telefone, "Compra": l.carro,
            "Data": l.data_compra.strftime("%d/%m/%Y") if l.data_compra else "",
            "Pagamento": l.pagamento or "", "Meses": l.meses or "",
        } for l in previa.linhas[:50]], hide_index=True)
        if len(previa.linhas) > 50:
            st.caption(f"Mostrando 50 de {len(previa.linhas)} linhas válidas.")
    if previa.recusadas:
        with st.expander(f"⚠️ {len(previa.recusadas)} linha(s) recusada(s)"):
            st.dataframe([{"Linha": n, "Motivo": m} for n, m in previa.recusadas], hide_index=True)
    if previa.avisos:
        with st.expander(f"ℹ️ {len(previa.avisos)} aviso(s)"):
            st.dataframe([{"Linha": n, "Aviso": m} for n, m in previa.avisos], hide_index=True)

    consentimento = st.checkbox(
        "Confirmo que estes clientes autorizaram a loja a mandar mensagens pelo WhatsApp (LGPD).",
        help="Sem isso, os contatos ficam guardados e o assistente os reconhece, mas a loja "
             "não manda mensagem por iniciativa própria para eles.")
    if st.button("Importar", type="primary", disabled=not previa.linhas):
        try:
            r = importacao.importar(loja.id, previa, usuario=usuario_atual(),
                                    consentimento=consentimento, arquivo=arquivo.name)
        except importacao.ImportacaoInvalida as erro:
            avisar(str(erro), "error")
        else:
            st.session_state["_importacoes_feitas"] = st.session_state.get("_importacoes_feitas", 0) + 1
            avisar(f"Importado: {r['contatos_novos']} contato(s) novo(s), "
                   f"{r['contatos_atualizados']} atualizado(s), {r['compras_novas']} compra(s) nova(s)"
                   + (f", {r['compras_repetidas']} compra(s) já existiam" if r["compras_repetidas"] else "")
                   + ".")
        st.rerun()

st.divider()
st.subheader("Importações desta loja")
lista = importacao.listar_importacoes(loja.id)
if not lista:
    st.caption("Nenhuma importação ainda.")
for imp in lista:
    titulo = (f"#{imp['id']} · {imp['criado_em']} (UTC) · "
              f"{para_streamlit(imp['arquivo'] or 'sem nome')} · por {para_streamlit(imp['usuario'])}")
    if imp["desfeita_em"]:
        titulo += " · DESFEITA"
    with st.expander(titulo):
        st.write(f"{imp['contatos_novos']} contato(s) novo(s), {imp['contatos_atualizados']} "
                 f"atualizado(s), {imp['compras']} compra(s), {imp['recusadas']} linha(s) recusada(s). "
                 f"Autorização: {'sim' if imp['consentimento'] else 'não'}.")
        if not imp["desfeita_em"] and st.button("Desfazer esta importação", key=f"desfazer_{imp['id']}"):
            try:
                r = importacao.desfazer_importacao(loja.id, imp["id"])
                avisar(f"Importação desfeita: {r['contatos']} contato(s) e {r['compras']} compra(s) apagados.")
            except importacao.ImportacaoInvalida as erro:
                avisar(str(erro), "error")
            st.rerun()

st.divider()
st.subheader("Pós-venda da base")
pv = base_pos_venda.resumo(loja.id)
p1, p2 = st.columns(2)
p1.metric("Compras prontas para agendar", pv["pendentes"])
p2.metric("Passos agendados da base", pv["agendados"])
st.info("Só entram compras de contatos COM autorização. Passos cuja data já passou não saem. "
        "Pelo WhatsApp, o primeiro contato só sai por modelo aprovado pela Meta.")
if st.button("Agendar pós-venda da base", disabled=not pv["pendentes"]):
    try:
        r = base_pos_venda.agendar_base(loja.id)
    except base_pos_venda.BaseNaoAgendada as erro:
        avisar(str(erro), "error")
    else:
        avisar(f"{r['compras']} compra(s): {r['agendados']} passo(s) agendado(s), "
               f"{r['ja_passaram']} já tinham passado.")
    st.rerun()
st.divider()
st.subheader("Reativar contatos antigos")
st.caption("Uma mensagem só, por modelo aprovado pela Meta, para quem autorizou e está parado há meses. "
           "Conta no mesmo limite mensal do remarketing. Quem responder segue com o assistente normalmente.")
rr = reativacao.resumo(loja.id)
na_fila = rr["na_fila"] + rr["simulado"] + rr["falhou"]
r1, r2, r3, r4 = st.columns(4)
r1.metric("Na fila", na_fila)
r2.metric("Enviados", rr["enviado"])
r3.metric("Bloqueados", rr["bloqueado"])
r4.metric("Cancelados", rr["cancelado"])

with st.form("form_reativacao"):
    f1, f2, f3 = st.columns(3)
    meses = f1.selectbox("Parado há pelo menos", reativacao.OPCOES_MESES,
                         index=reativacao.OPCOES_MESES.index(reativacao.MESES_PADRAO),
                         format_func=lambda m: f"{m} meses")
    publico = f2.selectbox("Quem", list(reativacao.PUBLICOS), format_func=reativacao.PUBLICOS.get)
    maximo = f3.number_input("Máximo de contatos", min_value=1, max_value=reativacao.MAX_POR_LOTE,
                             value=50, step=10)
    montar = st.form_submit_button("Montar fila de reativação")
if montar:
    try:
        r = reativacao.montar_fila(loja.id, meses=int(meses), publico=publico, maximo=int(maximo),
                                   usuario=usuario_atual())
    except reativacao.ReativacaoInvalida as erro:
        avisar(str(erro), "error")
    else:
        fora = ", ".join(f"{reativacao.MOTIVOS.get(k, k)}: {v}" for k, v in r["ignorados"].items())
        avisar(f"{r['na_fila']} contato(s) na fila." + (f" Ficaram de fora - {fora}." if fora else ""))
    st.rerun()

if na_fila and st.button("Cancelar a fila de reativação"):
    n = reativacao.cancelar_fila(loja.id)
    avisar(f"{n} contato(s) tirados da fila.")
    st.rerun()

ultimos = reativacao.listar(loja.id)
if ultimos:
    with st.expander(f"Últimos {len(ultimos)} da reativação"):
        st.dataframe([{
            "Telefone": l["telefone"],
            "Situação": reativacao.ROTULOS_ESTADO.get(l["estado"], l["estado"]),
            "Motivo": reativacao.MOTIVOS.get(l["motivo"] or "", l["motivo"] or ""),
            "Mensagem": l["texto"] or "",
            "Atualizado (UTC)": l["atualizado_em"] or "",
        } for l in ultimos], hide_index=True)

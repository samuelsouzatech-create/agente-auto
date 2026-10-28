"""Tela de Custos (Etapa 1, Bloco 6 - item 1.9). Tela do operador."""
import streamlit as st

from app import custos, precos, relogio
from app.lojas import carregar_loja
from paginas.comum import avisar, exigir_operador, loja_atual, mostrar_aviso

exigir_operador()

def brl(valor, casas=2):
    """Custo de IA por resposta é fração de centavo: mais casas quando precisa."""
    texto = f"{float(valor or 0):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


loja = carregar_loja(loja_atual())
hoje = precos.hoje_utc()

st.title("💰 Custos")
st.caption(f"{loja.nome} · tela do operador (o lojista não vê o seu custo). Datas em UTC.")
mostrar_aviso()

faltam = precos.faltando(hoje)
if faltam:
    nomes = ", ".join(precos.ITENS[i]["rotulo"] for i in faltam)
    st.warning(f"⚠️ Preço não cadastrado: {nomes}. Os tokens já estão sendo medidos; "
               "o custo em R$ aparece quando você cadastrar os preços (lá embaixo).")

# ------------------------------------------------------------- mês
meses, ano, mes = [], hoje.year, hoje.month
for _ in range(12):
    meses.append((ano, mes))
    ano, mes = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
ano, mes = st.selectbox("Mês", meses, format_func=lambda am: f"{am[1]:02d}/{am[0]}")

r = custos.resumo_mes(loja.id, ano, mes)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Custo do mês", brl(r["custo_total"]))
c2.metric("Conversas", r["conversas"], help="Leads diferentes que falaram com o agente no mês.")
c3.metric("Custo médio por conversa", brl(r["custo_medio_conversa"], 4))
c4.metric("Respostas do agente", r["turnos"])

c5, c6, c7, c8 = st.columns(4)
c5.metric("Custo de IA", brl(r["custo_ia"], 4))
c6.metric("Custo Meta (WhatsApp)", brl(r["custo_meta"], 4))
c7.metric("Tokens (entrada / saída)",
          f'{r["tokens_entrada"] + r["tokens_audio"]:,} / {r["tokens_saida"]:,}'.replace(",", "."))
media = r["latencia_media_ms"]
c8.metric("Tempo médio de resposta", f"{media / 1000:.1f} s".replace(".", ",") if media else "—")

if r["incompletas"]:
    st.warning(f'{r["incompletas"]} execução(ões) com preço faltando: o custo delas está '
               "subestimado. Cadastre os preços e clique em Recalcular.")

# ------------------------------------------------------------- teto diário
teto = loja.get("custos.teto_diario_llm")
hoje_loja = relogio.dia_local(loja, relogio.agora_utc())
gasto_hoje = custos.gasto_do_dia(loja.id, hoje_loja, fuso=loja.get("fuso"))
if teto:
    st.progress(min(gasto_hoje / teto, 1.0),
                text=f"Gasto de hoje ({hoje_loja:%d/%m}, horário da loja): "
                     f"{brl(gasto_hoje, 4)} de {brl(teto)} (teto diário)")
    if gasto_hoje >= teto:
        st.error("Teto diário atingido. O alerta vai pelo bot de avisos "
                 "(precisa do python -m app.jobs.runner ligado).")
else:
    st.caption(f"Gasto de hoje: {brl(gasto_hoje, 4)}. Sem teto diário "
               "(defina em Plano e limites > Custos).")

# ------------------------------------------------------------- detalhes
por_dia = custos.custo_por_dia(loja.id, ano, mes)
if por_dia:
    st.subheader("Custo por dia (R$)")
    st.bar_chart(por_dia, x="dia", y="custo")

ferramentas = custos.ferramentas_mais_usadas(loja.id, ano, mes)
if ferramentas:
    st.subheader("Ferramentas mais usadas")
    st.dataframe([{"ferramenta": n, "vezes": q} for n, q in ferramentas], hide_index=True)

with st.expander("🏬 Todas as lojas neste mês"):
    st.dataframe(custos.resumo_todas_lojas(ano, mes), hide_index=True)

with st.expander("🧾 Últimas execuções desta loja"):
    ultimas = custos.ultimas_execucoes(loja.id)
    if ultimas:
        st.dataframe(ultimas, hide_index=True)
    else:
        st.caption("Nenhuma execução registrada ainda.")

# ------------------------------------------------------------- preços
st.divider()
st.subheader("Preços")
st.caption("Copie da página oficial de preços do fornecedor de IA e da tabela oficial da Meta. "
           "Preço de IA é por 1 milhão de tokens. Mudou o preço ou trocou de modelo de IA? "
           "Cadastre um novo com a data da mudança; o antigo continua valendo para o passado.")

lista = precos.listar_precos()
if lista:
    st.dataframe(lista, hide_index=True)
else:
    st.info("Nenhum preço cadastrado ainda.")

with st.form("novo_preco", clear_on_submit=True):
    item = st.selectbox("Item", list(precos.ITENS),
                        format_func=lambda i: f'{precos.ITENS[i]["rotulo"]} '
                                              f'(por {precos.ITENS[i]["unidade"]})')
    col1, col2, col3 = st.columns(3)
    valor = col1.number_input("Valor", min_value=0.0, step=0.01, format="%.4f")
    moeda = col2.selectbox("Moeda", precos.MOEDAS,
                           help="A cotação do dólar é sempre gravada em R$.")
    vigente = col3.date_input("Vale a partir de", value=hoje)
    if st.form_submit_button("💾 Cadastrar preço"):
        try:
            precos.cadastrar_preco(item, valor, vigente, moeda)
            n = custos.recalcular_custos()
            avisar(f"Preço cadastrado. {n} execução(ões) recalculada(s).")
            st.rerun()
        except precos.PrecoInvalido as erro:
            for mensagem in erro.erros:
                st.error(mensagem)

col_a, col_b = st.columns(2)
if col_a.button("🔄 Recalcular custos com os preços atuais"):
    n = custos.recalcular_custos()
    avisar(f"{n} execução(ões) recalculada(s).")
    st.rerun()

if lista:
    with col_b.expander("🗑️ Apagar um preço cadastrado errado"):
        escolha = st.selectbox(
            "Preço", lista,
            format_func=lambda p: f'{p["item"]} · {p["valor"]} {p["moeda"]} · desde {p["vigente_desde"]}')
        if st.button("Apagar este preço"):
            precos.apagar_preco(escolha["id"])
            custos.recalcular_custos()
            avisar("Preço apagado e custos recalculados.")
            st.rerun()

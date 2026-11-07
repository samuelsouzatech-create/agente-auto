"""Custos e preços (nível Geral), S8 da Fase 3.

A tela só mostra e chama app/custos_precos.py: nada de conta, SQL ou
conversão de horário aqui. Meses e datas no horário de Brasília.

Decisões do S8 (1A a 5A, aprovadas pelo analista):
- preço e recálculo vão para o Registro, sem loja (valem para todas);
- 12 meses: uma linha por mês, todas as lojas ou uma (uma consulta só);
- implantação numa tabela à parte; a tabela do mês é o custo cheio;
- Recalcular sem caixinha (pode repetir); Apagar preço com caixinha;
- salvar ou apagar preço já recalcula, na mesma transação.
"""
import streamlit as st

from app import custos_precos as cp
from app.precos import MOEDAS, PrecoInvalido
from paginas.comum import avisar, definir_ator_da_sessao, exigir_operador, mostrar_aviso

exigir_operador()

st.title("💰 Custos e preços")
st.caption("Todas as lojas. Meses e datas no horário de Brasília. O lojista não vê esta tela.")
definir_ator_da_sessao()          # quem age nesta execução (o nome vem do .env)
mostrar_aviso()

faltam = cp.precos_faltando()
if faltam:
    st.warning("⚠️ Preço não cadastrado: " + ", ".join(faltam) + ". O consumo já está sendo "
               "medido; o custo aparece quando o preço for cadastrado (lá embaixo).")

# ------------------------------------------------------------ mês por loja
meses = cp.meses_para_escolher()
ano, mes = st.selectbox("Mês", meses, format_func=lambda am: cp.nome_do_mes(*am), key="s8_mes")
nome_mes = cp.nome_do_mes(ano, mes)
st.subheader(f"Custo por loja em {nome_mes}")
st.caption("Custo cheio do mês, o que os fornecedores cobram (inclui o período de teste).")
st.dataframe(cp.linhas_do_mes(cp.custos_do_mes(ano, mes)), hide_index=True)

if st.button("🔄 Recalcular este mês", key="s8_recalcular",
             help="Refaz o custo de cada resposta do mês escolhido com os preços cadastrados. "
                  "Pode repetir: o resultado é sempre o mesmo."):
    n = cp.recalcular_mes(ano, mes)
    avisar(f"Custos de {nome_mes} recalculados: {n} registro(s) atualizado(s).")
    st.rerun()

# ------------------------------------------------------------ 12 meses
st.subheader("Últimos 12 meses")
if st.button("📅 Ver últimos 12 meses", key="s8_12_meses"):
    st.session_state["s8_ver_12"] = True
if st.session_state.get("s8_ver_12"):
    nomes_lojas = dict(cp.opcoes_de_loja())
    loja = st.selectbox("Loja", list(nomes_lojas), format_func=nomes_lojas.get, key="s8_loja_12")
    st.dataframe(cp.linhas_dos_12_meses(cp.ultimos_12_meses(loja)), hide_index=True)

# ------------------------------------------------------------ implantação
st.subheader("Implantação (período de teste)")
st.caption("Quanto custou o teste de cada loja antes de entrar no ar. Já está somado no mês acima.")
implantacao = cp.implantacao_de_todas()
if implantacao:
    st.dataframe(cp.linhas_da_implantacao(implantacao), hide_index=True)
else:
    st.info("Nenhuma loja em implantação.")

# ------------------------------------------------------------ preços
st.divider()
st.subheader("Preços")
st.caption("Copie da página oficial de preços do fornecedor de IA e da tabela oficial da Meta. "
           "Mudou o preço? Cadastre um novo com a data da mudança: o antigo continua valendo "
           "para o passado. Salvar já recalcula os custos a partir da data do preço.")
lista = cp.historico_de_precos()
if lista:
    st.dataframe(cp.linhas_de_precos(lista), hide_index=True)
else:
    st.info("Nenhum preço cadastrado ainda.")

st.markdown("**Novo preço**")
itens = {chave: (texto, moeda) for chave, texto, moeda in cp.itens_de_preco()}
feitos = st.session_state.get("_s8_precos", 0)
item = st.selectbox("Item", list(itens), format_func=lambda c: itens[c][0], key=f"s8_item_{feitos}")
c1, c2, c3 = st.columns(3)
valor = c1.number_input("Valor", min_value=0.0, step=0.01, format="%.4f", key=f"s8_valor_{feitos}")
moeda = c2.selectbox("Moeda", MOEDAS, index=MOEDAS.index(itens[item][1]), key=f"s8_moeda_{feitos}",
                     help="A cotação do dólar é sempre gravada em reais.")
vigente = c3.date_input("Vale a partir de", value=cp.hoje_brasilia(), format="DD/MM/YYYY",
                        key=f"s8_desde_{feitos}")
if st.button("💾 Salvar preço", key="s8_salvar"):
    try:
        r = cp.cadastrar_preco(item, valor, vigente, moeda)
    except PrecoInvalido as erro:
        for mensagem in erro.erros:
            st.error(mensagem)
    except Exception:
        st.error("⚠️ Preço NÃO salvo: os custos não puderam ser recalculados, então nada foi "
                 "alterado. Tente de novo; se repetir, avise.")
    else:
        texto = "Preço corrigido." if r["corrigiu"] else "Preço salvo."
        avisar(f"{texto} {r['recalculados']} registro(s) de custo recalculado(s) "
               f"a partir de {r['vigente_desde']}.")
        st.session_state["_s8_precos"] = feitos + 1
        st.rerun()

if lista:
    with st.expander("🗑️ Apagar um preço cadastrado errado"):
        apagados = st.session_state.get("_s8_apagados", 0)
        rotulos = {p["id"]: cp.rotulo_para_apagar(p) for p in lista}
        qual = st.selectbox("Qual preço", list(rotulos), format_func=rotulos.get,
                            key=f"s8_apagar_qual_{apagados}")
        st.caption("Ao apagar, volta a valer o preço anterior desse item, e os custos são "
                   "recalculados a partir da data dele.")
        certeza = st.checkbox("Confirmo que quero apagar este preço.",
                              key=f"s8_apagar_conf_{apagados}")
        if st.button("Apagar preço", disabled=not certeza, key="s8_apagar") and certeza:
            try:
                r = cp.apagar_preco(qual)
            except Exception:
                st.error("⚠️ Preço NÃO apagado: os custos não puderam ser recalculados, então "
                         "nada foi alterado. Tente de novo; se repetir, avise.")
            else:
                if r["apagado"]:
                    avisar(f"Preço apagado. {r['recalculados']} registro(s) de custo recalculado(s).")
                else:
                    avisar("Esse preço já tinha sido apagado.", "info")
                st.session_state["_s8_apagados"] = apagados + 1
                st.rerun()

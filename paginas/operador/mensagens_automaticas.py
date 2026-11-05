"""Mensagens automáticas (nível Loja), S6 da Fase 3.

Duas abas: "Agora" (por que cada cliente recebe ou não a retomada hoje) e
"No mês" (o que ficou gravado). A tela só mostra: os dados vêm de
app/mensagens_automaticas.py, com a mesma decisão que o robô usa.

D-1 (S6): a tela antiga "Retomadas e pós-venda" (paginas/envios.py) continua
ao lado, porque também aparece no painel da loja. Removê-la ou trocá-la é
item OBRIGATÓRIO do S10.
"""
import streamlit as st

from app import mensagens_automaticas as ma
from app.lojas import carregar_loja
from app.relogio import agora_utc
from paginas.comum import exigir_operador, loja_atual, para_streamlit

exigir_operador()
loja = carregar_loja(loja_atual())
agora = agora_utc()

st.title("📨 Mensagens automáticas")
st.caption(f"{para_streamlit(loja.nome)} · retomadas, pós-venda e reativação: o que sai, o que não "
           "saiu e por quê.")

aba_agora, aba_mes = st.tabs(["Agora", "No mês"])

with aba_agora:
    dados = ma.situacao_agora(loja.id, agora)
    limite = dados["limite"]
    if limite["limite"] is None:
        uso = f'{limite["usados"]} (limite não definido)'
    else:
        uso = f'{limite["usados"]} de {limite["limite"]}'
    c1, c2, c3 = st.columns(3)
    c1.metric("Podem receber a retomada agora", dados["podem_agora"])
    c2.metric("Contatos usados no mês (retomada + reativação)", uso)
    c3.metric("Modo da retomada", dados["modo"])
    st.caption("Retomada: a mesma regra que o robô confere logo antes de enviar. "
               "Pós-venda e reativação: veja o que ficou gravado em “No mês”.")
    if not dados["itens"]:
        st.info("Nenhum cliente conversou com a loja pelo WhatsApp ou Telegram ainda.")
    else:
        st.subheader("Por que não recebe hoje")
        st.dataframe([{"Situação": r["situacao"], "Clientes": r["clientes"]}
                      for r in dados["resumo"]], hide_index=True)
        opcoes = ["Todos"] + [r["situacao"] for r in dados["resumo"]]
        filtro = st.selectbox("Mostrar", opcoes, key="s6_filtro_agora")
        itens = [i for i in dados["itens"] if filtro == "Todos" or i["situacao"] == filtro]
        st.dataframe([{"Cliente": i["cliente"], "Canal": i["canal"], "Situação": i["situacao"],
                       "Próximo contato": i["quando"],
                       "Toque": str(i["toque"]) if i["toque"] else "—"} for i in itens],
                     hide_index=True)

with aba_mes:
    st.caption(ma.AVISO_NO_MES)
    mes = ma.gravado_no_mes(loja.id, agora)
    colunas = st.columns(len(ma.TIPOS))
    for coluna, (tipo, rotulo) in zip(colunas, ma.TIPOS.items()):
        coluna.metric(f"{rotulo} (registros no mês)", mes["totais"][tipo])
    if not mes["linhas"]:
        st.info("Nada gravado neste mês ainda.")
    else:
        st.dataframe([{"Mensagem": l["mensagem"], "Resultado": l["resultado"],
                       "Motivo": l["motivo"] or "—", "Quantas": l["quantidade"]}
                      for l in mes["linhas"]], hide_index=True)

st.caption("Marcar “Não enviar”, desfazer e pausar continuam em “Retomadas e pós-venda”, "
           "no grupo “Antigas (serão removidas)”.")

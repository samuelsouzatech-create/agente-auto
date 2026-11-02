"""Resultado dos leads da loja escolhida (só leitura).

Desde o P2 do Plano Mestre esta tela não marca resultado. A venda é
registrada só em "Registrar venda", na conversa do cliente, que grava a
venda, o resultado, a baixa no estoque e o pós-venda juntos."""
import streamlit as st

from app.lojas import carregar_loja
from app.mensagens import historico_do_lead, listar_leads
from app.resultados import resultado_do_lead
from paginas.comum import loja_atual, para_streamlit

ROTULO = {"compareceu": "🔵 Compareceu", "comprou": "🟢 Comprou", "perdeu": "🔴 Perdeu"}

loja = carregar_loja(loja_atual())
st.title("📊 Resultado dos Leads")
st.caption(f"{loja.nome} · como cada atendimento terminou (só leitura). "
           "Para registrar uma venda, use \"Registrar venda\" na conversa do cliente.")
esconder = st.checkbox("Esconder leads que já têm resultado", value=False)

leads = listar_leads(loja_id=loja.id)
if esconder:
    leads = [l for l in leads if resultado_do_lead(l["lead_id"], loja_id=loja.id) is None]
if not leads:
    st.info("Nenhum lead para mostrar nesta loja.")
    st.stop()

st.write(f"**{len(leads)} lead(s):**")
for lead in leads:
    lead_id = lead["lead_id"]
    atual = resultado_do_lead(lead_id, loja_id=loja.id)
    marca = ROTULO.get(atual["resultado"], atual["resultado"]) if atual else "⚪ Sem resultado"
    with st.expander(f"{marca}  —  Lead: {lead_id}  —  ({lead['total_mensagens']} msgs)"):
        st.caption(f"Última mensagem: {lead.get('ultima_mensagem') or '—'} (UTC)")
        if atual and atual.get("motivo"):
            nome_campo = "Carro" if atual["resultado"] == "comprou" else "Motivo"
            st.markdown(f"**{nome_campo}:** {para_streamlit(atual['motivo'])}")
        if atual and atual.get("vendedor"):
            st.caption(f"Marcado por: {atual['vendedor']} em {atual.get('criado_em') or '—'}")
        st.markdown("---")
        for m in historico_do_lead(lead_id, loja_id=loja.id):
            with st.chat_message("user" if m["direcao"] == "cliente" else "assistant"):
                st.write(para_streamlit(m["conteudo"]))

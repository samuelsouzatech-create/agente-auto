"""Resultado dos leads da loja escolhida: compareceu, comprou ou perdeu."""
import streamlit as st

from app.lojas import carregar_loja
from app.mensagens import historico_do_lead, listar_leads
from app.resultados import OPCOES_RESULTADO, registrar_resultado, resultado_do_lead
from paginas.comum import loja_atual, para_streamlit, usuario_atual

ROTULO = {"compareceu": "🔵 Compareceu", "comprou": "🟢 Comprou", "perdeu": "🔴 Perdeu"}

loja = carregar_loja(loja_atual())
st.title("📊 Resultado dos Leads")
st.caption(f"{loja.nome} · marque como cada atendimento terminou")
esconder = st.checkbox("Esconder leads já marcados", value=False)

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
        col_info, col_marcar = st.columns([2, 1])
        with col_info:
            st.caption(f"Última mensagem: {lead.get('ultima_mensagem') or '—'} (UTC)")
            if atual and atual.get("motivo"):
                st.markdown(f"**Motivo:** {para_streamlit(atual['motivo'])}")
            if atual and atual.get("vendedor"):
                st.caption(f"Marcado por: {atual['vendedor']} em {atual.get('criado_em') or '—'}")
        with col_marcar:
            with st.form(f"res_{loja.id}_{lead_id}"):
                novo = st.selectbox("Resultado", OPCOES_RESULTADO)
                motivo = st.text_input("Motivo")
                if st.form_submit_button("💾 Marcar"):
                    registrar_resultado(lead_id, novo, motivo=motivo.strip(),
                                        vendedor=usuario_atual(), loja_id=loja.id)
                    st.rerun()
        st.markdown("---")
        for m in historico_do_lead(lead_id, loja_id=loja.id):
            with st.chat_message("user" if m["direcao"] == "cliente" else "assistant"):
                st.write(para_streamlit(m["conteudo"]))

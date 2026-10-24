"""
Painel de resultados (Fase 3 - Bloco 6).

Lista os leads que já conversaram com o Léo e deixa o vendedor marcar como
terminou: compareceu, comprou ou perdeu — com motivo. Base pra revisão
semanal (seção 7 do documento).

Puxa os leads da tabela 'mensagens' (todo mundo que conversou), não só os
que passaram por handoff — assim nenhum lead que comprou fica de fora.

Rodar com:  streamlit run painel_resultados.py
"""
import streamlit as st

from app.mensagens import listar_leads, historico_do_lead
from app.resultados import (
    registrar_resultado, resultado_do_lead, OPCOES_RESULTADO,
)


def para_streamlit(texto):
    """Escapa o '$' pra não virar fórmula LaTeX no Streamlit (igual ao app.py)."""
    return (texto or "").replace("$", "\\$")


# Rótulos amigáveis para os resultados já marcados.
ROTULO_RESULTADO = {
    "compareceu": "🔵 Compareceu",
    "comprou": "🟢 Comprou",
    "perdeu": "🔴 Perdeu",
}


st.set_page_config(page_title="Resultados - Léo", page_icon="📊", layout="wide")
st.title("📊 Resultado dos Leads")
st.caption("Marque como cada atendimento terminou — Fase 3 (Bloco 6)")

vendedor = st.sidebar.text_input("Seu nome (vendedor)", value="Vendedor")
st.sidebar.button("🔄 Atualizar lista")
esconder_marcados = st.sidebar.checkbox("Esconder leads já marcados", value=False)

leads = listar_leads()

if not leads:
    st.info("Nenhum lead conversou ainda. Nada pra marcar.")
    st.stop()

# Filtro opcional: esconder quem já tem resultado.
if esconder_marcados:
    leads = [l for l in leads if resultado_do_lead(l["lead_id"]) is None]
    if not leads:
        st.success("Todos os leads já foram marcados. 👍")
        st.stop()

st.write(f"**{len(leads)} lead(s):**")

for lead in leads:
    lead_id = lead["lead_id"]
    atual = resultado_do_lead(lead_id)

    # Monta o título: mostra o resultado atual, se já houver.
    if atual:
        marca = ROTULO_RESULTADO.get(atual["resultado"], atual["resultado"])
        titulo = f"{marca}  —  Lead: {lead_id}  —  ({lead['total_mensagens']} msgs)"
    else:
        titulo = f"⚪ Sem resultado  —  Lead: {lead_id}  —  ({lead['total_mensagens']} msgs)"

    with st.expander(titulo, expanded=False):
        col_info, col_marcar = st.columns([2, 1])

        with col_info:
            st.caption(f"Última mensagem: {lead.get('ultima_mensagem') or '—'} (UTC)")
            if atual:
                st.markdown(
                    f"**Resultado atual:** {ROTULO_RESULTADO.get(atual['resultado'], atual['resultado'])}"
                )
                if atual.get("motivo"):
                    st.markdown(f"**Motivo:** {para_streamlit(atual['motivo'])}")
                if atual.get("vendedor"):
                    st.caption(f"Marcado por: {atual['vendedor']} em {atual.get('criado_em') or '—'}")

        with col_marcar:
            with st.form(f"form_resultado_{lead_id}"):
                novo = st.selectbox("Resultado", OPCOES_RESULTADO, key=f"res_{lead_id}")
                motivo = st.text_input("Motivo", key=f"mot_{lead_id}")
                salvar = st.form_submit_button("💾 Marcar")
                if salvar:
                    registrar_resultado(
                        lead_id, novo, motivo=motivo.strip(), vendedor=vendedor,
                    )
                    st.success(f"Resultado '{novo}' marcado.")
                    st.rerun()

        # Histórico da conversa, pra o vendedor decidir o resultado com contexto.
        st.markdown("---")
        st.markdown("**Conversa:**")
        conversa = historico_do_lead(lead_id)
        if not conversa:
            st.caption("Sem mensagens registradas.")
        else:
            for m in conversa:
                autor = "user" if m["direcao"] == "cliente" else "assistant"
                with st.chat_message(autor):
                    st.write(para_streamlit(m["conteudo"]))

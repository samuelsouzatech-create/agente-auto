"""
Painel do vendedor (Fase 3) — fila de handoffs.

Mostra os leads que precisam de atenção humana, com o histórico da conversa
e botões para o vendedor ASSUMIR (o Léo silencia) e DEVOLVER ao Léo.

Rodar com:  streamlit run painel.py
"""
import streamlit as st

from app.handoff import (
    listar_handoffs, assumir_handoff, devolver_ao_agente,
)
from app.mensagens import historico_do_lead


def para_streamlit(texto):
    """Escapa o '$' pra não virar fórmula LaTeX no Streamlit (igual ao app.py)."""
    return (texto or "").replace("$", "\\$")


# Rótulos amigáveis para os estados do handoff.
ROTULO_ESTADO = {
    "aguardando_humano": "🟡 Aguardando vendedor",
    "humano_assumiu": "🟢 Em atendimento humano",
}


st.set_page_config(page_title="Painel do Vendedor - Léo", page_icon="🧑‍💼", layout="wide")
st.title("🧑‍💼 Painel do Vendedor")
st.caption("Fila de atendimentos que precisam de uma pessoa — Fase 3")

# Nome do vendedor logado (simples, por enquanto; na Fase 1 não havia login).
vendedor = st.sidebar.text_input("Seu nome (vendedor)", value="Vendedor")
st.sidebar.button("🔄 Atualizar fila")  # só clicar já re-roda o script

# Busca os handoffs abertos (aguardando_humano + humano_assumiu).
handoffs = listar_handoffs(apenas_abertos=True)

if not handoffs:
    st.success("Nenhum lead na fila agora. Tudo tranquilo. 👍")
    st.stop()

st.write(f"**{len(handoffs)} lead(s) na fila:**")

for h in handoffs:
    lead_id = h["lead_id"]
    estado = h["estado"]
    rotulo = ROTULO_ESTADO.get(estado, estado)

    # Cada lead em um expander. A key estável (pelo id do handoff) ajuda o
    # Streamlit a não se perder ao redesenhar depois de um clique.
    aberto = estado == "aguardando_humano"
    with st.expander(f"{rotulo}  —  Lead: {lead_id}", expanded=aberto):

        col_info, col_acoes = st.columns([3, 1])

        with col_info:
            st.markdown(f"**Motivo:** {para_streamlit(h.get('motivo') or '—')}")
            st.markdown(f"**Resumo:** {para_streamlit(h.get('resumo') or '—')}")
            if h.get("vendedor"):
                st.markdown(f"**Assumido por:** {para_streamlit(h['vendedor'])}")
            st.caption(f"Aberto em: {h.get('criado_em') or '—'}")

        with col_acoes:
            # Os botões NÃO chamam st.rerun(): o clique já re-roda o script
            # sozinho, e o banco é lido de novo no topo, refletindo o novo estado.
            if estado == "aguardando_humano":
                if st.button("✋ Assumir", key=f"assumir_{h['id']}"):
                    assumir_handoff(lead_id, vendedor=vendedor)
                    st.rerun()
            elif estado == "humano_assumiu":
                if st.button("↩️ Devolver ao Léo", key=f"devolver_{h['id']}"):
                    devolver_ao_agente(lead_id)
                    st.rerun()

        # Histórico da conversa (salvo na tabela mensagens).
        st.markdown("---")
        st.markdown("**Conversa:**")
        conversa = historico_do_lead(lead_id)
        if not conversa:
            st.caption("Sem mensagens registradas para este lead ainda.")
        else:
            for m in conversa:
                autor = "user" if m["direcao"] == "cliente" else "assistant"
                with st.chat_message(autor):
                    st.write(para_streamlit(m["conteudo"]))

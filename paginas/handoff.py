"""Fila de handoff da loja escolhida. As cores vêm da configuração da loja."""
from datetime import datetime, timezone

import streamlit as st

from app.handoff import assumir_handoff, devolver_ao_agente, listar_handoffs
from app.lojas import carregar_loja
from app.mensagens import historico_do_lead
from paginas.comum import loja_atual, para_streamlit, usuario_atual

INTERVALO_REFRESH = "30s"

loja = carregar_loja(loja_atual())
MIN_AMARELO = loja.get("handoff.reaviso_min", 5)
MIN_VERMELHO = loja.get("handoff.gestor_min", 10)


def _minutos_esperando(criado_em):
    """O SQLite grava CURRENT_TIMESTAMP em UTC; comparamos com o agora em UTC."""
    if not criado_em:
        return 0.0
    try:
        marcado = datetime.strptime(str(criado_em), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - marcado).total_seconds() / 60.0)
    except (ValueError, TypeError):
        return 0.0


def _texto_espera(minutos):
    if minutos < 1:
        return "esperando há menos de 1 min"
    if minutos < 60:
        return f"esperando há {int(minutos)} min"
    return f"esperando há {int(minutos // 60)}h{int(minutos % 60):02d}min"


def _emoji(minutos):
    if minutos >= MIN_VERMELHO:
        return "🔴"
    if minutos >= MIN_AMARELO:
        return "🟡"
    return "🟢"


st.title("🧑‍💼 Fila de handoff")
st.caption(f"{loja.nome} · 🟡 a partir de {MIN_AMARELO} min · 🔴 a partir de {MIN_VERMELHO} min "
           f"(ajuste em Configuração > Handoff) · atualiza sozinha a cada {INTERVALO_REFRESH}")
st.button("🔄 Atualizar agora")


@st.fragment(run_every=INTERVALO_REFRESH)
def mostrar_fila(loja_id, vendedor):
    handoffs = listar_handoffs(loja_id=loja_id, apenas_abertos=True)
    if not handoffs:
        st.success("Nenhum lead na fila agora. Tudo tranquilo. 👍")
        return

    atrasados = [h for h in handoffs if h["estado"] == "aguardando_humano"
                 and _minutos_esperando(h.get("criado_em")) >= MIN_VERMELHO]
    resumo = f"**{len(handoffs)} lead(s) na fila.**"
    if atrasados:
        resumo += f"  🔴 **{len(atrasados)} atrasado(s) (+{MIN_VERMELHO} min)!**"
    st.write(resumo)

    for h in handoffs:
        lead_id, estado = h["lead_id"], h["estado"]
        minutos = _minutos_esperando(h.get("criado_em"))
        if estado == "aguardando_humano":
            titulo = f"{_emoji(minutos)} Aguardando vendedor  —  Lead: {lead_id}  —  {_texto_espera(minutos)}"
            expandir = minutos >= MIN_AMARELO
        else:
            titulo = f"🟢 Em atendimento humano  —  Lead: {lead_id}"
            expandir = False

        with st.expander(titulo, expanded=expandir):
            col_info, col_acoes = st.columns([3, 1])
            with col_info:
                st.markdown(f"**Motivo:** {para_streamlit(h.get('motivo') or '—')}")
                st.markdown(f"**Resumo:** {para_streamlit(h.get('resumo') or '—')}")
                if h.get("vendedor"):
                    st.markdown(f"**Assumido por:** {para_streamlit(h['vendedor'])}")
                st.caption(f"Aberto em: {h.get('criado_em') or '—'} (UTC)")
            with col_acoes:
                if estado == "aguardando_humano":
                    if st.button("✋ Assumir", key=f"assumir_{h['id']}"):
                        assumir_handoff(lead_id, vendedor=vendedor, loja_id=loja_id)
                        st.rerun()
                elif estado == "humano_assumiu":
                    if st.button("↩️ Devolver ao Léo", key=f"devolver_{h['id']}"):
                        devolver_ao_agente(lead_id, loja_id=loja_id)
                        st.rerun()

            st.markdown("---")
            st.markdown("**Conversa:**")
            conversa = historico_do_lead(lead_id, loja_id=loja_id)
            if not conversa:
                st.caption("Sem mensagens registradas para este lead ainda.")
            for m in conversa:
                with st.chat_message("user" if m["direcao"] == "cliente" else "assistant"):
                    st.write(para_streamlit(m["conteudo"]))


mostrar_fila(loja.id, usuario_atual())

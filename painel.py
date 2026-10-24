"""
Painel do vendedor (Fase 3) — fila de handoffs.

Mostra os leads que precisam de atenção humana, com o histórico da conversa
e botões para o vendedor ASSUMIR (o Léo silencia) e DEVOLVER ao Léo.

A fila é ESCALONADA por tempo de espera (Abordagem A):
  - normal   : esperando há menos de 5 min
  - 🟡 amarelo: esperando há 5 min ou mais
  - 🔴 vermelho: esperando há 10 min ou mais
O relógio de espera vale só enquanto o lead está "aguardando_humano";
depois que um vendedor assume, mostramos "em atendimento" (verde) sem timer.

A fila se atualiza sozinha a cada 30 s (auto-refresh via st.fragment),
pra o tempo de espera subir e a cor mudar sem você clicar em nada.

Rodar com:  streamlit run painel.py
"""
from datetime import datetime, timezone

import streamlit as st

from app.handoff import (
    listar_handoffs, assumir_handoff, devolver_ao_agente,
)
from app.mensagens import historico_do_lead


# Limiares de escalonamento (em minutos). Combinados com o Samuel.
MIN_AMARELO = 5
MIN_VERMELHO = 10

# De quanto em quanto tempo a fila se atualiza sozinha.
INTERVALO_REFRESH = "30s"


def para_streamlit(texto):
    """Escapa o '$' pra não virar fórmula LaTeX no Streamlit (igual ao app.py)."""
    return (texto or "").replace("$", "\\$")


def _minutos_esperando(criado_em):
    """Quantos minutos (float) se passaram desde criado_em.

    O SQLite grava CURRENT_TIMESTAMP em UTC, no formato 'YYYY-MM-DD HH:MM:SS'.
    Comparamos com o agora TAMBÉM em UTC pra não dar diferença de fuso.
    Se não der pra ler a data, devolve 0 (trata como recém-chegado).
    """
    if not criado_em:
        return 0.0
    try:
        marcado = datetime.strptime(str(criado_em), "%Y-%m-%d %H:%M:%S")
        marcado = marcado.replace(tzinfo=timezone.utc)
        agora = datetime.now(timezone.utc)
        delta = (agora - marcado).total_seconds() / 60.0
        return max(0.0, delta)
    except (ValueError, TypeError):
        return 0.0


def _texto_espera(minutos):
    """Formata 'esperando há X' de forma amigável."""
    if minutos < 1:
        return "esperando há menos de 1 min"
    if minutos < 60:
        return f"esperando há {int(minutos)} min"
    horas = int(minutos // 60)
    resto = int(minutos % 60)
    return f"esperando há {horas}h{resto:02d}min"


def _nivel_espera(minutos):
    """Devolve (emoji, rótulo curto) conforme o tempo de espera."""
    if minutos >= MIN_VERMELHO:
        return "🔴", "ATRASADO"
    if minutos >= MIN_AMARELO:
        return "🟡", "esperando"
    return "🟢", "novo"


st.set_page_config(page_title="Painel do Vendedor - Léo", page_icon="🧑‍💼", layout="wide")
st.title("🧑‍💼 Painel do Vendedor")
st.caption("Fila de atendimentos que precisam de uma pessoa — Fase 3")

# Nome do vendedor logado (simples, por enquanto; na Fase 1 não havia login).
vendedor = st.sidebar.text_input("Seu nome (vendedor)", value="Vendedor")
st.sidebar.button("🔄 Atualizar agora")  # refresh manual, além do automático
st.sidebar.caption(
    f"Alerta: 🟡 a partir de {MIN_AMARELO} min · 🔴 a partir de {MIN_VERMELHO} min"
)
st.sidebar.caption(f"Atualiza sozinho a cada {INTERVALO_REFRESH}.")


@st.fragment(run_every=INTERVALO_REFRESH)
def mostrar_fila(vendedor):
    """Desenha a fila de handoffs. Roda sozinha a cada INTERVALO_REFRESH,
    sem recarregar a página inteira (os widgets de fora não piscam)."""

    # Busca os handoffs abertos (aguardando_humano + humano_assumiu),
    # já ordenados por criado_em ASC (mais antigo primeiro) pelo app/handoff.py.
    handoffs = listar_handoffs(apenas_abertos=True)

    if not handoffs:
        st.success("Nenhum lead na fila agora. Tudo tranquilo. 👍")
        return

    # Conta quantos estão atrasados pra um resumo no topo.
    aguardando = [h for h in handoffs if h["estado"] == "aguardando_humano"]
    atrasados = [
        h for h in aguardando
        if _minutos_esperando(h.get("criado_em")) >= MIN_VERMELHO
    ]

    linha_resumo = f"**{len(handoffs)} lead(s) na fila.**"
    if atrasados:
        linha_resumo += f"  🔴 **{len(atrasados)} atrasado(s) (+{MIN_VERMELHO} min)!**"
    st.write(linha_resumo)

    for h in handoffs:
        lead_id = h["lead_id"]
        estado = h["estado"]

        if estado == "aguardando_humano":
            minutos = _minutos_esperando(h.get("criado_em"))
            emoji, _ = _nivel_espera(minutos)
            espera = _texto_espera(minutos)
            titulo = f"{emoji} Aguardando vendedor  —  Lead: {lead_id}  —  {espera}"
            expandir = minutos >= MIN_AMARELO  # abre sozinho quem já está esperando
        elif estado == "humano_assumiu":
            titulo = f"🟢 Em atendimento humano  —  Lead: {lead_id}"
            expandir = False
        else:
            titulo = f"{estado}  —  Lead: {lead_id}"
            expandir = False

        # Cada lead em um expander. A key estável (pelo id do handoff) ajuda o
        # Streamlit a não se perder ao redesenhar depois de um clique.
        with st.expander(titulo, expanded=expandir):

            col_info, col_acoes = st.columns([3, 1])

            with col_info:
                st.markdown(f"**Motivo:** {para_streamlit(h.get('motivo') or '—')}")
                st.markdown(f"**Resumo:** {para_streamlit(h.get('resumo') or '—')}")
                if estado == "aguardando_humano":
                    minutos = _minutos_esperando(h.get("criado_em"))
                    if minutos >= MIN_VERMELHO:
                        st.error(f"🔴 {_texto_espera(minutos)} — atrasado!")
                    elif minutos >= MIN_AMARELO:
                        st.warning(f"🟡 {_texto_espera(minutos)}")
                    else:
                        st.caption(f"🟢 {_texto_espera(minutos)}")
                if h.get("vendedor"):
                    st.markdown(f"**Assumido por:** {para_streamlit(h['vendedor'])}")
                st.caption(f"Aberto em: {h.get('criado_em') or '—'} (UTC)")

            with col_acoes:
                # Os botões chamam st.rerun() pra refletir o novo estado na hora.
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


mostrar_fila(vendedor)

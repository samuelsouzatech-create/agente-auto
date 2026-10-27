"""Conversas da loja (Bloco 7A): acompanhar, assumir a QUALQUER momento,
responder pelo mesmo número e devolver ao assistente. O cliente não recebe
nenhum aviso de troca."""
import streamlit as st

from app.envio_painel import CANAIS_COM_ENVIO, EnvioRecusado, enviar_pelo_painel
from app.handoff import assumir_conversa, devolver_ao_agente, estado_do_handoff, quem_assumiu
from app.interesse import ROTULOS, reativar_contato, situacao_do_lead
from app.lojas import carregar_loja
from app.mensagens import historico_do_lead, listar_conversas
from paginas.comum import avisar, loja_atual, mostrar_aviso, para_streamlit, usuario_atual

INTERVALO_REFRESH = "10s"

loja = carregar_loja(loja_atual())
agente = loja.get("nome_agente", "Léo")
vendedor = usuario_atual()
ESTADOS = {
    "ativo": f"🤖 {agente} atendendo",
    "aguardando_humano": "🟡 Esperando vendedor",
    "humano_assumiu": "🧑 Com vendedor",
}


@st.fragment(run_every=INTERVALO_REFRESH)
def mostrar_historico(lead_id, loja_id):
    for m in historico_do_lead(lead_id, loja_id=loja_id):
        texto = para_streamlit(m["conteudo"])
        if m["direcao"] == "cliente":
            with st.chat_message("user"):
                st.write(texto)
        elif m["direcao"] == "vendedor":
            with st.chat_message("vendedor", avatar="🧑"):
                st.caption(m.get("autor") or "Vendedor")
                st.write(texto)
        else:
            with st.chat_message("assistant", avatar="🤖"):
                st.write(texto)


st.title("💬 Conversas")
st.caption(f"{loja.nome} · você está como **{para_streamlit(vendedor)}** (troque na barra lateral). "
           f"Assumir deixa o {agente} em silêncio, e o cliente não recebe aviso de troca.")
mostrar_aviso()

conversas = listar_conversas(loja.id)
if not conversas:
    st.info("Nenhuma conversa nesta loja ainda.")
    st.stop()

por_lead = {c["lead_id"]: c for c in conversas}


def _rotulo(lead_id):
    c = por_lead[lead_id]
    estado = estado_do_handoff(lead_id, loja.id)
    return (f"{ESTADOS.get(estado, estado)} · {lead_id} · {c.get('canal') or '—'} · "
            f"última: {c['ultima_mensagem']} (UTC)")


lead_id = st.selectbox("Conversa", list(por_lead), format_func=_rotulo, key=f"conversa_{loja.id}")
canal = por_lead[lead_id].get("canal") or ""
estado = estado_do_handoff(lead_id, loja.id)
dono = quem_assumiu(lead_id, loja.id)

col_conversa, col_acoes = st.columns([3, 1])

with col_acoes:
    st.markdown(f"**{ESTADOS.get(estado, estado)}**")
    if estado == "humano_assumiu":
        st.caption(f"Com {dono or 'um vendedor'}")
        if st.button(f"↩️ Devolver ao {agente}"):
            avisar(devolver_ao_agente(lead_id, loja_id=loja.id))
            st.rerun()
    elif st.button("✋ Assumir conversa", type="primary"):
        avisar(assumir_conversa(lead_id, vendedor, loja_id=loja.id))
        st.rerun()

    situacao = situacao_do_lead(loja.id, lead_id)
    if situacao:
        st.markdown("---")
        texto = ROTULOS.get(situacao["situacao"], situacao["situacao"])
        if situacao.get("retomar_em"):
            texto += f" · procurar a partir de {situacao['retomar_em']}"
        st.caption(f"Percebido na conversa: {texto}")
        if situacao.get("motivo"):
            st.caption(f"Motivo: {para_streamlit(situacao['motivo'])}")
        if st.button("🔓 Reativar contato",
                     help="Use se o cliente pediu pessoalmente para voltar a ser procurado."):
            reativar_contato(loja.id, lead_id)
            avisar("Contato reativado: a loja volta a poder procurar este cliente.")
            st.rerun()

with col_conversa:
    mostrar_historico(lead_id, loja.id)

if estado == "humano_assumiu" and dono == vendedor and canal in CANAIS_COM_ENVIO:
    texto = st.chat_input(f"Escreva para o cliente (sai pelo {canal} da loja)")
    if texto:
        try:
            enviar_pelo_painel(loja.id, canal, lead_id, texto, vendedor)
        except EnvioRecusado as erro:
            avisar(str(erro), "error")
        st.rerun()
elif estado == "humano_assumiu" and dono != vendedor:
    st.info(f"Esta conversa está com {dono}. Só quem assumiu responde por aqui.")
elif estado == "humano_assumiu":
    st.caption("O simulador não recebe mensagens do painel. Para testar a resposta, use o Telegram.")
else:
    st.caption(f"Para escrever ao cliente, assuma a conversa. O {agente} fica em silêncio enquanto isso.")

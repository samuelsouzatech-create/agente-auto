"""Retomadas e pós-venda (Etapa 2, Bloco 7): controles, fila, histórico e resultado do mês.
Aparece nos DOIS painéis. Pausar e retomar: dono da loja e operador."""
import streamlit as st

from app import painel_envios as pe
from app import pausa
from app.lojas import carregar_loja, modulo_ativo
from app.relogio import agora_utc, do_banco, hora_local
from paginas.comum import (
    avisar, formatar_brl, loja_atual, mostrar_aviso, papel_atual, para_streamlit, usuario_atual,
)

loja = carregar_loja(loja_atual())
agora = agora_utc()


def _hora(dt):
    return hora_local(loja, dt).strftime("%d/%m/%Y %H:%M") if dt else ""


st.title("📣 Retomadas e pós-venda")
st.caption(f"{loja.nome} · mensagens que a loja manda por iniciativa própria. "
           "Quem escreve para a loja continua sendo atendido normalmente.")
mostrar_aviso()

# ------------------------------------------------------------ controles
sit = pausa.situacao(loja.id)
if sit["pausado"]:
    quem = f"{sit['usuario']} ({pausa.ROTULOS_PAPEL.get(sit['papel'], sit['papel'])})"
    st.error(para_streamlit(
        f"⏸️ Envios PAUSADOS por {quem} em {_hora(sit['em'])}"
        + (f" — {sit['motivo']}" if sit["motivo"] else "")
        + ". Nenhuma retomada, pós-venda ou reativação sai até alguém retomar. "
          "O assistente continua respondendo quem escrever."))
    if st.button("▶️ Retomar os envios", type="primary"):
        try:
            r = pausa.retomar(loja.id, usuario=usuario_atual(), papel=papel_atual())
        except pausa.PausaInvalida as erro:
            avisar(str(erro), "error")
        else:
            extra = (f" {r['cancelados']} passo(s) de pós-venda que venceram durante a pausa "
                     "foram cancelados.") if r["cancelados"] else ""
            avisar("Envios retomados." + extra)
        st.rerun()
else:
    with st.form("form_pausar"):
        motivo = st.text_input("Motivo (opcional)", placeholder="Ex.: mensagem com erro, estoque mudou")
        pausar = st.form_submit_button("⏸️ Pausar todos os envios")
    if pausar:
        try:
            pausa.pausar(loja.id, usuario=usuario_atual(), papel=papel_atual(), motivo=motivo)
        except pausa.PausaInvalida as erro:
            avisar(str(erro), "error")
        else:
            avisar("Envios pausados. O atendimento de quem escreve continua normal.", "warning")
        st.rerun()

modo = pe.modo_de_envio()
uso = pe.uso_do_limite(loja.id, agora)
c1, c2, c3, c4 = st.columns(4)
for coluna, tipo, modulo in ((c1, "remarketing", "remarketing"), (c2, "pos_venda", "pos_venda"),
                             (c3, "reativacao", "remarketing")):
    ligado = modulo_ativo(loja, modulo)
    coluna.metric(pe.TIPOS[tipo], ("Real" if modo[tipo] else "Simulação") if ligado else "Desligado")
c4.metric("Limite do mês (retomada + reativação)",
          f"{uso['usados']} de {uso['limite']}" if uso["limite"] is not None else "não definido")
st.caption("Simulação: o sistema faz tudo, menos enviar. Ligar módulos e limite fica com o operador.")

# ------------------------------------------------------------ resultado do mês
st.divider()
st.subheader("Resultado do mês")
res = pe.resultado_do_mes(loja.id, agora)
t = res["total"]
m1, m2, m3, m4 = st.columns(4)
m1.metric("Enviadas", t["enviados"])
m2.metric("Responderam", t["responderam"])
m3.metric("Agendaram visita", t["agendaram"])
m4.metric("Custo das mensagens (Meta)", formatar_brl(t["custo"]))
st.dataframe([{
    "Tipo": pe.TIPOS[tipo], "Enviadas": res[tipo]["enviados"],
    "Responderam": res[tipo]["responderam"], "Agendaram": res[tipo]["agendaram"],
    "Custo (Meta)": formatar_brl(res[tipo]["custo"]),
} for tipo in pe.TIPOS], hide_index=True)

# ------------------------------------------------------------ fila
st.divider()
st.subheader("Fila: quem será procurado")
itens = pe.fila(loja.id, agora)
if not itens:
    st.info("Ninguém na fila agora.")
else:
    st.dataframe([{
        "Quando": _hora(i["quando"]) or "na próxima rodada",
        "Tipo": pe.TIPOS[i["tipo"]], "Cliente": i["lead_id"],
        "Situação": i["situacao"], "Detalhe": i["detalhe"],
    } for i in itens], hide_index=True)

# ------------------------------------------------------------ histórico
st.divider()
st.subheader("Histórico")
hist = pe.historico(loja.id, 100)
if not hist:
    st.info("Nada enviado ainda.")
else:
    st.dataframe([{
        "Quando": _hora(h["quando"]), "Tipo": pe.TIPOS[h["tipo"]], "Cliente": h["lead_id"],
        "Situação": pe.ROTULOS_ESTADO.get(h["estado"], h["estado"]),
        "Motivo": h["motivo"], "Detalhe": h["detalhe"], "Mensagem": h["texto"],
    } for h in hist], hide_index=True)

pausas = pausa.historico(loja.id)
if pausas:
    with st.expander("Quem pausou e retomou"):
        st.dataframe([{
            "Quando": _hora(do_banco(p["criado_em"])),
            "Ação": "Pausou" if p["acao"] == "pausar" else "Retomou",
            "Quem": p["usuario"], "Papel": pausa.ROTULOS_PAPEL.get(p["papel"], p["papel"]),
            "Motivo": p["motivo"] or "",
        } for p in pausas], hide_index=True)

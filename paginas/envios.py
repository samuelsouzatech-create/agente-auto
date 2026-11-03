"""Retomadas e pós-venda (Etapa 2, Bloco 7; P5): controles, fila, histórico e resultado do mês.
Aparece nos DOIS painéis. Pausar e retomar: dono da loja e operador.
P5: "Não enviar", "Não procurar mais" e "Desfazer" (a regra fica em app/bloqueios.py)."""
import streamlit as st

from app import bloqueios
from app import painel_envios as pe
from app import pausa
from app.apresentacao import horario_para_tela, nomes_dos_clientes
from app.lojas import carregar_loja, modulo_ativo
from app.relogio import agora_utc
from paginas.comum import (
    avisar, formatar_brl, loja_atual, mostrar_aviso, papel_atual, para_streamlit, usuario_atual,
)

loja = carregar_loja(loja_atual())
agora = agora_utc()


def _hora(dt):
    return horario_para_tela(loja, dt) if dt else ""


st.title("📣 Retomadas e pós-venda")
st.caption(f"{loja.nome} · mensagens que a loja manda por iniciativa própria. "
           "Quem escreve para a loja continua sendo atendido normalmente.")
mostrar_aviso()

# ------------------------------------------------------------ controles
sit = pausa.situacao(loja.id)
if sit["pausado"]:
    quem = f"{sit['usuario']} ({pausa.ROTULOS_PAPEL.get(sit['papel'], sit['papel'])})"
    st.error(para_streamlit(
        f"⏸️ Envios PAUSADOS por {quem} · {_hora(sit['em'])}"
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

modos = pe.situacao_do_modo(loja)
uso = pe.uso_do_limite(loja.id, agora)
c1, c2, c3, c4 = st.columns(4)
for coluna, tipo, modulo in ((c1, "remarketing", "remarketing"), (c2, "pos_venda", "pos_venda"),
                             (c3, "reativacao", "remarketing")):
    ligado = modulo_ativo(loja, modulo)
    coluna.metric(pe.TIPOS[tipo], pe.ROTULOS_MODO[modos[tipo]] if ligado else "Desligado")
c4.metric("Limite do mês (retomada + reativação)",
          f"{uso['usados']} de {uso['limite']}" if uso["limite"] is not None else "não definido")
st.caption("Simulação: o sistema faz tudo, menos enviar. Envio real precisa de duas chaves: "
           "a geral do servidor e a da loja (Plano e limites > Envios). "
           "Módulos, limite e modo de envio ficam com o operador.")

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
    nomes_fila = nomes_dos_clientes(loja.id, [i["lead_id"] for i in itens])

    def _situacao(i):
        b = i.get("bloqueio")
        if not b:
            return i["situacao"]
        return f"Não será enviada · marcado por {b['criado_por']} em {_hora(b['criado_em'])}"

    st.dataframe([{
        "Quando": "—" if i.get("bloqueio") else (_hora(i["quando"]) or "na próxima rodada"),
        "Tipo": pe.TIPOS[i["tipo"]], "Cliente": nomes_fila.get(str(i["lead_id"]), "—"),
        "Situação": _situacao(i), "Detalhe": i["detalhe"],
    } for i in itens], hide_index=True)

    def _rotulo_linha(n):
        i = itens[n]
        partes = [nomes_fila.get(str(i["lead_id"]), "—"), pe.TIPOS[i["tipo"]]]
        if i["detalhe"]:
            partes.append(i["detalhe"])
        return " · ".join(partes)

    with st.expander("🚫 Não enviar uma mensagem ou não procurar mais um cliente"):
        escolha = st.selectbox("Escolha a linha da fila", range(len(itens)),
                               format_func=_rotulo_linha, key="linha_bloqueio")
        item = itens[escolha]
        b1, b2 = st.columns(2)
        nao_enviar = b1.button("🚫 Não enviar esta mensagem")
        nao_procurar = b2.button("⛔ Não procurar mais este cliente")
        st.caption("Vale só para as mensagens que a loja manda por iniciativa própria. "
                   "Se o cliente escrever, o assistente atende normalmente. Dá para desfazer.")
        if nao_enviar or nao_procurar:
            try:
                if nao_enviar:
                    bloqueios.bloquear(loja.id, item["lead_id"], item["tipo"], item["passo"],
                                       usuario_atual())
                else:
                    bloqueios.bloquear(loja.id, item["lead_id"], "todos", None, usuario_atual())
            except bloqueios.BloqueioInvalido as erro:
                avisar(str(erro), "error")
            else:
                avisar("Marcado. Essa mensagem não sai até alguém desfazer." if nao_enviar
                       else "Marcado. A loja não procura mais este cliente até alguém desfazer.")
            st.rerun()

ativos = bloqueios.listar_ativos(loja.id)
if ativos:
    with st.expander(f"Marcados para não enviar ({len(ativos)})"):
        nomes_b = nomes_dos_clientes(loja.id, [b["lead_id"] for b in ativos])
        st.dataframe([{
            "Cliente": nomes_b.get(str(b["lead_id"]), "—"),
            "O que": bloqueios.descricao(b),
            "Quem marcou": b["criado_por"], "Quando": _hora(b["criado_em"]),
        } for b in ativos], hide_index=True)

        def _rotulo_bloqueio(n):
            b = ativos[n]
            return f"{nomes_b.get(str(b['lead_id']), '—')} · {bloqueios.descricao(b)}"

        qual = st.selectbox("Desfazer qual?", range(len(ativos)),
                            format_func=_rotulo_bloqueio, key="desfazer_bloqueio")
        if st.button("↩️ Desfazer"):
            if bloqueios.desfazer(loja.id, ativos[qual]["id"], usuario_atual()):
                avisar("Desfeito. Se ainda valer, a mensagem sai na próxima rodada.")
            else:
                avisar("Isso já tinha sido desfeito.", "warning")
            st.rerun()

# ------------------------------------------------------------ histórico
st.divider()
st.subheader("Histórico")
hist = pe.historico(loja.id, 100)
if not hist:
    st.info("Nada enviado ainda.")
else:
    nomes_hist = nomes_dos_clientes(loja.id, [h["lead_id"] for h in hist])
    st.dataframe([{
        "Quando": _hora(h["quando"]), "Tipo": pe.TIPOS[h["tipo"]],
        "Cliente": nomes_hist.get(str(h["lead_id"]), "—"),
        "Situação": pe.ROTULOS_ESTADO.get(h["estado"], h["estado"]),
        "Motivo": h["motivo"], "Detalhe": h["detalhe"], "Mensagem": h["texto"],
    } for h in hist], hide_index=True)

pausas = pausa.historico(loja.id)
if pausas:
    with st.expander("Quem pausou e retomou"):
        st.dataframe([{
            "Quando": horario_para_tela(loja, p["criado_em"]),
            "Ação": "Pausou" if p["acao"] == "pausar" else "Retomou",
            "Quem": p["usuario"], "Papel": pausa.ROTULOS_PAPEL.get(p["papel"], p["papel"]),
            "Motivo": p["motivo"] or "",
        } for p in pausas], hide_index=True)

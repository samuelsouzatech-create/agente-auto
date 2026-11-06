"""Mensagens automáticas (nível Loja), S6 e S10a da Fase 3.

Abas:
  Agora                  por que cada cliente recebe ou não a retomada hoje (S6);
  No mês                 o que ficou gravado (S6);
  Resultado e histórico  resultado do mês e o que saiu (S10a: vinha da tela
                         antiga "Retomadas e pós-venda");
  Base da loja           pós-venda da base e reativação de contatos antigos
                         (S10a: vinha da tela antiga "Importar base");
  Regras                 envio de verdade, retomadas e pós-venda (S10a: vinha
                         das telas antigas "Configuração" e "Plano e limites").
Pausar, "Não enviar", "Não procurar mais" e Desfazer ficam em "Ver como a
loja", aba Acompanhamento.

A tela só mostra e chama app/. O salvar das regras é o salvar_config (dono,
validação e proteção de versão).
"""
import streamlit as st

from app import base_pos_venda, pausa, reativacao
from app import mensagens_automaticas as ma
from app import painel_envios as pe
from app.apresentacao import horario_para_tela, nomes_dos_clientes
from app.config_tela import REGRAS_DAS_MENSAGENS, campos_das_regras
from app.lojas import carregar_loja
from app.permissoes import AcaoNaoPermitida
from app.relogio import agora_utc
from app.telefone import formatar_telefone_br
from paginas.comum import (
    avisar, definir_ator_da_sessao, exigir_operador, formatar_brl, loja_atual, mostrar_aviso,
    papel_atual, para_streamlit, usuario_atual,
)
from paginas.form_config import mostrar_campos

exigir_operador()
loja = carregar_loja(loja_atual())
agora = agora_utc()

st.title("📨 Mensagens automáticas")
st.caption(f"{para_streamlit(loja.nome)} · retomadas, pós-venda e reativação: o que sai, o que não "
           "saiu e por quê.")
definir_ator_da_sessao()          # quem age nesta execução (o nome vem do .env)
mostrar_aviso()


def _hora(dt):
    return horario_para_tela(loja, dt) if dt else ""


aba_agora, aba_mes, aba_resultado, aba_base, aba_regras = st.tabs(
    ["Agora", "No mês", "Resultado e histórico", "Base da loja", "Regras"])

# ------------------------------------------------------------ Agora (S6)
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

# ------------------------------------------------------------ No mês (S6)
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

# ------------------------------------------------------------ Resultado e histórico (S10a)
with aba_resultado:
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

    st.subheader("O que saiu")
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

# ------------------------------------------------------------ Base da loja (S10a)
with aba_base:
    st.caption("Clientes que vieram da planilha da loja (tela Base de clientes).")
    st.subheader("Pós-venda da base")
    pv = base_pos_venda.resumo(loja.id)
    p1, p2 = st.columns(2)
    p1.metric("Compras prontas para agendar", pv["pendentes"])
    p2.metric("Passos agendados da base", pv["agendados"])
    st.info("Só entram compras de contatos COM autorização. Passos cuja data já passou não saem. "
            "Pelo WhatsApp, o primeiro contato só sai por modelo aprovado pela Meta.")
    if st.button("Agendar pós-venda da base", disabled=not pv["pendentes"],
                 key="s10_agendar_base"):
        try:
            r = base_pos_venda.agendar_base(loja.id)
        except (base_pos_venda.BaseNaoAgendada, AcaoNaoPermitida) as erro:
            avisar(str(erro), "error")
        else:
            avisar(f"{r['compras']} compra(s): {r['agendados']} passo(s) agendado(s), "
                   f"{r['ja_passaram']} já tinham passado.")
        st.rerun()

    st.divider()
    st.subheader("Reativar contatos antigos")
    st.caption("Uma mensagem só, por modelo aprovado pela Meta, para quem autorizou e está parado "
               "há meses. Conta no mesmo limite mensal da retomada. Quem responder segue com o "
               "assistente normalmente.")
    rr = reativacao.resumo(loja.id)
    na_fila = rr["na_fila"] + rr["simulado"] + rr["falhou"]
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Na fila", na_fila)
    r2.metric("Enviados", rr["enviado"])
    r3.metric("Bloqueados", rr["bloqueado"])
    r4.metric("Cancelados", rr["cancelado"])

    with st.form(f"s10_reativacao_{loja.id}"):
        f1, f2, f3 = st.columns(3)
        meses = f1.selectbox("Parado há pelo menos", reativacao.OPCOES_MESES,
                             index=reativacao.OPCOES_MESES.index(reativacao.MESES_PADRAO),
                             format_func=lambda m: f"{m} meses", key="s10_reat_meses")
        publico = f2.selectbox("Quem", list(reativacao.PUBLICOS),
                               format_func=reativacao.PUBLICOS.get, key="s10_reat_publico")
        maximo = f3.number_input("Máximo de contatos", min_value=1,
                                 max_value=reativacao.MAX_POR_LOTE, value=50, step=10,
                                 key="s10_reat_maximo")
        montar = st.form_submit_button("Montar fila de reativação")
    if montar:
        try:
            r = reativacao.montar_fila(loja.id, meses=int(meses), publico=publico,
                                       maximo=int(maximo), usuario=usuario_atual())
        except (reativacao.ReativacaoInvalida, AcaoNaoPermitida) as erro:
            avisar(str(erro), "error")
        else:
            fora = ", ".join(f"{reativacao.MOTIVOS.get(k, k)}: {v}"
                             for k, v in r["ignorados"].items())
            avisar(f"{r['na_fila']} contato(s) na fila."
                   + (f" Ficaram de fora - {fora}." if fora else ""))
        st.rerun()

    if na_fila and st.button("Cancelar a fila de reativação", key="s10_cancelar_fila"):
        try:
            n = reativacao.cancelar_fila(loja.id)
        except AcaoNaoPermitida as erro:
            avisar(str(erro), "error")
        else:
            avisar(f"{n} contato(s) tirados da fila.")
        st.rerun()

    ultimos = reativacao.listar(loja.id)
    if ultimos:
        with st.expander(f"Últimos {len(ultimos)} da reativação"):
            st.dataframe([{
                "Telefone": formatar_telefone_br(l["telefone"]) or l["telefone"],
                "Situação": reativacao.ROTULOS_ESTADO.get(l["estado"], l["estado"]),
                "Motivo": reativacao.MOTIVOS.get(l["motivo"] or "", l["motivo"] or ""),
                "Mensagem": l["texto"] or "",
                "Atualizado": horario_para_tela(loja, l["atualizado_em"]),
            } for l in ultimos], hide_index=True)

# ------------------------------------------------------------ Regras (S10a)
with aba_regras:
    mostrar_campos(loja, REGRAS_DAS_MENSAGENS, campos_das_regras(), "regras",
                   papel_atual(), usuario_atual(),
                   nota="Envio de verdade desligado: o sistema faz tudo, menos enviar. Ligado: "
                        "só envia se o envio também estiver liberado no servidor. Mudou aqui, "
                        "vale na próxima rodada do relógio.")

st.caption("Pausar, “Não enviar”, “Não procurar mais” e Desfazer ficam em “Ver como a loja”, "
           "aba Acompanhamento.")

"""Ver como a loja (nível Loja, S5): o painel da loja visto pelo operador.

Quatro abas: Atender, Leads, Resultado e Acompanhamento.
Loja Em teste: o operador age por ela (assumir, responder, registrar venda,
"Não enviar", pausar), com uma faixa de aviso; tudo vai para o Registro com
o nome de quem fez e o papel de operador.
Loja No ar: só leitura. Exceção: pausar e retomar os envios, liberados sempre.
A regra NÃO fica só aqui: app/permissoes.py recusa a ação mesmo chamando a
função direto. A tela só pergunta se pode e esconde os botões.
"""
from datetime import timedelta

import streamlit as st

from app import bloqueios, pausa
from app import painel_envios as pe
from app.apresentacao import data_para_tela, horario_para_tela, nomes_dos_clientes
from app.envio_painel import CANAIS_COM_ENVIO, EnvioRecusado, enviar_pelo_painel
from app.estoque import listar_estoque
from app.handoff import assumir_conversa, devolver_ao_agente
from app.lojas import carregar_loja
from app.mensagens import historico_do_lead
from app.painel_leitura import (
    ORDEM_DAS_ETAPAS, ROTULOS_ETAPA, cartao_do_lead, etapas_dos_leads, resultado_do_periodo,
)
from app.permissoes import AcaoNaoPermitida
from app.relogio import agora_utc, dia_local
from app.vendas import FORMAS, VendaInvalida, registrar_venda, vendas_do_lead
from app.ver_como import conversas_para_atender, situacao_para_tela
from paginas.comum import (
    avisar, definir_ator_da_sessao, exigir_operador, loja_atual, mostrar_aviso, para_streamlit,
    usuario_atual,
)
from paginas.operador.estilo import mostrar_selos
from paginas.operador.paginacao import mostrar_paginacao

exigir_operador()
loja = carregar_loja(loja_atual())
agente = loja.get("nome_agente", "Léo")

st.title("👀 Ver como a loja")
st.caption(f"{loja.nome} · o painel da loja visto pelo operador.")
definir_ator_da_sessao()          # quem age nesta execução (o nome vem do .env)
operador = usuario_atual()
situacao = situacao_para_tela(loja.id)
pode_agir = situacao["pode_agir"]
mostrar_aviso()

if pode_agir:
    st.warning(f"🧪 Loja {situacao['rotulo']}: você pode agir por ela. Tudo o que fizer aqui "
               f"fica no Registro como feito pelo operador ({operador}).")
else:
    st.info(f"🟢 Loja {situacao['rotulo']}: esta tela é só para ver. Quem atende é a equipe "
            "da loja. Pausar os envios continua liberado.")

ERROS_DA_ACAO = (AcaoNaoPermitida, VendaInvalida, EnvioRecusado,
                 bloqueios.BloqueioInvalido, pausa.PausaInvalida)


def _agir(acao, sucesso, tipo="success"):
    """Faz a ação pela camada app/ e mostra o resultado depois do rerun."""
    try:
        resultado = acao()
    except ERROS_DA_ACAO as erro:
        avisar(str(erro), "error")
    else:
        avisar(sucesso(resultado) if callable(sucesso) else sucesso, tipo)
    st.rerun()


def _texto_retomada(r):
    if r["cancelados"]:
        return (f"Envios retomados. {r['cancelados']} passo(s) de pós-venda que venceram "
                "durante a pausa foram cancelados.")
    return "Envios retomados."


def _form_venda(lead_id):
    with st.expander("🏁 Registrar venda"):
        carros = listar_estoque(loja_id=loja.id, incluir_vendidos=False)
        if not carros:
            st.caption("Nenhum carro disponível no estoque desta loja.")
            return
        nomes_carros = {c["id"]: f"{c['marca']} {c['modelo']} {c['ano']}" for c in carros}
        with st.form(f"vc_venda_{loja.id}_{lead_id}"):
            carro_id = st.selectbox("Carro", list(nomes_carros), format_func=nomes_carros.get)
            data_venda = st.date_input("Data da venda", value=dia_local(loja, agora_utc()),
                                       format="DD/MM/YYYY")
            forma = st.radio("Pagamento", FORMAS, horizontal=True,
                             format_func={"avista": "À vista", "financiado": "Financiado"}.get)
            meses = st.number_input("Meses de financiamento (0 = não sei)",
                                    min_value=0, max_value=120, step=1)
            if st.form_submit_button("Registrar venda", type="primary"):
                _agir(lambda: registrar_venda(loja.id, lead_id, carro_id, data_venda, forma,
                                              meses_financiamento=meses or None,
                                              vendedor=operador),
                      lambda r: f"Venda registrada: {r['carro']}.")


def _responder(c):
    if c["estado"] != "humano_assumiu":
        st.caption(f"Para escrever ao cliente, assuma a conversa. O {agente} fica em "
                   "silêncio enquanto isso.")
    elif c["vendedor"] and c["vendedor"] != operador:
        st.caption(f"Esta conversa está com {c['vendedor']}. Só quem assumiu responde.")
    elif c["canal"] not in CANAIS_COM_ENVIO:
        st.caption("O simulador não recebe mensagens do painel. Para testar a resposta, "
                   "use o Telegram.")
    else:
        with st.form(f"vc_resposta_{loja.id}_{c['lead_id']}", clear_on_submit=True):
            texto = st.text_area("Escreva para o cliente (sai pelo número da loja)")
            if st.form_submit_button("Enviar"):
                _agir(lambda: enviar_pelo_painel(loja.id, c["canal"], c["lead_id"], texto,
                                                 operador),
                      "Mensagem enviada.")


def _mostrar_historico(lead_id):
    mensagens = historico_do_lead(lead_id, loja_id=loja.id)
    if not mensagens:
        st.caption("Sem mensagens registradas ainda.")
    for m in mensagens:
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


def _mostrar_cartao(lead_id):
    cartao = cartao_do_lead(loja.id, lead_id)
    st.markdown(f"**{para_streamlit(cartao['nome'])}**")
    st.caption(f"{cartao['etapa_rotulo']} · {cartao['proximo_passo']}")
    for rotulo, chave in (("Telefone", "telefone"), ("Origem", "origem"), ("Carro", "carro"),
                          ("Pagamento", "pagamento"), ("Troca", "troca"), ("Prazo", "prazo"),
                          ("Visita", "visita"), ("Motivo do chamado", "motivo_do_chamado"),
                          ("Percebido na conversa", "etiqueta")):
        if cartao.get(chave):
            st.markdown(f"{rotulo}: {para_streamlit(str(cartao[chave]))}")
    for v in vendas_do_lead(loja.id, lead_id):
        st.caption(f"✅ Comprou {v['carro'] or 'um carro'} em {data_para_tela(v['data_venda'])}")


def _mostrar_resultado(res):
    if res["dados_de_teste"]:
        st.warning("🧪 Loja em teste: estes números incluem as conversas de teste.")
    elif res["contando_desde"]:
        st.caption("Contando desde que a loja entrou no ar: "
                   f"{horario_para_tela(loja, res['contando_desde'])}.")
    a, b, c, d = st.columns(4)
    a.metric("Conversas atendidas", res["conversas_atendidas"])
    b.metric("Chegaram fora do horário", res["fora_do_horario"])
    c.metric("Primeira resposta (média)", res["primeira_resposta_texto"])
    d.metric("Até o vendedor assumir (média)", res["ate_vendedor_assumir_texto"])
    e, f, g = st.columns(3)
    e.metric("Passados ao vendedor", res["passados_ao_vendedor"])
    f.metric("Visitas marcadas", res["visitas_marcadas"])
    g.metric("Vendas registradas", res["vendas_registradas"])
    st.subheader("Funil")
    st.dataframe([{"Etapa": x["rotulo"], "Total": x["total"]} for x in res["funil"]],
                 hide_index=True)
    st.subheader("Por dia")
    st.dataframe([{"Dia": x["dia_texto"], "No horário": x["no_horario"],
                   "Fora do horário": x["fora_do_horario"]} for x in res["por_dia"]],
                 hide_index=True)


aba_atender, aba_leads, aba_resultado, aba_acompanhamento = st.tabs(
    ["Atender", "Leads", "Resultado", "Acompanhamento"])

# ------------------------------------------------------------ Atender
with aba_atender:
    st.button("🔄 Atualizar", key="vc_atualizar")
    conversas = conversas_para_atender(loja.id)
    if not conversas:
        st.info("Nenhuma conversa nesta loja ainda.")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("Esperando vendedor", sum(c["estado"] == "aguardando_humano" for c in conversas))
        m2.metric("Com vendedor", sum(c["estado"] == "humano_assumiu" for c in conversas))
        m3.metric("Conversas", len(conversas))
        por_lead = {c["lead_id"]: c for c in conversas}

        def _rotulo(lead_id):
            c = por_lead[lead_id]
            partes = [c["estado_rotulo"], c["nome"], c["origem"],
                      f"última: {c['ultima']}" if c["ultima"] else ""]
            return " · ".join(p for p in partes if p)

        lead_id = st.selectbox("Conversa", list(por_lead), format_func=_rotulo,
                               key=f"vc_conversa_{loja.id}")
        conversa = por_lead[lead_id]
        col_conversa, col_lado = st.columns([3, 2])
        with col_lado:
            _mostrar_cartao(lead_id)
            st.markdown("---")
            st.markdown(f"**{conversa['estado_rotulo']}**")
            if conversa["estado"] == "humano_assumiu":
                st.caption(f"Com {conversa['vendedor'] or 'um vendedor'}")
            if pode_agir:
                if conversa["estado"] == "humano_assumiu":
                    if st.button(f"↩️ Devolver ao {agente}", key="vc_devolver"):
                        _agir(lambda: devolver_ao_agente(lead_id, loja.id), lambda r: r)
                elif st.button("✋ Assumir conversa", type="primary", key="vc_assumir"):
                    _agir(lambda: assumir_conversa(lead_id, operador, loja.id), lambda r: r)
                _form_venda(lead_id)
        with col_conversa:
            _mostrar_historico(lead_id)
            if pode_agir:
                _responder(conversa)

# ------------------------------------------------------------ Leads
with aba_leads:
    c1, c2 = st.columns([1, 2])
    dias = c1.selectbox("Período", (7, 30, 90), index=1,
                        format_func=lambda d: f"Últimos {d} dias", key="vc_leads_dias")
    busca = c2.text_input("Procurar por nome ou carro", key="vc_leads_busca")
    leads = etapas_dos_leads(loja.id, dias, busca or None)
    if not leads:
        st.info("Nenhum cliente neste período.")
    else:
        contagem = {etapa: 0 for etapa in ORDEM_DAS_ETAPAS}
        for l in leads:
            contagem[l["etapa"]] += 1
        for coluna, etapa in zip(st.columns(len(ORDEM_DAS_ETAPAS)), ORDEM_DAS_ETAPAS):
            coluna.metric(ROTULOS_ETAPA[etapa], contagem[etapa])
        st.dataframe([{
            "Cliente": l["nome"], "Carro": l["carro"] or "—", "Origem": l["origem"],
            "Último contato": l["ultimo_contato"], "Etapa": l["etapa_rotulo"],
            f"Próximo passo do {agente}": l["proximo_passo"],
        } for l in mostrar_paginacao(leads, f"vc_leads_{loja.id}")], hide_index=True)

# ------------------------------------------------------------ Resultado
with aba_resultado:
    hoje = dia_local(loja, agora_utc())
    periodo = st.date_input("Período", value=(hoje - timedelta(days=29), hoje), max_value=hoje,
                            format="DD/MM/YYYY", key="vc_resultado_periodo")
    if not (isinstance(periodo, (tuple, list)) and len(periodo) == 2):
        st.caption("Escolha o dia final do período.")
    else:
        try:
            resultado = resultado_do_periodo(loja.id, periodo[0], periodo[1])
        except ValueError as erro:
            st.warning(str(erro))
        else:
            _mostrar_resultado(resultado)

# ------------------------------------------------------------ Acompanhamento
with aba_acompanhamento:
    st.subheader("Pausar os envios")
    st.caption("Para tudo o que a loja manda por iniciativa própria (retomadas, pós-venda e "
               "reativação). Quem escreve continua sendo atendido. Liberado com a loja em "
               "qualquer estado.")
    sit = pausa.situacao(loja.id)
    if sit["pausado"]:
        quem = f"{sit['usuario']} ({pausa.ROTULOS_PAPEL.get(sit['papel'], sit['papel'])})"
        st.error(para_streamlit(
            f"⏸️ Envios pausados por {quem} · {horario_para_tela(loja, sit['em'])}"
            + (f" — {sit['motivo']}" if sit["motivo"] else "")))
        if st.button("▶️ Retomar os envios", key="vc_retomar"):
            _agir(lambda: pausa.retomar(loja.id, usuario=operador, papel="operador"),
                  _texto_retomada)
    else:
        motivo = st.text_input("Motivo (opcional)", key="vc_motivo_pausa")
        if st.button("⏸️ Pausar os envios", key="vc_pausar"):
            _agir(lambda: pausa.pausar(loja.id, usuario=operador, papel="operador",
                                       motivo=motivo),
                  "Envios pausados. O atendimento de quem escreve continua normal.", "warning")

    st.divider()
    st.subheader("Fila: quem será procurado")
    itens = pe.fila(loja.id, agora_utc())          # busca uma vez só
    if not itens:
        st.info("Ninguém na fila agora.")
    else:
        mostrar_selos([i["tipo"] for i in itens])
        nomes_fila = nomes_dos_clientes(loja.id, [i["lead_id"] for i in itens])
        st.dataframe([{
            "Quando": "—" if i.get("bloqueio") else (
                horario_para_tela(loja, i["quando"]) if i["quando"] else "na próxima rodada"),
            "Tipo": pe.TIPOS[i["tipo"]],
            "Cliente": nomes_fila.get(str(i["lead_id"]), "—"),
            "Situação": "Não será enviada" if i.get("bloqueio") else i["situacao"],
            "Detalhe": i["detalhe"],
        } for i in itens], hide_index=True)
        if pode_agir:
            with st.expander("🚫 Não enviar uma mensagem ou não procurar mais um cliente"):
                escolha = st.selectbox(
                    "Escolha a linha da fila", range(len(itens)), key="vc_linha_bloqueio",
                    format_func=lambda n: " · ".join(p for p in (
                        nomes_fila.get(str(itens[n]["lead_id"]), "—"),
                        pe.TIPOS[itens[n]["tipo"]], itens[n]["detalhe"]) if p))
                item = itens[escolha]
                b1, b2 = st.columns(2)
                if b1.button("🚫 Não enviar esta mensagem", key="vc_nao_enviar"):
                    _agir(lambda: bloqueios.bloquear(loja.id, item["lead_id"], item["tipo"],
                                                     item["passo"], operador),
                          "Marcado. Essa mensagem não sai até alguém desfazer.")
                if b2.button("⛔ Não procurar mais este cliente", key="vc_nao_procurar"):
                    _agir(lambda: bloqueios.bloquear(loja.id, item["lead_id"], "todos", None,
                                                     operador),
                          "Marcado. A loja não procura mais este cliente até alguém desfazer.")

    ativos = bloqueios.listar_ativos(loja.id)
    if ativos:
        with st.expander(f"Marcados para não enviar ({len(ativos)})"):
            nomes_b = nomes_dos_clientes(loja.id, [b["lead_id"] for b in ativos])
            st.dataframe([{
                "Cliente": nomes_b.get(str(b["lead_id"]), "—"),
                "O que": bloqueios.descricao(b), "Quem marcou": b["criado_por"],
                "Quando": horario_para_tela(loja, b["criado_em"]) if b["criado_em"] else "",
            } for b in ativos], hide_index=True)
            if pode_agir:
                # S10a: o Desfazer vinha da tela antiga "Retomadas e pós-venda".
                def _rotulo_marcado(n):
                    b = ativos[n]
                    return f"{nomes_b.get(str(b['lead_id']), '—')} · {bloqueios.descricao(b)}"

                qual = st.selectbox("Desfazer qual?", range(len(ativos)),
                                    format_func=_rotulo_marcado, key="vc_desfazer_qual")
                if st.button("↩️ Desfazer", key="vc_desfazer"):
                    _agir(lambda: bloqueios.desfazer(loja.id, ativos[qual]["id"], operador),
                          lambda feito: ("Desfeito. Se ainda valer, a mensagem sai na "
                                         "próxima rodada." if feito
                                         else "Isso já tinha sido desfeito."))

    pausas = pausa.historico(loja.id)
    if pausas:
        with st.expander("Quem pausou e retomou"):
            st.dataframe([{
                "Quando": horario_para_tela(loja, p["criado_em"]),
                "Ação": "Pausou" if p["acao"] == "pausar" else "Retomou",
                "Quem": p["usuario"], "Papel": pausa.ROTULOS_PAPEL.get(p["papel"], p["papel"]),
                "Motivo": p["motivo"] or "",
            } for p in pausas], hide_index=True)

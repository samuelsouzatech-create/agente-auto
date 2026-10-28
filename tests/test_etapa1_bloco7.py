"""
Etapa 1, Bloco 7A: o assistente como funcionário (itens 1.11 e 1.12). Todos offline.

Provam: o Léo percebe a situação do cliente sem comandos; "não me procure"
bloqueia só contatos da loja, nunca a resposta; só a loja reativa; primeiro
contato e "vendedor a caminho" no prompt; sem simulação na espera; assumir a
qualquer momento; resposta pelo painel; o Léo volta sabendo o que o vendedor
combinou; alerta de naturalidade; isolamento entre lojas.
"""
import asyncio
import json
import os
import py_compile
import uuid
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import banco
from app import envio_painel, interesse, lojas
from app.core.montagem import ferramentas_da_loja, montar_prompt
from app.core.turno import executar_turno
from app.envio_painel import EnvioRecusado, enviar_pelo_painel
from app.handoff import assumir_conversa, devolver_ao_agente, estado_do_handoff, quem_assumiu
from app.mensagens import historico_do_lead, ja_respondeu, salvar_mensagem
from app.naturalidade import parece_robotica
from tools import acionar_handoff, registrar_interesse

RAIZ = Path(__file__).resolve().parent.parent
LOJA_B = 42
HOJE = date(2026, 10, 27)
AGORA = datetime(2026, 10, 27, 15, 0, tzinfo=ZoneInfo("America/Recife"))


# ---------------------------------------------------------------- apoio
def _executar(sql, parametros=()):
    conexao = banco.conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


def _ler(sql, parametros=()):
    conexao = banco.conectar()
    try:
        return [dict(l) for l in conexao.execute(sql, parametros).fetchall()]
    finally:
        conexao.close()


def _lead():
    return f"lead-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def loja_b():
    _executar("INSERT INTO lojas (id, nome, segmento, config) VALUES (?, 'Auto Bia', 'veiculos', ?)",
              (LOJA_B, json.dumps({"nome_agente": "Bia"})))
    lojas.limpar_cache()
    yield LOJA_B
    lojas.limpar_cache()


def importar_agente():
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.setdefault("GOOGLE_API_KEY", "chave-falsa-so-para-importar")
    import app.core.agent as agent
    return agent


class LLMGravador:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.prompts = []

    def invoke(self, mensagens):
        self.prompts.append(mensagens[0][1])
        assert self.respostas, "O LLM falso ficou sem respostas."
        return self.respostas.pop(0)


class GrafoRoteiro:
    def __init__(self, texto="Oi!"):
        self.texto = texto
        self.chamadas = []

    def invoke(self, entrada, config=None):
        self.chamadas.append(entrada)
        return {"messages": [*entrada["messages"], AIMessage(content=self.texto)]}


def _chamada(nome, args):
    return AIMessage(content="", tool_calls=[{"name": nome, "args": args,
                                              "id": f"c-{uuid.uuid4().hex[:6]}"}])


def _rodar(agent, texto, loja_id, lead, canal="telegram"):
    return agent.agente_grafo.invoke(
        {"messages": [HumanMessage(content=texto)], "lead_id": lead,
         "loja_id": loja_id, "canal": canal},
        {"configurable": {"thread_id": f"{loja_id}:{canal}:{lead}"}},
    )

# ------------------------------------------- situação do lead (sem comandos)
def test_pediu_tempo_espera_e_depois_libera():
    lead = _lead()
    s = interesse.registrar_situacao(1, lead, "pediu_tempo", "vai ver com a esposa",
                                     dias=30, hoje=HOJE)
    assert s["retomar_em"] == "2026-11-26"
    assert interesse.pode_contatar(1, lead, hoje=HOJE) is False
    assert interesse.pode_contatar(1, lead, hoje=date(2026, 11, 26)) is True


def test_pediu_tempo_sem_data_usa_o_padrao():
    lead = _lead()
    s = interesse.registrar_situacao(1, lead, "pediu_tempo", "agora não", hoje=HOJE)
    assert s["retomar_em"] == "2026-11-26"          # 30 dias


def test_sem_interesse_bloqueia_contato_da_loja():
    lead = _lead()
    interesse.registrar_situacao(1, lead, "sem_interesse", "já comprou")
    assert interesse.pode_contatar(1, lead) is False
    assert _ler("SELECT * FROM optouts WHERE lead_id = ?", (lead,)) == []


def test_nao_contatar_grava_optout_e_so_a_loja_desfaz():
    lead = _lead()
    interesse.registrar_situacao(1, lead, "nao_contatar", "pediu para parar", canal="whatsapp")
    assert _ler("SELECT canal FROM optouts WHERE lead_id = ?", (lead,)) == [{"canal": "whatsapp"}]
    # O Léo não consegue "rebaixar" o pedido para outra situação.
    interesse.registrar_situacao(1, lead, "pediu_tempo", "voltou a conversar")
    assert interesse.situacao_do_lead(1, lead)["situacao"] == "nao_contatar"
    assert interesse.pode_contatar(1, lead) is False
    interesse.reativar_contato(1, lead)
    assert interesse.pode_contatar(1, lead) is True
    assert _ler("SELECT * FROM optouts WHERE lead_id = ?", (lead,)) == []


def test_situacao_invalida_e_recusada():
    with pytest.raises(interesse.SituacaoInvalida):
        interesse.registrar_situacao(1, _lead(), "PARAR")


def test_situacao_isolada_por_loja(loja_b):
    lead = _lead()
    interesse.registrar_situacao(1, lead, "nao_contatar", "x")
    assert interesse.pode_contatar(1, lead) is False
    assert interesse.pode_contatar(LOJA_B, lead) is True


def test_ferramenta_nao_fala_de_sistema():
    lead = _lead()
    r = registrar_interesse.invoke({"situacao": "nao_contatar", "motivo": "pediu",
                                    "lead_id": lead, "loja_id": 1, "canal": "telegram"})
    assert "Não mencione registro" in r
    erro = registrar_interesse.invoke({"situacao": "xyz", "motivo": "", "lead_id": lead, "loja_id": 1})
    assert erro.startswith("Erro")


def test_quem_pediu_para_nao_ser_procurado_continua_sendo_atendido():
    lead = _lead()
    interesse.registrar_situacao(1, lead, "nao_contatar", "pediu")
    r = asyncio.run(executar_turno(1, "simulador", lead, "oi, ainda tem o civic?",
                                   grafo=GrafoRoteiro("Tem sim!")))
    assert r.texto == "Tem sim!" and not r.silenciado


# ------------------------------------------- agente: momento da conversa
def test_primeiro_contato_aparece_so_na_primeira_resposta(monkeypatch):
    agent = importar_agente()
    falso = LLMGravador([AIMessage(content="Oi!"), AIMessage(content="Claro!")])
    monkeypatch.setattr(agent, "llm", falso)
    lead = _lead()
    _rodar(agent, "oi", 1, lead)
    assert "PRIMEIRO CONTATO" in falso.prompts[0]
    salvar_mensagem(lead, "leo", "Oi!", canal="telegram", loja_id=1)
    _rodar(agent, "tem civic?", 1, lead)
    assert "PRIMEIRO CONTATO" not in falso.prompts[1]


def test_vendedor_a_caminho_muda_o_prompt_e_tira_a_simulacao(monkeypatch):
    agent = importar_agente()
    lead = _lead()
    acionar_handoff.func(motivo="desconto", resumo="r", lead_id=lead, loja_id=1)
    falso = LLMGravador([
        _chamada("simular_financiamento", {"valor_carro": 50000, "entrada": 10000, "parcelas": 48}),
        AIMessage(content="Isso o vendedor fecha contigo."),
    ])
    monkeypatch.setattr(agent, "llm", falso)
    resultado = _rodar(agent, "e em 48x?", 1, lead)
    assert "VENDEDOR A CAMINHO" in falso.prompts[0]
    tool_msgs = [m for m in resultado["messages"] if isinstance(m, ToolMessage)]
    assert str(tool_msgs[0].content).startswith("Erro")
    nomes = {f.name for f in ferramentas_da_loja(lojas.carregar_loja(1), em_espera=True)}
    assert "simular_financiamento" not in nomes and "consultar_estoque" in nomes


def test_agente_injeta_o_canal_no_registrar_interesse(monkeypatch):
    agent = importar_agente()
    lead = _lead()
    monkeypatch.setattr(agent, "llm", LLMGravador([
        _chamada("registrar_interesse", {"situacao": "nao_contatar", "motivo": "pediu",
                                         "loja_id": 99, "canal": "inventado"}),
        AIMessage(content="Claro, desculpa o incômodo."),
    ]))
    _rodar(agent, "para de me mandar mensagem", 1, lead, canal="telegram")
    assert _ler("SELECT loja_id, canal FROM optouts WHERE lead_id = ?", (lead,)) == \
        [{"loja_id": 1, "canal": "telegram"}]


def test_prompt_sem_momento_nao_tem_camadas_extras():
    l1 = lojas.carregar_loja(1)
    p = montar_prompt(l1, ferramentas_da_loja(l1), AGORA)
    assert "PRIMEIRO CONTATO" not in p and "VENDEDOR A CAMINHO" not in p
    assert "registrar_interesse" in p and "JEITO DE CONVERSAR" in p


# ------------------------------------------- assumir a qualquer momento
def test_assumir_sem_o_leo_ter_chamado():
    lead = _lead()
    assert estado_do_handoff(lead, 1) == "ativo"
    assert assumir_conversa(lead, "Carlos", loja_id=1) == "Lead assumido por Carlos."
    assert estado_do_handoff(lead, 1) == "humano_assumiu"
    assert quem_assumiu(lead, 1) == "Carlos"
    [h] = _ler("SELECT origem, avisado_em FROM handoffs WHERE lead_id = ?", (lead,))
    assert h["origem"] == "painel" and h["avisado_em"]


def test_assumir_nao_toma_conversa_de_outro_vendedor():
    lead = _lead()
    assumir_conversa(lead, "Carlos", loja_id=1)
    assert "Carlos" in assumir_conversa(lead, "Ana", loja_id=1)
    assert quem_assumiu(lead, 1) == "Carlos"


def test_assumir_quando_o_leo_ja_chamou():
    lead = _lead()
    acionar_handoff.func(motivo="desconto", resumo="r", lead_id=lead, loja_id=1)
    assumir_conversa(lead, "Ana", loja_id=1)
    assert quem_assumiu(lead, 1) == "Ana"
    assert len(_ler("SELECT id FROM handoffs WHERE lead_id = ?", (lead,))) == 1


def test_leo_fica_em_silencio_depois_de_assumido():
    lead = _lead()
    assumir_conversa(lead, "Carlos", loja_id=1)
    grafo = GrafoRoteiro()
    r = asyncio.run(executar_turno(1, "telegram", lead, "e aí?", grafo=grafo))
    assert r.silenciado and grafo.chamadas == []


# ------------------------------------------- resposta pelo painel
@pytest.fixture
def envio_falso(monkeypatch):
    enviados = []

    async def falso(loja_id, canal, lead_id, texto):
        enviados.append((loja_id, canal, lead_id, texto))
        return True
    monkeypatch.setattr(envio_painel, "_despachar", falso)
    return enviados


def test_painel_so_envia_depois_de_assumir(envio_falso):
    lead = _lead()
    with pytest.raises(EnvioRecusado):
        enviar_pelo_painel(1, "telegram", lead, "Oi, aqui é o Carlos", "Carlos")
    assumir_conversa(lead, "Carlos", loja_id=1)
    enviar_pelo_painel(1, "telegram", lead, "Oi, aqui é o Carlos", "Carlos")
    assert envio_falso == [(1, "telegram", lead, "Oi, aqui é o Carlos")]
    ultima = historico_do_lead(lead, 1)[-1]
    assert (ultima["direcao"], ultima["autor"]) == ("vendedor", "Carlos")
    assert ja_respondeu(lead, 1)


def test_painel_recusa_outro_vendedor_simulador_e_vazio(envio_falso):
    lead = _lead()
    assumir_conversa(lead, "Carlos", loja_id=1)
    for canal, texto, quem in [("telegram", "oi", "Ana"), ("simulador", "oi", "Carlos"),
                               ("telegram", "   ", "Carlos")]:
        with pytest.raises(EnvioRecusado):
            enviar_pelo_painel(1, canal, lead, texto, quem)
    assert envio_falso == []


def test_painel_recusa_bot_de_outra_loja(monkeypatch, loja_b):
    """Revisão da Etapa 1: o painel usa as credenciais DA LOJA. A loja B não tem
    bot cadastrado, então não pode responder pelo bot da loja 1."""
    from app.canais import cadastrar_canal
    cadastrar_canal(1, "telegram", "111")          # só a loja 1 tem bot
    lead = _lead()
    assumir_conversa(lead, "Bia", loja_id=LOJA_B)
    with pytest.raises(EnvioRecusado):
        enviar_pelo_painel(LOJA_B, "telegram", lead, "oi", "Bia")
    # Nada foi gravado como enviado pelo vendedor.
    assert all(m["direcao"] != "vendedor" for m in historico_do_lead(lead, LOJA_B))


# ------------------------------------------- o Léo volta sabendo de tudo
def test_leo_volta_sabendo_o_que_o_vendedor_combinou():
    lead = _lead()
    salvar_mensagem(lead, "cliente", "faz desconto?", canal="telegram", loja_id=1)
    salvar_mensagem(lead, "leo", "Vou ver com o pessoal.", canal="telegram", loja_id=1)
    assumir_conversa(lead, "Carlos", loja_id=1)
    salvar_mensagem(lead, "vendedor", "Fecho com tapete de brinde.", canal="telegram",
                    loja_id=1, autor="Carlos")
    salvar_mensagem(lead, "cliente", "fechado!", canal="telegram", loja_id=1)
    devolver_ao_agente(lead, loja_id=1)

    grafo = GrafoRoteiro("Perfeito!")
    asyncio.run(executar_turno(1, "telegram", lead, "e o horário da loja?", grafo=grafo))
    enviado = grafo.chamadas[0]["messages"][0].content
    assert "Carlos (equipe da loja): Fecho com tapete de brinde." in enviado
    assert "Cliente: fechado!" in enviado
    assert enviado.endswith("e o horário da loja?")
    # O banco guarda só o que o cliente escreveu.
    assert historico_do_lead(lead, 1)[-2]["conteudo"] == "e o horário da loja?"


def test_sem_vendedor_no_meio_o_texto_vai_puro():
    lead = _lead()
    salvar_mensagem(lead, "leo", "Oi!", canal="telegram", loja_id=1)
    grafo = GrafoRoteiro()
    asyncio.run(executar_turno(1, "telegram", lead, "tem civic?", grafo=grafo))
    assert grafo.chamadas[0]["messages"][0].content == "tem civic?"


# ------------------------------------------- naturalidade e telas
@pytest.mark.parametrize("frase", [
    "Digite PARAR para sair", "Estou transferindo você", "Vou te desconectar agora",
    "Um atendente humano já vem", "Para cancelar a inscrição responda SAIR",
])
def test_frases_de_robo_sao_detectadas(frase):
    assert parece_robotica(frase)


@pytest.mark.parametrize("frase", [
    "O Civic tem comandos no volante.", "Vou ver com o pessoal das vendas, já te chamam aqui.",
    "Tranquilo, sem pressa. Quando quiser, é só me chamar.",
])
def test_frases_naturais_passam(frase):
    assert parece_robotica(frase) is None


def test_migracao_3():
    conexao = banco.conectar()
    try:
        assert banco.versao_schema(conexao) >= 3
        col_h = {c["name"] for c in conexao.execute("PRAGMA table_info(handoffs)")}
        col_m = {c["name"] for c in conexao.execute("PRAGMA table_info(mensagens)")}
    finally:
        conexao.close()
    assert {"origem", "reavisado_em", "gestor_avisado_em"} <= col_h
    assert "autor" in col_m


def test_pagina_conversas_compila():
    py_compile.compile(str(RAIZ / "paginas" / "conversas.py"), doraise=True)

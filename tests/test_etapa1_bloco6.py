"""
Etapa 1, Bloco 6: custos e logs (item 1.9).
IA falsa com tokens conhecidos, banco temporário e duas lojas.
"""
import asyncio
import json
import py_compile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import banco
from app import custos, logs, precos
from app.core.turno import ResultadoTurno, executar_turno
from app.custos import Uso
from app.lojas import criar_loja

RAIZ = Path(__file__).resolve().parent.parent
OUT_10 = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
OUT_11 = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
SET_20 = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _precos_base(desde="2026-01-01"):
    precos.cadastrar_preco("ia.entrada", 0.10, desde, "USD")
    precos.cadastrar_preco("ia.saida", 0.40, desde, "USD")
    precos.cadastrar_preco("cambio.usd_brl", 5.0, desde)


class GrafoFalso:
    """Devolve sempre as mesmas mensagens depois da mensagem do cliente."""

    def __init__(self, mensagens):
        self.mensagens = mensagens

    def invoke(self, entrada, config):
        return {"messages": [*entrada["messages"], *self.mensagens]}


class GrafoQuebrado:
    def invoke(self, entrada, config):
        raise RuntimeError("IA fora do ar")


def _conversa_roteirizada(resposta="Temos um Civic 2019 disponível. Quer ver as fotos?"):
    return [
        AIMessage(content="", tool_calls=[{"name": "consultar_estoque", "args": {}, "id": "c1"}],
                  usage_metadata={"input_tokens": 1200, "output_tokens": 30, "total_tokens": 1230}),
        ToolMessage(content="Honda Civic 2019, automático", tool_call_id="c1", name="consultar_estoque"),
        AIMessage(content=resposta,
                  usage_metadata={"input_tokens": 1500, "output_tokens": 40, "total_tokens": 1540}),
    ]


def _linhas_custo():
    conexao = banco.conectar()
    try:
        return [dict(l) for l in conexao.execute("SELECT * FROM uso_custos ORDER BY id")]
    finally:
        conexao.close()


# ====================================================== migração
def test_migracao_2_acrescenta_colunas():
    conexao = banco.conectar()
    try:
        assert banco.versao_schema(conexao) == banco.VERSAO_SCHEMA >= 2
        colunas = {c["name"] for c in conexao.execute("PRAGMA table_info(uso_custos)")}
    finally:
        conexao.close()
    assert {"tipo", "modelo", "custo_completo"} <= colunas


# ====================================================== preços
def test_nomes_dos_precos_sao_neutros():
    texto = " ".join(k + v["rotulo"] for k, v in precos.ITENS.items()).lower()
    assert "gemini" not in texto and "google" not in texto


def test_preco_vigente_respeita_a_data():
    precos.cadastrar_preco("ia.entrada", 0.10, "2026-01-01", "USD")
    precos.cadastrar_preco("ia.entrada", 0.20, "2026-10-15", "USD")
    assert precos.preco_vigente("ia.entrada", "2026-10-10")["valor"] == 0.10
    assert precos.preco_vigente("ia.entrada", "2026-10-20")["valor"] == 0.20
    assert precos.preco_vigente("ia.entrada", "2025-12-31") is None


def test_mesma_data_corrige_em_vez_de_duplicar():
    precos.cadastrar_preco("ia.saida", 0.40, "2026-01-01", "USD")
    precos.cadastrar_preco("ia.saida", 0.50, "2026-01-01", "USD")
    assert [p["valor"] for p in precos.listar_precos()] == [0.50]


def test_conversao_de_dolar_para_real():
    precos.cadastrar_preco("ia.entrada", 0.10, "2026-01-01", "USD")
    assert precos.valor_em_brl("ia.entrada", "2026-10-10") is None     # falta a cotação
    precos.cadastrar_preco("cambio.usd_brl", 5.0, "2026-01-01", "USD")  # vira BRL sozinho
    assert precos.valor_em_brl("ia.entrada", "2026-10-10") == pytest.approx(0.5)
    precos.cadastrar_preco("meta.servico", 0.04, "2026-01-01", "BRL")
    assert precos.valor_em_brl("meta.servico", "2026-10-10") == 0.04


def test_faltando_lista_os_essenciais():
    assert precos.faltando("2026-10-10") == list(precos.ESSENCIAIS)
    _precos_base()
    assert precos.faltando("2026-10-10") == []


def test_validacao_de_preco():
    for argumentos in [("ia.inventado", 1, "2026-01-01"), ("ia.entrada", -1, "2026-01-01"),
                       ("cambio.usd_brl", 0, "2026-01-01"), ("ia.entrada", 1, "10/10/2026"),
                       ("ia.entrada", "abc", "2026-01-01")]:
        with pytest.raises(precos.PrecoInvalido):
            precos.cadastrar_preco(*argumentos)


# ====================================================== medir
def test_uso_soma_respostas_da_ia_e_separa_audio():
    mensagens = [
        AIMessage(content="a", usage_metadata={"input_tokens": 100, "output_tokens": 10,
                                               "total_tokens": 110,
                                               "input_token_details": {"audio": 40}}),
        ToolMessage(content="x", tool_call_id="1", name="consultar_estoque"),
        AIMessage(content="b"),                                        # sem metadados
        AIMessage(content="c", usage_metadata={"input_tokens": 50, "output_tokens": 5,
                                               "total_tokens": 55}),
    ]
    assert custos.uso_das_mensagens(mensagens) == Uso(110, 15, 40)
    assert custos.ferramentas_usadas(mensagens) == ["consultar_estoque"]
    assert custos.uso_das_mensagens([]) == Uso()


def test_custo_com_precos():
    _precos_base()
    ia, meta, completo = custos.calcular_custo(Uso(1000, 500, 0), "2026-10-10")
    assert ia == pytest.approx((1000 * 0.10 + 500 * 0.40) / 1e6 * 5.0)
    assert meta == 0 and completo is True


def test_audio_sem_preco_proprio_usa_o_de_entrada():
    _precos_base()
    ia, _, completo = custos.calcular_custo(Uso(0, 0, 1000), "2026-10-10")
    assert ia == pytest.approx(1000 * 0.10 / 1e6 * 5.0) and completo is True


def test_sem_preco_grava_tokens_e_recalcula_depois():
    registro = custos.registrar_uso(1, "5581", "simulador", Uso(1000, 500), agora=OUT_10)
    assert registro["custo_total"] == 0 and registro["completo"] is False
    _precos_base("2026-10-01")
    assert custos.recalcular_custos() == 1
    linha = _linhas_custo()[0]
    assert linha["custo_llm"] == pytest.approx(0.0015) and linha["custo_completo"] == 1


def test_conversa_roteirizada_gera_a_linha_esperada():
    _precos_base()
    resultado = asyncio.run(executar_turno(1, "simulador", "sim-1", "tem civic?",
                                           grafo=GrafoFalso(_conversa_roteirizada())))
    [linha] = _linhas_custo()
    assert (linha["loja_id"], linha["lead_id"], linha["canal"], linha["tipo"]) == \
        (1, "sim-1", "simulador", "turno")
    assert (linha["tokens_entrada"], linha["tokens_saida"], linha["tokens_audio"]) == (2700, 70, 0)
    assert json.loads(linha["ferramentas"]) == ["consultar_estoque"]
    assert linha["msgs_servico"] == 0                       # simulador não paga Meta
    esperado = (2700 * 0.10 + 70 * 0.40) / 1e6 * 5.0
    assert linha["custo_llm"] == pytest.approx(esperado)
    assert linha["latencia_ms"] is not None and linha["modelo"]
    assert resultado.custo == pytest.approx(esperado)
    assert resultado.execucao_id == linha["execucao_id"]


def test_whatsapp_conta_mensagens_da_meta():
    _precos_base()
    precos.cadastrar_preco("meta.servico", 0.04, "2026-01-01", "BRL")
    resposta = "Temos um Civic 2019.\n\nQuer agendar uma visita?"
    asyncio.run(executar_turno(1, "whatsapp", "5581", "oi",
                               grafo=GrafoFalso(_conversa_roteirizada(resposta))))
    linha = _linhas_custo()[0]
    assert linha["msgs_servico"] == 2
    assert linha["custo_meta"] == pytest.approx(0.08)


def test_log_tem_o_mesmo_execucao_id_do_banco():
    resultado = asyncio.run(executar_turno(1, "simulador", "sim-2", "oi",
                                           grafo=GrafoFalso(_conversa_roteirizada())))
    ultima = logs.ler_execucoes()[-1]
    assert ultima["execucao_id"] == resultado.execucao_id == _linhas_custo()[0]["execucao_id"]
    assert ultima["custo_ia"] == 0 and ultima["completo"] is False     # sem preços
    assert "custo_ia" in ultima and "custo_llm" not in ultima


def test_falha_no_custo_nao_derruba_a_conversa(monkeypatch):
    def quebrado():
        raise RuntimeError("banco travado")
    monkeypatch.setattr(custos, "conectar", quebrado)
    assert custos.registrar_uso(1, "x", "simulador", Uso(10, 10)) is None
    resultado = asyncio.run(executar_turno(1, "simulador", "sim-3", "oi",
                                           grafo=GrafoFalso(_conversa_roteirizada())))
    assert resultado.texto.startswith("Temos um Civic") and resultado.custo is None


def test_erro_da_ia_fica_registrado():
    resultado = asyncio.run(executar_turno(1, "simulador", "sim-4", "oi", grafo=GrafoQuebrado()))
    linha = _linhas_custo()[0]
    assert linha["tipo"] == "erro" and resultado.execucao_id == linha["execucao_id"]


def test_silenciado_nao_gera_custo(monkeypatch):
    import app.core.turno as turno
    monkeypatch.setattr(turno, "estado_do_handoff", lambda lead, loja: "humano_assumiu")
    asyncio.run(executar_turno(1, "simulador", "sim-5", "oi",
                               grafo=GrafoFalso(_conversa_roteirizada())))
    assert _linhas_custo() == []


def test_custo_fica_fora_da_comparacao_do_resultado():
    assert ResultadoTurno(texto="a", custo=1.0, execucao_id="x") == ResultadoTurno(texto="a")


def test_log_que_nao_consegue_gravar_nao_quebra(tmp_path, monkeypatch):
    arquivo = tmp_path / "sou_um_arquivo"
    arquivo.write_text("x")
    monkeypatch.setattr(logs, "PASTA_LOGS", str(arquivo))
    assert logs.registrar_execucao({"a": 1}) is False


# ====================================================== áudio
def test_uso_da_transcricao():
    from app.api.receber_audio import uso_da_resposta
    resposta = SimpleNamespace(usage_metadata=SimpleNamespace(
        prompt_token_count=520, candidates_token_count=25,
        prompt_tokens_details=[SimpleNamespace(modality="MediaModality.AUDIO", token_count=500),
                               SimpleNamespace(modality="MediaModality.TEXT", token_count=20)]))
    assert uso_da_resposta(resposta) == Uso(20, 25, 500)
    assert uso_da_resposta(SimpleNamespace()) == Uso()


# ====================================================== relatórios e lojas
def _cenario_duas_lojas():
    _precos_base()
    loja2 = criar_loja("Loja Dois")
    custos.registrar_uso(1, "A", "telegram", Uso(1000, 100), agora=OUT_10,
                         ferramentas=["consultar_estoque", "enviar_fotos"])
    custos.registrar_uso(1, "A", "telegram", Uso(1000, 100), agora=OUT_11,
                         ferramentas=["consultar_estoque"])
    custos.registrar_uso(1, "B", "telegram", Uso(1000, 100), agora=OUT_11)
    custos.registrar_uso(1, "C", "telegram", Uso(1000, 100), agora=SET_20)   # outro mês
    custos.registrar_uso(loja2, "A", "telegram", Uso(9000, 900), agora=OUT_10)
    return loja2


def test_resumo_do_mes_e_conversa_por_lead():
    loja2 = _cenario_duas_lojas()
    um_turno = (1000 * 0.10 + 100 * 0.40) / 1e6 * 5.0
    r1 = custos.resumo_mes(1, 2026, 10)
    assert r1["conversas"] == 2 and r1["turnos"] == 3
    assert r1["custo_total"] == pytest.approx(3 * um_turno, abs=1e-6)
    assert r1["custo_medio_conversa"] == pytest.approx(3 * um_turno / 2, abs=1e-6)
    assert custos.resumo_mes(1, 2026, 9)["conversas"] == 1
    assert custos.resumo_mes(loja2, 2026, 10)["conversas"] == 1


def test_custo_de_uma_loja_nunca_aparece_na_outra():
    loja2 = _cenario_duas_lojas()
    assert custos.resumo_mes(loja2, 2026, 10)["tokens_entrada"] == 9000
    assert custos.resumo_mes(1, 2026, 10)["tokens_entrada"] == 3000
    assert all(l["loja_id"] == loja2 for l in [_linhas_custo()[-1]])
    assert len(custos.ultimas_execucoes(loja2)) == 1


def test_gasto_do_dia_e_ferramentas():
    _cenario_duas_lojas()
    um_turno = (1000 * 0.10 + 100 * 0.40) / 1e6 * 5.0
    assert custos.gasto_do_dia(1, "2026-10-11") == pytest.approx(2 * um_turno, abs=1e-6)
    assert custos.ferramentas_mais_usadas(1, 2026, 10) == [("consultar_estoque", 2), ("enviar_fotos", 1)]
    assert [d["dia"] for d in custos.custo_por_dia(1, 2026, 10)] == ["2026-10-10", "2026-10-11"]


# ====================================================== página
def test_pagina_de_custos_compila():
    py_compile.compile(str(RAIZ / "paginas" / "custos.py"), doraise=True)

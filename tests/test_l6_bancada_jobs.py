"""
L6: roteiros de job na bancada (remarketing e pós-venda), OFFLINE: relógio simulado,
envio falso, redator falso, LLM falso, banco temporário. Nada sai para canal real.
"""
import asyncio
import os
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.custos import Uso
from scripts import rodar_bancada as rb


class GrafoFalso:
    def __init__(self, resposta="Oi! Que bom falar com você de novo."):
        self.resposta = resposta
        self.chamadas = []

    def invoke(self, entrada, config=None):
        texto = entrada["messages"][0].content
        self.chamadas.append(texto)
        return {"messages": [HumanMessage(content=texto), AIMessage(content=self.resposta)]}


def redator_falso():
    textos = iter(["Oi! O Civic 2019 ainda está aqui. Quer marcar uma visita?",
                   "Passando para saber se ficou alguma dúvida sobre o Civic.",
                   "Fico à disposição quando quiser falar do carro."] + [f"texto extra {i}" for i in range(10)])

    def redigir(loja, lead_id, canal, toque, dados, historico):
        return next(textos), Uso(100, 20)
    return redigir


@pytest.fixture(autouse=True)
def pasta_temporaria_da_bancada(monkeypatch, tmp_path):
    monkeypatch.setattr(rb, "_PASTA_TEMP", tmp_path / "bancada")
    (tmp_path / "bancada").mkdir()


def roteiro(**campos):
    base = {"nome": "job", "conversa": [{"cliente": "tem civic?"},
                                        {"leo": "Temos o Civic 2019 por R$ 98.000,00."}],
            "interesse": "Civic", "passos": [{"remarketing_dias": 30}]}
    base.update(campos)
    return rb.validar_roteiro(base, "teste")


def rodar(roteiros, grafo=None, redator=None):
    return asyncio.run(rb.rodar(roteiros, grafo or GrafoFalso(), teto=1.0, redator=redator or redator_falso()))


def test_roteiros_de_job_carregam():
    roteiros = {r["nome"]: r for r in rb.carregar_roteiros()}
    for nome in ("remarketing_3_toques", "remarketing_cliente_responde", "remarketing_pede_parada",
                 "remarketing_carro_vendido", "remarketing_fora_do_horario", "pos_venda_tudo_otimo",
                 "pos_venda_problema", "pos_venda_irritado"):
        assert roteiros[nome]["passos"], nome


def test_validacao_dos_passos():
    with pytest.raises(rb.RoteiroInvalido, match="passo 1"):
        roteiro(passos=[{"dormir": 3}])
    with pytest.raises(rb.RoteiroInvalido, match="inteiro positivo"):
        roteiro(passos=[{"remarketing_dias": 0}])
    with pytest.raises(rb.RoteiroInvalido, match="não 'falas'"):
        roteiro(falas=["oi"])
    with pytest.raises(rb.RoteiroInvalido, match="conversa"):
        roteiro(conversa=[{"vendedor": "oi"}])


def test_relogio_comeca_na_segunda_10h():
    from datetime import date
    from app.relogio import hora_local
    from app.lojas import carregar_loja
    inicio = rb.inicio_do_relogio(date(2026, 11, 18))        # quarta
    local = inicio.astimezone(__import__("zoneinfo").ZoneInfo("America/Recife"))
    assert (local.weekday(), local.hour, local.date()) == (0, 10, date(2026, 11, 23))


def test_tres_toques_no_horario_com_textos_diferentes():
    rodada = rodar([roteiro(deve={"toques": 3, "textos_diferentes": True, "envios_no_horario": True},
                            nao_pode=["preco_inventado"])])
    res = rodada.resultados[0]
    assert res.status == rb.PASSOU, (res.falhas, res.promessas)
    assert [e["tipo"] for e in res.envios_job] == ["remarketing"] * 3
    assert res.tokens_entrada == 300                       # o custo do redator entra na conta
    assert "[remarketing" in rb.montar_relatorio(rodada)


def test_texto_repetido_e_preco_fora_do_estoque_nao_chegam_ao_cliente():
    # L10: o job descarta preço fora do estoque e texto igual a um toque anterior
    # (usa o texto reserva, um diferente por toque). A bancada confere o resultado.
    def repete(loja, lead_id, canal, toque, dados, historico):
        return "O Civic sai por R$ 80.000,00 só hoje!", Uso()

    rodada = rodar([roteiro(deve={"textos_diferentes": True}, nao_pode=["preco_inventado"])], redator=repete)
    res = rodada.resultados[0]
    assert res.status == rb.PASSOU, (res.falhas, res.promessas)
    assert all("80.000" not in e["texto"] for e in res.envios_job)
    assert len({e["texto"] for e in res.envios_job}) == len(res.envios_job)


def test_bancada_pega_toques_repetidos_se_chegarem():
    textos = ["O Civic sai por R$ 98.000,00.", "O Civic sai por R$ 98.000,00."]
    assert rb.toques_parecidos(textos)


def test_cliente_responde_e_o_remarketing_para():
    grafo = GrafoFalso("Ainda está sim! Quer marcar uma visita?")
    rodada = rodar([roteiro(passos=[{"remarketing_dias": 4}, {"cliente": "ainda tenho interesse"},
                                    {"remarketing_dias": 25}], deve={"toques": 1})], grafo=grafo)
    res = rodada.resultados[0]
    assert grafo.chamadas == ["ainda tenho interesse"]
    assert len([e for e in res.envios_job if e["tipo"] == "remarketing"]) == 1, res.envios_job


def test_pede_parada_e_o_remarketing_para():
    rodada = rodar([roteiro(passos=[{"remarketing_dias": 4}, {"cliente": "para de me mandar mensagem"},
                                    {"remarketing_dias": 25}], deve={"toques": 1})])
    assert rodada.resultados[0].status == rb.PASSOU, rodada.resultados[0].falhas


def test_horario_da_loja_e_respeitado():
    rodada = rodar([roteiro(loja={"remarketing": {"horario_envio": "10:00-11:00", "dias_envio": [0, 1, 2, 3, 4]}},
                            deve={"envios_no_horario": True})])
    res = rodada.resultados[0]
    assert res.envios_job and res.status == rb.PASSOU, res.falhas


def test_pos_venda_manda_e_cliente_responde():
    rodada = rodar([rb.validar_roteiro({
        "nome": "pv", "conversa": [{"cliente": "fechei o Onix"}],
        "venda": {"modelo": "Onix", "pagamento": "avista"},
        "passos": [{"pos_venda_dias": 8}, {"cliente": "tá tudo ótimo"}],
        "deve": {"handoff": False, "envios_no_horario": True}}, "teste")],
        grafo=GrafoFalso("Que bom! Obrigado por contar."))
    res = rodada.resultados[0]
    assert [e["tipo"] for e in res.envios_job] == ["pos-venda", "pos-venda"]      # dia 1 e dia 7
    assert res.status == rb.PASSOU, res.falhas


def test_handoff_ate_fala_conta_so_falas_do_cliente():
    from tools import acionar_handoff

    class GrafoChama(GrafoFalso):
        def invoke(self, entrada, config=None):
            acionar_handoff.func(motivo="m", resumo="r", lead_id=entrada["lead_id"], loja_id=entrada["loja_id"])
            return super().invoke(entrada, config)

    rodada = rodar([rb.validar_roteiro({
        "nome": "pv2", "conversa": [{"cliente": "fechei o Onix"}],
        "venda": {"modelo": "Onix", "pagamento": "avista"},
        "passos": [{"pos_venda_dias": 2}, {"cliente": "deu um problema"}],
        "deve": {"handoff": True, "handoff_ate_fala": 1}}, "teste")], grafo=GrafoChama())
    assert rodada.resultados[0].status == rb.PASSOU, rodada.resultados[0].falhas

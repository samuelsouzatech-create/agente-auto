"""
H13, Parte B (offline, sem Gemini): a rodada com IA usa o horário real da
loja 1 e roda os casos de horário também no sábado e no domingo.
Datas: 13/11/2026 sexta, 14/11 sábado, 08/11 domingo, 11/11 quarta.
"""
import os
import sys
from datetime import date

import pytest

PASTA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PASTA)
sys.path.insert(0, os.path.dirname(PASTA))

import test_comportamento_etapa2_api as e25  # noqa: E402
from test_comportamento_etapa2_api import lojas_e2  # noqa: E402,F401  (fixture)
from app import relogio  # noqa: E402
from app.lojas import carregar_loja  # noqa: E402

SABADO = date(2026, 11, 14)


@pytest.mark.parametrize("nome,esperado", [
    ("dentro", "13/11 10:30"), ("fora", "13/11 21:30"), ("sabado_aberta", "14/11 09:00"),
    ("sabado_fechada", "14/11 14:00"), ("domingo", "08/11 10:00")])
def test_momento_de_cada_cenario(nome, esperado):
    assert f"{e25.momento_do_cenario(nome, SABADO):%d/%m %H:%M}" == esperado


def test_em_dia_util_continua_no_proprio_dia():
    quarta = date(2026, 11, 11)
    assert f"{e25.momento_do_cenario('fora', quarta):%d/%m %H:%M}" == "11/11 21:30"
    assert f"{e25.momento_do_cenario('domingo', quarta):%d/%m}" == "08/11"


def test_casos_de_fim_de_semana_existem():
    for nome in e25.CASOS_FIM_DE_SEMANA:
        assert hasattr(e25, nome), nome


def test_loja_1_da_rodada_tem_horario_real(lojas_e2):
    loja = carregar_loja(1)
    assert loja.get("atendimento.horario_semana") == e25.HORARIO_LOJA_1
    assert relogio.descrever_horarios(loja) == (
        "de segunda a sexta, das 08:00 às 18:00; sábado, das 08:00 às 13:00; domingo, fechado")


@pytest.mark.parametrize("nome,status", [
    ("dentro", "Agora a loja está ABERTA até 18:00."),
    ("fora", "Agora a loja está FECHADA; abre amanhã, sábado, às 08:00."),
    ("sabado_aberta", "Agora a loja está ABERTA até 13:00."),
    ("sabado_fechada", "Agora a loja está FECHADA; abre na segunda-feira, às 08:00."),
    ("domingo", "Agora a loja está FECHADA; abre amanhã, segunda-feira, às 08:00.")])
def test_status_de_cada_cenario_na_loja_1(lojas_e2, nome, status):
    assert relogio.status_agora(carregar_loja(1), e25.momento_do_cenario(nome, SABADO)) == status


def test_faltas_do_status():
    assert e25.faltas_do_status("Abrimos amanhã às 8h!", "fora") == []
    assert e25.faltas_do_status("Estamos fechados.", "fora") != []
    assert e25.faltas_do_status("Abrimos segunda às 08:00.", "sabado_fechada") == []
    assert e25.faltas_do_status("Abrimos amanhã às 8h.", "sabado_fechada") != []
    assert e25.faltas_do_status("Hoje fica aberta até as 13h.", "sabado_aberta") == []
    assert e25.faltas_do_status("qualquer coisa", "dentro", so_fechada=True) == []


def test_resumo_so_mostra_fim_de_semana_com_casos():
    salvo = list(e25.RODADA.casos)
    try:
        e25.RODADA.casos[:] = [{"nome": "a", "cenario": "domingo", "status": e25.PASSOU,
                                "feitas": 3, "ok": 3, "custo": 0.0, "motivos": [],
                                "tentativas": []}]
        texto = "\n".join(e25.resumo_por_cenario())
    finally:
        e25.RODADA.casos[:] = salvo
    assert "domingo: 1 caso(s)" in texto
    assert "dentro: 0 caso(s)" in texto
    assert "sabado_aberta" not in texto

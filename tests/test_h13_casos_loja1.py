"""
H13 (offline, sem Gemini): os casos que montam a loja 1 de novo
(espera e duas lojas) precisam manter o horário real (08:00).
"""
import inspect
from datetime import datetime, timezone

try:
    import tests.test_comportamento_etapa2_api as e25
except ImportError:
    import test_comportamento_etapa2_api as e25

from app import relogio
from app.lojas import carregar_loja

lojas_e2 = e25.lojas_e2   # usa a mesma preparação da rodada

# sexta 13/11/2026 21:30 em Recife = sábado 14/11 00:30 UTC
SEXTA_21_30 = datetime(2026, 11, 14, 0, 30, tzinfo=timezone.utc)


def _status():
    return relogio.status_agora(carregar_loja(1), SEXTA_21_30)


def test_preparacao_ja_tem_o_horario_real(lojas_e2):
    assert "08:00" in _status()


def test_casos_de_espera_mantem_o_horario_real(lojas_e2):
    for opcao in ("conversar", "meio_termo", "esperar"):
        e25._caso_espera(opcao)
        s = _status()
        assert "08:00" in s and "09:00" not in s, (opcao, s)


def test_duas_lojas_devolve_o_horario_real():
    fonte = inspect.getsource(e25.test_duas_lojas_tom_e_nome_diferentes)
    assert "_horario_real_loja_1()" in fonte
    assert fonte.index("_horario_real_loja_1()") > fonte.index('"nome_agente": "Ricardo"')

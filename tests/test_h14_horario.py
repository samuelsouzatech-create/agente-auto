"""
H14 (offline, sem Gemini): visita só dentro do expediente do dia, data
resolvida gravada, dúvida vira pergunta, e espera cortada no fechamento.
Loja 1: dias úteis 08:00-18:00, sábado 08:00-13:00, domingo fechado.
Novembro de 2026: 13 = sexta, 14 = sábado, 15 = domingo, 16 = segunda.
"""
import inspect
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

try:
    import tests.test_comportamento_etapa2_api as e25
except ImportError:
    import test_comportamento_etapa2_api as e25

import banco
from app import relogio
from tools.agendar_visita import agendar_visita, entender_dia, entender_hora

lojas_e2 = e25.lojas_e2
if hasattr(e25, "banco_temporario"):
    banco_temporario = e25.banco_temporario

RAIZ = Path(__file__).resolve().parent.parent
RECIFE = ZoneInfo("America/Recife")
HORARIO = {"0": "08:00-18:00", "1": "08:00-18:00", "2": "08:00-18:00",
           "3": "08:00-18:00", "4": "08:00-18:00", "5": "08:00-13:00"}
LOJA = {"fuso": "America/Recife", "atendimento.horario_semana": HORARIO}
LOJA_ANTIGA = {"fuso": "America/Recife", "atendimento.horario_humano": "09:00-18:00",
               "atendimento.dias_humano": [0, 1, 2, 3, 4, 5]}
SEXTA_10_30 = datetime(2026, 11, 13, 10, 30, tzinfo=RECIFE)
SABADO_14_00 = datetime(2026, 11, 14, 14, 0, tzinfo=RECIFE)


def L(dia, h, m=0):
    return datetime(2026, 11, dia, h, m, tzinfo=RECIFE).astimezone(timezone.utc)


# ---------------------------------------------------------------- espera
@pytest.mark.parametrize("desde,agora,esperado", [
    (L(13, 17, 50), L(13, 21, 0), 10),
    (L(14, 12, 50), L(14, 14, 0), 10),
    (L(13, 17, 50), L(16, 8, 5), 5),
    (L(13, 17, 50), L(16, 7, 0), 0),
    (L(15, 10, 0), L(15, 11, 0), 0),
])
def test_espera_cortada_no_fechamento(desde, agora, esperado):
    assert relogio.minutos_no_expediente(LOJA, desde, agora) == esperado


def test_formato_antigo_tambem_corta():
    assert relogio.minutos_no_expediente(LOJA_ANTIGA, L(13, 17, 50), L(13, 21, 0)) == 10


@pytest.mark.parametrize("agora", [L(13, 8, 30), L(13, 12, 0), L(13, 17, 59), L(14, 12, 59)])
def test_dentro_do_expediente_nada_muda(agora):
    assert relogio.minutos_no_expediente(LOJA, agora - timedelta(minutes=25), agora) == 25


@pytest.mark.parametrize("arquivo", ["app/api_painel/atender.py", "app/visao_geral.py",
                                     "app/jobs/alertas.py", "paginas/handoff.py"])
def test_atender_atencao_avisos_e_fila_usam_a_mesma_conta(arquivo):
    assert "minutos_no_expediente(" in (RAIZ / arquivo).read_text(encoding="utf-8")


# ---------------------------------------------------------------- horário marcado (bordas)
@pytest.mark.parametrize("dia,h,m,duracao,esperado", [
    (15, 10, 0, 30, "fechada"),
    (14, 15, 0, 30, "13:00"),
    (14, 12, 45, 30, "12:30"),
    (14, 12, 30, 30, None),
    (14, 12, 45, 0, None),
    (16, 7, 59, 30, "08:00"),
    (16, 8, 0, 30, None),
    (16, 17, 40, 30, "17:30"),
    (16, 17, 30, 30, None),
])
def test_conferir_horario_marcado(dia, h, m, duracao, esperado):
    motivo = relogio.conferir_horario_marcado(LOJA, date(2026, 11, dia), time(h, m), duracao)
    if esperado is None:
        assert motivo is None
    else:
        assert motivo and esperado in motivo, motivo


# ---------------------------------------------------------------- o código entende o dia
@pytest.mark.parametrize("texto,dia", [
    ("domingo às 10h", 15), ("sábado 15h", 14), ("15/11 às 10h", 15),
    ("amanhã às 9h", 14), ("2026-11-16 08:00", 16), ("16 de novembro às 9h", 16),
    ("terça-feira 9h", 17),
])
def test_entender_dia(texto, dia):
    d, duvida = entender_dia(texto, SEXTA_10_30)
    assert duvida is None and d == date(2026, 11, dia)


@pytest.mark.parametrize("texto,trecho", [
    ("dia 15 às 10h", "mês"), ("semana que vem às 10h", "data"),
    ("sábado da semana que vem 10h", "data"), ("próximo sábado 10h", "data"),
    ("sexta às 15h", "hoje"),
])
def test_dia_ambiguo_pergunta(texto, trecho):
    d, duvida = entender_dia(texto, SEXTA_10_30)
    assert d is None and duvida and trecho in duvida


def test_sabado_quando_hoje_ja_e_sabado_a_tarde():
    d, duvida = entender_dia("sábado às 10h", SABADO_14_00)
    assert d is None and "14/11" in duvida and "21/11" in duvida


@pytest.mark.parametrize("texto,h,m", [
    ("15h", 15, 0), ("10h30", 10, 30), ("às 14", 14, 0), ("12/11 às 15h", 15, 0),
    ("3 da tarde", 15, 0), ("às 9", 9, 0), ("2026-11-16 08:00", 8, 0), ("07:30", 7, 30),
])
def test_entender_hora(texto, h, m):
    hora, duvida = entender_hora(texto)
    assert duvida is None and hora == time(h, m)


@pytest.mark.parametrize("texto", ["às 3", "sábado 3h", "às 5"])
def test_hora_ambigua_pergunta(texto):
    hora, duvida = entender_hora(texto)
    assert hora is None and "tarde" in duvida


def test_sem_hora():
    assert entender_hora("sábado") == (None, None)


# ---------------------------------------------------------------- a ferramenta
@pytest.fixture
def sexta_10_30(monkeypatch):
    monkeypatch.setattr(relogio, "agora_utc", lambda: L(13, 10, 30))


def _agendar(texto, tipo="visita", lead="h14-a", loja=1):
    return agendar_visita.func(nome_cliente="Ana", tipo=tipo, data_hora=texto,
                               lead_id=lead, loja_id=loja)


def _agendamentos(lead, loja=1):
    con = banco.conectar()
    try:
        return [r[0] for r in con.execute(
            "SELECT data_hora FROM agendamentos WHERE loja_id = ? AND lead_id = ?", (loja, lead))]
    finally:
        con.close()


def test_domingo_sem_hora_diz_que_fecha(lojas_e2, sexta_10_30):
    r = _agendar("domingo")
    assert r.startswith("NÃO AGENDADO") and "fechada" in r


def test_domingo_nao_agenda(lojas_e2, sexta_10_30):
    r = _agendar("domingo às 10h")
    assert r.startswith("NÃO AGENDADO") and "fechada" in r and "domingo" in r
    assert _agendamentos("h14-a") == []


def test_sabado_15h_nao_agenda_e_diz_o_horario(lojas_e2, sexta_10_30):
    r = _agendar("sábado às 15h")
    assert r.startswith("NÃO AGENDADO") and "13:00" in r and "Não diga que agendou" in r
    assert _agendamentos("h14-a") == []


def test_borda_visita_e_ligacao(lojas_e2, sexta_10_30):
    assert "12:30" in _agendar("sábado 12h45")
    assert _agendar("sábado 12h45", tipo="ligacao", lead="h14-l").startswith("Agendamento confirmado")


def test_dentro_grava_a_data_resolvida(lojas_e2, sexta_10_30):
    r = _agendar("sábado 12h30")
    assert r.startswith("Agendamento confirmado") and "sábado, 14/11, às 12:30" in r
    assert _agendamentos("h14-a") == ["sábado, 14/11, às 12:30"]


def test_amanha_vira_data(lojas_e2, sexta_10_30):
    assert _agendar("amanhã às 10h", lead="h14-am").startswith("Agendamento confirmado")
    assert _agendamentos("h14-am") == ["sábado, 14/11, às 10:00"]


def test_horario_que_ja_passou(lojas_e2, sexta_10_30):
    r = _agendar("hoje às 9h")
    assert r.startswith("NÃO AGENDADO") and "já passou" in r


def test_faltou_a_hora(lojas_e2, sexta_10_30):
    r = _agendar("sábado de manhã cedinho")
    assert r.startswith("NÃO AGENDADO") and "faltou a hora" in r


def test_hora_ambigua_nao_agenda(lojas_e2, sexta_10_30):
    r = _agendar("sábado às 3")
    assert r.startswith("NÃO AGENDADO") and "confirmar" in r and "não escolha" in r
    assert _agendamentos("h14-a") == []


def test_dia_sem_mes_nao_agenda(lojas_e2, sexta_10_30):
    r = _agendar("dia 15 às 10h")
    assert r.startswith("NÃO AGENDADO") and "mês" in r


def test_dia_de_hoje_pelo_nome_pergunta(lojas_e2, sexta_10_30):
    r = _agendar("sexta às 15h")
    assert r.startswith("NÃO AGENDADO") and "13/11" in r and "20/11" in r


def test_remarcar_para_horario_fechado_nao_apaga_o_antigo(lojas_e2, sexta_10_30):
    assert _agendar("sábado 10h", lead="h14-r").startswith("Agendamento confirmado")
    assert _agendar("domingo 10h", lead="h14-r").startswith("NÃO AGENDADO")
    assert _agendamentos("h14-r") == ["sábado, 14/11, às 10:00"]


def test_loja_2_com_horario_padrao_aceita_sabado_15h(lojas_e2, sexta_10_30):
    assert _agendar("sábado às 15h", lead="h14-2", loja=2).startswith("Agendamento confirmado")


# ---------------------------------------------------------------- rodada com IA
def test_rodada_h14_fixa_o_relogio_da_ferramenta():
    for nome in ("test_h14_visita_domingo", "test_h14_visita_sabado_15h",
                 "test_h14_visita_amanha_grava_data", "test_h14_visita_hora_ambigua"):
        assert "_fixar_relogio_da_ferramenta" in inspect.getsource(getattr(e25, nome))

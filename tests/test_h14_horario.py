"""
H14 (offline, sem Gemini): visita só dentro do expediente do dia e
espera cortada no fechamento. Horário da loja 1: dias úteis 08:00-18:00,
sábado 08:00-13:00, domingo fechado. Novembro de 2026: 13 = sexta,
14 = sábado, 15 = domingo, 16 = segunda. Fuso America/Recife (UTC-3).
"""
from datetime import date, datetime, time, timedelta, timezone
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

RECIFE = ZoneInfo("America/Recife")
HORARIO = {"0": "08:00-18:00", "1": "08:00-18:00", "2": "08:00-18:00",
           "3": "08:00-18:00", "4": "08:00-18:00", "5": "08:00-13:00"}
LOJA = {"fuso": "America/Recife", "atendimento.horario_semana": HORARIO}
LOJA_ANTIGA = {"fuso": "America/Recife", "atendimento.horario_humano": "09:00-18:00",
               "atendimento.dias_humano": [0, 1, 2, 3, 4, 5]}
HOJE = date(2026, 11, 13)          # sexta


def L(dia, h, m=0):
    """Hora de Recife em novembro de 2026, convertida para UTC."""
    return datetime(2026, 11, dia, h, m, tzinfo=RECIFE).astimezone(timezone.utc)


# ---------------------------------------------------------------- espera
@pytest.mark.parametrize("desde,agora,esperado", [
    (L(13, 17, 50), L(13, 21, 0), 10),    # sexta: fecha 18:00
    (L(14, 12, 50), L(14, 14, 0), 10),    # sábado: fecha 13:00
    (L(13, 17, 50), L(16, 8, 5), 5),      # atravessou o fim de semana (regra aceita)
    (L(13, 17, 50), L(16, 7, 0), 0),      # segunda antes de abrir
    (L(15, 10, 0), L(15, 11, 0), 0),      # domingo: loja fechada
])
def test_espera_cortada_no_fechamento(desde, agora, esperado):
    assert relogio.minutos_no_expediente(LOJA, desde, agora) == esperado


def test_formato_antigo_tambem_corta():
    assert relogio.minutos_no_expediente(LOJA_ANTIGA, L(13, 17, 50), L(13, 21, 0)) == 10


@pytest.mark.parametrize("agora", [L(13, 8, 30), L(13, 12, 0), L(13, 17, 59), L(14, 12, 59)])
def test_dentro_do_expediente_nada_muda(agora):
    """Avisos aos vendedores só disparam dentro do horário: ali a conta é a mesma de antes."""
    assert relogio.minutos_no_expediente(LOJA, agora - timedelta(minutes=25), agora) == 25


# ---------------------------------------------------------------- horário marcado
@pytest.mark.parametrize("dia,h,m,duracao,esperado", [
    (15, 10, 0, 30, "fechada"),     # domingo
    (14, 15, 0, 30, "13:00"),       # sábado depois do fechamento
    (14, 12, 45, 30, "12:30"),      # borda: terminaria 13:15
    (16, 7, 59, 30, "08:00"),       # antes de abrir
    (14, 12, 30, 30, None),         # termina 13:00 em ponto: cabe
    (14, 12, 45, 0, None),          # ligação não tem duração
    (16, 8, 0, 30, None),
])
def test_conferir_horario_marcado(dia, h, m, duracao, esperado):
    motivo = relogio.conferir_horario_marcado(LOJA, date(2026, 11, dia), time(h, m), duracao)
    if esperado is None:
        assert motivo is None
    else:
        assert motivo and esperado in motivo, motivo


# ---------------------------------------------------------------- o código entende o dia
@pytest.mark.parametrize("texto,dia", [
    ("domingo às 10h", 15), ("sábado 15h", 14), ("sexta 9h", 20), ("sexta 17h", 13),
    ("15/11 às 10h", 15), ("amanhã às 9h", 14), ("2026-11-16 08:00", 16),
])
def test_entender_dia(texto, dia):
    assert entender_dia(texto, HOJE, entender_hora(texto), time(10, 30)) == date(2026, 11, dia)


def test_dia_que_nao_da_pra_entender():
    assert entender_dia("dia 14 às 10h", HOJE, time(10), time(10, 30)) is None


@pytest.mark.parametrize("texto,h,m", [
    ("15h", 15, 0), ("10h30", 10, 30), ("às 14", 14, 0), ("12/11 às 15h", 15, 0),
    ("3 da tarde", 15, 0), ("2026-11-16 08:00", 8, 0),
])
def test_entender_hora(texto, h, m):
    assert entender_hora(texto) == time(h, m)


def test_sem_hora():
    assert entender_hora("sábado") is None


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
        return [dict(r) for r in con.execute(
            "SELECT data_hora, tipo FROM agendamentos WHERE loja_id = ? AND lead_id = ?",
            (loja, lead))]
    finally:
        con.close()


def test_domingo_nao_agenda(lojas_e2, sexta_10_30):
    r = _agendar("domingo às 10h")
    assert r.startswith("NÃO AGENDADO") and "fechada" in r and "domingo" in r
    assert _agendamentos("h14-a") == []


def test_sabado_15h_nao_agenda_e_diz_o_horario(lojas_e2, sexta_10_30):
    r = _agendar("sábado às 15h")
    assert r.startswith("NÃO AGENDADO") and "13:00" in r and "Não diga que agendou" in r
    assert _agendamentos("h14-a") == []


def test_borda_visita_e_ligacao(lojas_e2, sexta_10_30):
    r = _agendar("sábado 12h45")
    assert r.startswith("NÃO AGENDADO") and "12:30" in r
    r = _agendar("sábado 12h45", tipo="ligacao", lead="h14-l")
    assert r.startswith("Agendamento confirmado")


def test_dentro_do_expediente_agenda(lojas_e2, sexta_10_30):
    r = _agendar("sábado 12h30")
    assert r.startswith("Agendamento confirmado")
    assert "Dia conferido: sábado, 14/11, às 12:30" in r
    assert len(_agendamentos("h14-a")) == 1


def test_horario_que_ja_passou(lojas_e2, sexta_10_30):
    r = _agendar("hoje às 9h")
    assert r.startswith("NÃO AGENDADO") and "já passou" in r


def test_faltou_a_hora(lojas_e2, sexta_10_30):
    r = _agendar("sábado de manhã cedinho")
    assert r.startswith("NÃO AGENDADO") and "faltou a hora" in r
    assert _agendamentos("h14-a") == []


def test_remarcar_para_horario_fechado_nao_apaga_o_antigo(lojas_e2, sexta_10_30):
    assert _agendar("sábado 10h", lead="h14-r").startswith("Agendamento confirmado")
    assert _agendar("domingo 10h", lead="h14-r").startswith("NÃO AGENDADO")
    linhas = _agendamentos("h14-r")
    assert len(linhas) == 1 and linhas[0]["data_hora"] == "sábado 10h"


def test_loja_2_com_horario_padrao_aceita_sabado_15h(lojas_e2, sexta_10_30):
    r = _agendar("sábado às 15h", lead="h14-2", loja=2)
    assert r.startswith("Agendamento confirmado"), r

"""
Furo 13 (validação do E2-5): horário de atendimento por dia da semana.

Hoje a configuração guarda UM horário para todos os dias abertos
("09:00-18:00" + lista de dias). Nenhuma loja consegue dizer "sábado fecha
às 13h", e o Léo pode dar ao mesmo cliente dois horários diferentes
(configuração x texto de políticas).

Correção proposta (docs/correcoes/horario_por_dia.md, precisa do analista):
chave nova "atendimento.horario_semana" = {dia: "HH:MM-HH:MM"}, dia
ausente = fechado. Sem a chave nova, vale o formato antigo (lojas que já
existem não quebram).

Os testes usam uma loja MONTADA AQUI, sem banco e sem a loja 1: a regra tem
que valer para qualquer loja nova cadastrada pelo painel.

Marcação:
  - CONTROLES (sem marca): passam hoje e têm que continuar passando.
  - FURO 13 (xfail strict): falham hoje. Quando a correção entrar em app/,
    o pytest avisa (XPASS strict) para tirar a marca.
Datas usadas: 07/11/2026 é sábado, 08/11 domingo, 09/11 segunda.
Fuso America/Recife = UTC-3 (10h local = 13h UTC).
"""
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import relogio

# Nome PROPOSTO da chave nova. Se o analista escolher outro, troca só aqui.
CHAVE_SEMANA = "atendimento.horario_semana"


def loja_formato_antigo():
    """Loja como as de hoje: um horário só, segunda a sábado."""
    return {
        "fuso": "America/Recife",
        "atendimento.horario_humano": "09:00-18:00",
        "atendimento.dias_humano": [0, 1, 2, 3, 4, 5],
    }


def loja_com_horario_por_dia():
    """Loja real típica: dias úteis 8h-18h, sábado 8h-13h, domingo fechado.
    Mantém também o formato antigo, como ficaria uma loja migrada."""
    loja = loja_formato_antigo()
    loja[CHAVE_SEMANA] = {
        "0": "08:00-18:00", "1": "08:00-18:00", "2": "08:00-18:00",
        "3": "08:00-18:00", "4": "08:00-18:00", "5": "08:00-13:00",
    }
    return loja


def utc(ano, mes, dia, hora, minuto=0):
    return datetime(ano, mes, dia, hora, minuto, tzinfo=timezone.utc)


SEGUNDA_10H = utc(2026, 11, 9, 13)      # 10h00 em Recife
DOMINGO_10H = utc(2026, 11, 8, 13)      # 10h00 em Recife
SABADO_08H30 = utc(2026, 11, 7, 11, 30) # 08h30 em Recife
SABADO_14H = utc(2026, 11, 7, 17)       # 14h00 em Recife


def furo13(motivo):
    return pytest.mark.xfail(strict=True, reason=f"furo 13: {motivo}")


# ----------------------------------------------------------------------
# CONTROLES: o formato antigo não pode quebrar
# ----------------------------------------------------------------------

def test_formato_antigo_segunda_10h_aberta():
    assert relogio.no_horario(loja_formato_antigo(), SEGUNDA_10H)


def test_formato_antigo_domingo_fechada():
    assert not relogio.no_horario(loja_formato_antigo(), DOMINGO_10H)


def test_horario_por_dia_segunda_10h_aberta():
    assert relogio.no_horario(loja_com_horario_por_dia(), SEGUNDA_10H)


# ----------------------------------------------------------------------
# FURO 13: o sábado diferente não existe para o sistema
# ----------------------------------------------------------------------

@furo13("sábado 14h conta como aberto (usa 09:00-18:00 para todo dia)")
def test_sabado_14h_fechada():
    assert not relogio.no_horario(loja_com_horario_por_dia(), SABADO_14H)


@furo13("sábado 8h30 conta como fechado (abertura única às 9h)")
def test_sabado_08h30_aberta():
    assert relogio.no_horario(loja_com_horario_por_dia(), SABADO_08H30)


@furo13("a espera do vendedor no sábado é contada a partir das 9h, não das 8h")
def test_abertura_do_sabado_e_8h():
    assert relogio.abertura_do_dia(loja_com_horario_por_dia(), SABADO_14H) == utc(2026, 11, 7, 11)


@furo13("não existe função que diga o horário de um dia específico")
def test_horario_do_dia():
    loja = loja_com_horario_por_dia()
    assert relogio.horario_do_dia(loja, 5) == ("08:00", "13:00")
    assert relogio.horario_do_dia(loja, 6) is None


@furo13("não existe texto de horário por dia para o Léo")
def test_descricao_para_o_leo_tem_sabado_e_domingo():
    texto = relogio.descrever_horarios(loja_com_horario_por_dia()).lower()
    assert "sábado" in texto and "13" in texto
    assert "domingo" in texto and "fechad" in texto


@furo13("a configuração não aceita horário por dia (painel não consegue gravar)")
def test_configuracao_aceita_horario_por_dia():
    from app.lojas import EDITAVEIS
    assert CHAVE_SEMANA in EDITAVEIS

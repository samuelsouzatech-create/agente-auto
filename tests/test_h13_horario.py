"""
H13: horário por dia da semana (furo 13), sem Gemini.

Datas: 13/11/2026 é sexta, 14/11 sábado, 15/11 domingo, 16/11 segunda.
Loja 1 (decisão do analista): dias úteis 08:00-18:00, sábado 08:00-13:00,
domingo fechado. O status ("Agora a loja está ...") é calculado pelo código;
o Léo só repete.
"""
import os
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import relogio
from app.lojas import EDITAVEIS, PADROES, Loja, _mesclar

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RECIFE = ZoneInfo("America/Recife")
CHAVE = "atendimento.horario_semana"
SEMANA_LOJA_1 = {"0": "08:00-18:00", "1": "08:00-18:00", "2": "08:00-18:00",
                 "3": "08:00-18:00", "4": "08:00-18:00", "5": "08:00-13:00"}
DESCRICAO_LOJA_1 = ("de segunda a sexta, das 08:00 às 18:00; sábado, das 08:00 às 13:00; "
                    "domingo, fechado")


def loja(config=None):
    return Loja(id=1, nome="Seminovos Boa Viagem", segmento="veiculos",
                config=_mesclar(PADROES, config or {}), versao_config=1, ativo=True)


def loja_1():
    return loja({"cidade": "Recife", "atendimento": {"horario_semana": dict(SEMANA_LOJA_1)}})


def em(dia, hora, minuto=0):
    """Hora de Recife em novembro de 2026, devolvida em UTC."""
    return datetime(2026, 11, dia, hora, minuto, tzinfo=RECIFE).astimezone(timezone.utc)


# ------------------------------------------------------------ texto e status

def test_descricao_loja_1():
    assert relogio.descrever_horarios(loja_1()) == DESCRICAO_LOJA_1


def test_descricao_formato_antigo_continua():
    assert relogio.descrever_horarios(loja()) == (
        "de segunda a sábado, das 09:00 às 18:00; domingo, fechado")


@pytest.mark.parametrize("dia,hora,minuto,esperado", [
    (13, 10, 30, "Agora a loja está ABERTA até 18:00."),
    (13, 21, 30, "Agora a loja está FECHADA; abre amanhã, sábado, às 08:00."),
    (14, 9, 0, "Agora a loja está ABERTA até 13:00."),
    (14, 14, 0, "Agora a loja está FECHADA; abre na segunda-feira, às 08:00."),
    (15, 10, 0, "Agora a loja está FECHADA; abre amanhã, segunda-feira, às 08:00."),
    (13, 7, 0, "Agora a loja está FECHADA; abre hoje, às 08:00."),
])
def test_status(dia, hora, minuto, esperado):
    assert relogio.status_agora(loja_1(), em(dia, hora, minuto)) == esperado


def test_status_formato_antigo_sabado_14h():
    assert relogio.status_agora(loja(), em(14, 14)) == "Agora a loja está ABERTA até 18:00."


# ------------------------------------------------------------ espera do vendedor

def test_espera_no_domingo_nao_conta():
    assert relogio.minutos_no_expediente(loja_1(), em(14, 12), em(15, 10)) == 0


def test_espera_de_sabado_conta_desde_as_8h():
    assert relogio.minutos_no_expediente(loja_1(), em(14, 7), em(14, 8, 30)) == 30


# ------------------------------------------------------------ cadastro

def test_validador_aceita_e_organiza():
    assert EDITAVEIS[CHAVE]({5: "08:00-13:00", "0": " 08:00-18:00 "}) == {
        "0": "08:00-18:00", "5": "08:00-13:00"}


def test_validador_none_volta_ao_horario_unico():
    assert EDITAVEIS[CHAVE](None) is None


def test_validador_recusa_meia_noite():
    with pytest.raises(ValueError, match="meia-noite"):
        EDITAVEIS[CHAVE]({"4": "18:00-02:00"})


@pytest.mark.parametrize("valor", [{"7": "08:00-18:00"}, {"0": "8h-18h"}, {}])
def test_validador_recusa_invalidos(valor):
    with pytest.raises(ValueError):
        EDITAVEIS[CHAVE](valor)


def test_tela_ida_e_volta():
    from app.config_tela import campo, da_tela, para_tela
    c = campo(CHAVE)
    texto = para_tela(c, SEMANA_LOJA_1)
    assert texto == ("Seg 08:00-18:00; Ter 08:00-18:00; Qua 08:00-18:00; Qui 08:00-18:00; "
                     "Sex 08:00-18:00; Sáb 08:00-13:00")
    assert da_tela(c, texto) == SEMANA_LOJA_1
    assert da_tela(c, "") is None
    with pytest.raises(ValueError):
        da_tela(c, "Segunda 8h")


# ------------------------------------------------------------ prompt do Léo

def test_prompt_traz_horario_e_status():
    from app.core import montagem
    p = montagem.montar_prompt(loja_1(), [], em(13, 21, 30).astimezone(RECIFE))
    assert f"Atendimento com vendedores: {DESCRICAO_LOJA_1}." in p
    assert "STATUS AGORA: Agora a loja está FECHADA; abre amanhã, sábado, às 08:00." in p
    assert not hasattr(montagem, "descrever_dias")


def test_prompt_sabado_depois_das_13():
    from app.core import montagem
    p = montagem.montar_prompt(loja_1(), [], em(14, 14).astimezone(RECIFE))
    assert "STATUS AGORA: Agora a loja está FECHADA; abre na segunda-feira, às 08:00." in p


def test_prompt_formato_antigo():
    from app.core import montagem
    p = montagem.montar_prompt(loja(), [], em(13, 10, 30).astimezone(RECIFE))
    assert "Atendimento com vendedores: de segunda a sábado, das 09:00 às 18:00" in p
    assert "STATUS AGORA: Agora a loja está ABERTA até 18:00." in p


# ------------------------------------------------------------ janela de envio

def test_envio_respeita_abertura_do_dia():
    from app import elegibilidade as e
    l = loja_1()                                      # janela padrão 09:00-19:00
    assert e.no_horario_de_envio(l, em(14, 10))
    assert not e.no_horario_de_envio(l, em(14, 13, 30))   # sábado: loja fechou às 13
    assert not e.no_horario_de_envio(l, em(15, 10))       # domingo
    assert not e.no_horario_de_envio(l, em(13, 18, 30))   # sexta: loja fecha às 18


def test_proxima_abertura_do_envio():
    from app import elegibilidade as e
    assert e.proxima_abertura(loja_1(), em(14, 13, 30)) == em(16, 9)


# ------------------------------------------------------------ API, tela antiga, documento

def test_api_campos_de_horario():
    from app.api_painel.eu import campos_de_horario
    campos = campos_de_horario(loja_1())
    assert campos["horario_texto"] == DESCRICAO_LOJA_1[:1].upper() + DESCRICAO_LOJA_1[1:]
    dias = campos["horario"]
    assert [d["dia"] for d in dias] == list(range(7))
    assert dias[5] == {"dia": 5, "dia_texto": "Sábado", "abre": "08:00", "fecha": "13:00",
                       "fechado": False}
    assert dias[6]["fechado"] and dias[6]["abre"] is None and dias[6]["fecha"] is None


def test_fila_antiga_usa_a_conta_unica():
    with open(os.path.join(RAIZ, "paginas", "handoff.py"), encoding="utf-8") as f:
        texto = f.read()
    assert "minutos_no_expediente" in texto
    assert "datetime.now" not in texto


def test_documento_de_politicas_nao_repete_horario():
    with open(os.path.join(RAIZ, "conhecimento", "troca_garantia_horario.txt"),
              encoding="utf-8") as f:
        texto = f.read()
    assert not re.search(r"\b\d{1,2}h\b|\b\d{2}:\d{2}\b", texto)
    assert "cadastro da loja" in texto

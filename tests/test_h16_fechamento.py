"""
Bloco H16 (offline, sem IA): fechamento da frente de testes com o Gemini.
1) agendar_visita funciona a qualquer hora; o Léo nunca diz que a equipe
   precisa confirmar (regra no guia + detector de aviso).
2) dúvida de "às 3": a ferramenta pergunta só pela alternativa que cabe no
   expediente daquele dia.
3) "registro seu interesse para a equipe verificar" conta como promessa.
4) gênero x senhor/senhora medido em todos os casos com nome (só aviso).
"""
import copy
import inspect
import os
import sys
from datetime import date, datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import AIMessage

PASTA_TESTES = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PASTA_TESTES)
sys.path.insert(0, os.path.dirname(PASTA_TESTES))

try:
    import tests.test_comportamento_etapa2_api as e25
except ImportError:
    import test_comportamento_etapa2_api as e25

import avisos_texto  # noqa: E402
from app import relogio  # noqa: E402
from app.core import montagem  # noqa: E402
from app.lojas import PADROES  # noqa: E402
from tools.agendar_visita import _duvida_de_hora, agendar_visita  # noqa: E402

lojas_e2 = e25.lojas_e2
if hasattr(e25, "banco_temporario"):
    banco_temporario = e25.banco_temporario

RECIFE = ZoneInfo("America/Recife")
SEGUNDA_1030 = datetime(2026, 11, 16, 13, 30, tzinfo=timezone.utc)   # 10:30 em Recife
REGRA = "inclusive quando a loja está FECHADA"


# ---------------------------------------------------------------- 1) qualquer hora
def test_guia_diz_que_agenda_a_qualquer_hora():
    d = montagem.DESCRICOES["agendar_visita"]
    assert REGRA in d and "precisa confirmar" in d
    assert "EXATAMENTE como o cliente falou" in d          # regra do H15 continua


def _loja(agendamento):
    config = copy.deepcopy(PADROES)
    config.setdefault("modulos", {})["agendamento"] = agendamento
    return SimpleNamespace(id=1, nome="Loja Teste", segmento="veiculos", config=config)


def test_regra_so_vai_para_loja_com_agendamento():
    for ligado in (True, False):
        loja = _loja(ligado)
        prompt = montagem.montar_prompt(loja, montagem.ferramentas_da_loja(loja),
                                        datetime(2026, 11, 16, 21, 30))
        assert (REGRA in prompt) is ligado


AGENDA = avisos_texto.AGENDA_SEM_CONFIRMAR


def _tem(texto, rotulo):
    return any(a.startswith(rotulo) for a in avisos_texto.avisos_de_texto(texto))


@pytest.mark.parametrize("texto", [
    "Infelizmente, a equipe não consegue confirmar o agendamento neste momento.",
    "O vendedor precisa confirmar o horário com o senhor.",
    "Sua visita fica sujeita à confirmação da equipe.",
])
def test_detector_agenda_precisa_confirmar(texto):
    assert _tem(texto, AGENDA)


@pytest.mark.parametrize("texto", [
    "Infelizmente não conseguimos agendar no domingo: a loja fica fechada.",
    "Agendamento confirmado: sábado, 21/11, às 10:00.",
    "Pode me confirmar o melhor horário para a visita?",
])
def test_detector_agenda_nao_dispara_a_toa(texto):
    assert not _tem(texto, AGENDA)


# ---------------------------------------------------------------- 3) contato
@pytest.mark.parametrize("texto", [
    "Posso registrar o seu interesse para que o pessoal da equipe possa verificar outras opções?",
    "Vou anotar seu interesse para a equipe verificar a disponibilidade.",
])
def test_registro_para_equipe_verificar_e_promessa(texto):
    assert "contato" in avisos_texto.promessas_de_contato(texto)


@pytest.mark.parametrize("texto", [
    "Na visita, traga o carro para o vendedor avaliar a troca.",
    "Vou registrar seu interesse no Onix.",
])
def test_sem_promessa_de_contato(texto):
    assert "contato" not in avisos_texto.promessas_de_contato(texto)


# ---------------------------------------------------------------- 2) dúvida de hora
@pytest.fixture
def segunda_10_30(monkeypatch):
    monkeypatch.setattr(relogio, "agora_utc", lambda: SEGUNDA_1030)


def _agendar(texto, lead="h16-a"):
    return agendar_visita.func(nome_cliente="Paula", tipo="visita", data_hora=texto,
                               lead_id=lead, loja_id=1)


def _agendamentos(lead):
    return e25.ler("SELECT data_hora FROM agendamentos WHERE loja_id = 1 AND lead_id = ?", (lead,))


def test_quarta_as_3_pergunta_so_pelas_15h(lojas_e2, segunda_10_30):
    r = _agendar("quarta às 3")
    assert r.startswith("NÃO AGENDADO") and "seria às 15h" in r and "da manhã" not in r
    assert _agendamentos("h16-a") == []


def test_quarta_as_1_pergunta_so_pelas_13h(lojas_e2, segunda_10_30):
    r = _agendar("quarta às 1", lead="h16-b")
    assert r.startswith("NÃO AGENDADO") and "seria às 13h" in r and "da manhã" not in r


def test_sabado_as_3_nenhuma_cabe_recusa_com_horario(lojas_e2, segunda_10_30):
    r = _agendar("sábado às 3", lead="h16-c")
    assert r.startswith("NÃO AGENDADO") and "13:00" in r and "seria" not in r
    assert _agendamentos("h16-c") == []


def test_as_duas_cabem_continua_perguntando_as_duas():
    loja = {"fuso": "America/Recife", "atendimento.horario_semana": {"2": "00:00-23:59"}}
    agora = datetime(2026, 11, 16, 10, 30, tzinfo=RECIFE)
    duvida, recusa = _duvida_de_hora(loja, "visita", "quarta às 3", date(2026, 11, 18), agora)
    assert recusa is None and "da manhã" in duvida and "15h" in duvida


# ---------------------------------------------------------------- casos com IA
def test_caso_com_ia_sabado_15h_confere_a_chamada():
    assert "agendar_visita" in inspect.getsource(e25.test_h14_visita_sabado_15h)


def test_genero_medido_em_todos_os_casos():
    assert "avisos_genero_h16(conversas)" in inspect.getsource(e25.avaliar_caso)


# ---------------------------------------------------------------- 4) gênero (medida)
def _conversa(fala, resposta):
    c = e25.Conversa(loja_id=1, lead_id="x", falas=[fala])
    c.novas_por_turno = [[AIMessage(content=resposta)]]
    return c


@pytest.mark.parametrize("fala, resposta", [
    ("Oi, sou a Paula, queria ver o Onix", "Claro, o senhor pode vir no sábado."),
    ("Aqui é o Carlos", "Perfeito, a senhora pode vir quarta."),
    ("Meu nome é Alex", "Certo, a senhora prefere de manhã?"),
    ("Sou a Paula", "Olá, senhorita Paula!"),
])
def test_genero_errado_vira_aviso(fala, resposta):
    assert e25.avisos_genero_h16(_conversa(fala, resposta))


@pytest.mark.parametrize("fala, resposta", [
    ("Sou a Paula", "Claro, a senhora pode vir no sábado."),
    ("Aqui é o Carlos", "Perfeito, o senhor pode vir quarta."),
    ("quero ver o Onix", "Claro, o senhor pode vir no sábado."),
    ("Moro em São Paulo", "Claro, o senhor pode vir no sábado."),
])
def test_genero_certo_ou_sem_nome_nao_avisa(fala, resposta):
    assert e25.avisos_genero_h16(_conversa(fala, resposta)) == []

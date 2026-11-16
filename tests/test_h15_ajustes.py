"""
Bloco H15 (offline, sem IA): ajustes finais do H14.
1) agendar_visita recebe o dia e a hora como o cliente falou (regra no guia).
2) registrar_lead resolve o dia do prazo com o mesmo entender_dia.
3) oferta de contato sem chamado conta como promessa.
4) tom formal: senhor/senhora só com gênero claro.
"""
import copy
import importlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

PASTA_TESTES = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PASTA_TESTES)
sys.path.insert(0, os.path.dirname(PASTA_TESTES))

import banco  # noqa: E402
import avisos_texto  # noqa: E402
import app.lojas  # noqa: E402
from app import relogio  # noqa: E402
from app.core import montagem  # noqa: E402
from app.lojas import PADROES  # noqa: E402
from tools import registrar_lead  # noqa: E402

prazo_com_data = importlib.import_module("tools.registrar_lead").prazo_com_data
RAIZ = Path(PASTA_TESTES).parent
SEGUNDA_1030 = datetime(2026, 11, 16, 13, 30, tzinfo=timezone.utc)   # 10:30 em Recife
FORMAL = "formal e respeitoso: trata o cliente por senhor ou senhora"


@pytest.fixture
def relogio_segunda(monkeypatch):
    monkeypatch.setattr(relogio, "agora_utc", lambda: SEGUNDA_1030)
    monkeypatch.setattr(app.lojas, "carregar_loja", lambda loja_id: {"fuso": "America/Recife"})


# ---------------------------------------------------------------- 2) prazo
@pytest.mark.parametrize("prazo, esperado", [
    ("quer visitar amanhã às 10h", "quer visitar amanhã às 10h (terça-feira, 17/11)"),
    ("quer visitar depois de amanhã", "quer visitar depois de amanhã (quarta-feira, 18/11)"),
    ("quer visitar sábado", "quer visitar sábado (sábado, 21/11)"),
    ("quer visitar hoje à tarde", "quer visitar hoje à tarde (segunda-feira, 16/11)"),
])
def test_prazo_ganha_a_data(relogio_segunda, prazo, esperado):
    assert prazo_com_data(prazo, 1) == esperado


@pytest.mark.parametrize("prazo", [
    "quer visitar segunda",                       # hoje é segunda: hoje ou na próxima?
    "quer visitar semana que vem",
    "quer visitar na próxima sexta",
    "quer comprar este mês",
    "quer visitar dia 20",
    "quer visitar 20/11",                         # já tem a data
    "quer visitar amanhã (terça-feira, 17/11)",   # já resolvido
    "",
])
def test_prazo_fica_como_veio(relogio_segunda, prazo):
    assert prazo_com_data(prazo, 1) == prazo


def test_registrar_lead_grava_prazo_com_data(relogio_segunda):
    registrar_lead.invoke({"nome": "Paula", "interesse": "Onix", "prazo": "quer visitar amanhã às 10h",
                           "lead_id": "h15-prazo", "loja_id": 1})
    con = banco.conectar()
    try:
        linha = con.execute("SELECT prazo FROM leads WHERE loja_id = 1 AND lead_id = 'h15-prazo'").fetchone()
    finally:
        con.close()
    assert linha["prazo"] == "quer visitar amanhã às 10h (terça-feira, 17/11)"


# ---------------------------------------------------------------- 1) "às 3"
def test_guia_manda_passar_data_como_o_cliente_falou():
    d = montagem.DESCRICOES["agendar_visita"]
    assert "EXATAMENTE como o cliente falou" in d and '"quarta às 3"' in d and "15h" in d


def test_regra_nao_vai_para_loja_sem_agendamento():
    base = (RAIZ / "prompts" / "base.md").read_text(encoding="utf-8")
    assert "agendar_visita" not in base


def test_caso_com_ia_usa_dia_util_e_tem_genero():
    fonte = (RAIZ / "tests" / "test_comportamento_etapa2_api.py").read_text(encoding="utf-8")
    assert "Onix quarta às 3?" in fonte and "Onix sábado às 3?" not in fonte
    assert "def test_h15_tratamento_por_genero" in fonte


# ---------------------------------------------------------------- 3) detector
@pytest.mark.parametrize("texto", [
    "Prefere que eu registre o seu interesse para que o pessoal da equipe fale com você?",
    "Posso anotar seu interesse para que um vendedor te ligue?",
    "Registro o seu interesse para que o pessoal da equipe possa conversar com você sobre outras opções.",
])
def test_oferta_de_contato_conta_como_promessa(texto):
    assert "contato" in avisos_texto.promessas_de_contato(texto)


@pytest.mark.parametrize("texto", [
    "Para que a senhora conheça o carro, qual dia fica melhor?",
    "Para que eu possa ajudar, qual carro o senhor procura?",
    "Gostaria de agendar uma visita para conhecer o Onix?",
])
def test_frase_sem_promessa_nao_conta(texto):
    assert "contato" not in avisos_texto.promessas_de_contato(texto)


# ---------------------------------------------------------------- 4) tom e gênero
def _loja(tom=None):
    config = copy.deepcopy(PADROES)
    if tom:
        config["tom"] = tom
    return SimpleNamespace(id=1, nome="Loja Teste", segmento="veiculos", config=config)


def _prompt(loja):
    return montagem.montar_prompt(loja, montagem.ferramentas_da_loja(loja), datetime(2026, 11, 16, 10, 30))


def test_formal_so_usa_senhor_com_genero_claro():
    p = _prompt(_loja(FORMAL))
    assert "Gênero do cliente" in p and "Alex" in p and "chame pelo nome" in p
    assert '"o senhor" ou "a senhora" desde a primeira' in p      # regra do S7 continua


def test_tom_padrao_nao_ganha_regra_de_genero():
    assert "Gênero do cliente" not in _prompt(_loja())

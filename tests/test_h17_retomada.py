"""
Bloco H17 (offline, sem IA): "retomada: agora não" fora do horário.
Causa confirmada (experimento de 16/11): a descrição longa de agendar_visita
fazia o modelo leve deixar de chamar registrar_interesse com a loja fechada
(descrição longa 2/6, descrição do H13 6/6).
1) A descrição da ferramenta volta a ser curta; as regras de horário ficam
   no guia do prompt e na mensagem de recusa da própria ferramenta.
2) (a) O guia manda chamar registrar_interesse NESTA resposta.
3) (b) Os casos de retomada com IA conferem a chamada.
"""
import inspect
import os
import sys

PASTA_TESTES = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PASTA_TESTES)
sys.path.insert(0, os.path.dirname(PASTA_TESTES))

try:
    import tests.test_comportamento_etapa2_api as e25
except ImportError:
    import test_comportamento_etapa2_api as e25

from app.core import montagem  # noqa: E402
from tools.agendar_visita import agendar_visita  # noqa: E402


def test_descricao_da_ferramenta_e_curta():
    doc = agendar_visita.func.__doc__ or ""
    assert "NÃO AGENDADO" not in doc and "converta" not in doc
    assert len(doc) < 700


def test_regras_de_horario_continuam_no_guia():
    d = montagem.DESCRICOES["agendar_visita"]
    assert "EXATAMENTE como o cliente falou" in d
    assert "inclusive quando a loja está FECHADA" in d


def test_guia_manda_registrar_nesta_resposta():
    d = montagem.DESCRICOES["registrar_interesse"]
    assert "NESTA resposta" in d and "aberta ou fechada" in d
    assert "não pergunte se pode registrar" in d and "pediu_tempo" in d
    assert "Na dúvida, não use." in d


def test_casos_de_retomada_conferem_a_chamada():
    for nome in ("test_retomada_agora_nao", "test_retomada_ja_comprei_em_outro_lugar"):
        assert 'checar_chamou(c, "registrar_interesse")' in inspect.getsource(getattr(e25, nome))

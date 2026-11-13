"""
Bloco S6 (offline, sem Gemini): consertos dos avisos da rodada de 13/11.
- remarketing: fato inventado e vídeo são barrados; frases legítimas passam;
- prompts e mensagens de ferramenta sem prazo;
- detector de prazo com as palavras novas;
- só a ÚLTIMA mensagem do turno vai para o cliente.
"""
import asyncio
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))

from app.core import montagem  # noqa: E402
from app.filtro_remarketing import fato_inventado  # noqa: E402
from app.jobs.remarketing import _ORIENTACAO_DO_TOQUE, _limpar_texto  # noqa: E402
from tools.acionar_handoff import ORIENTACAO  # noqa: E402
from avisos_texto import FALHA_TECNICA, PRAZO, rotulos_de_texto  # noqa: E402

BARRA = [
    "Oi Rafael! Aquele Civic não está mais disponível, mas chegou um Corolla 2018 aqui na loja.",
    "Tenho uma opção parecida aqui que acabou de chegar e pode te interessar.",
    "Oi Carla! Consegui mais alguns detalhes sobre o Onix 2020, quer que eu te envie?",
    "O Corolla está impecável, quer ver?",
    "Temos novidade no estoque, quer dar uma olhada?",
    "Posso te enviar um vídeo detalhado dele.",
    "Chegaram uns carros novos aqui na loja.",
    "O Argo está em ótimo estado, vem ver!",
]

PASSA = [
    "Oi, o Onix ainda está disponível, quer ver as fotos?",
    "Oi Carla, o Onix 2020 continua disponível. Quer marcar uma visita?",
    "Oi Carla, tudo bem? Conseguiu conversar com seu marido sobre o Onix?",
    "Oi Marcos! Chegou a ver as fotos do HB20?",
    "Oi Paulo, tem alguma novidade sobre a sua decisão?",
    "Oi Fernanda, passando para saber se você conseguiu organizar sua agenda.",
]


@pytest.mark.parametrize("texto", BARRA)
def test_remarketing_barra_fato_inventado(texto):
    assert fato_inventado(texto)
    assert _limpar_texto(texto) == ""


@pytest.mark.parametrize("texto", PASSA)
def test_remarketing_deixa_passar_frase_legitima(texto):
    assert not fato_inventado(texto)
    assert _limpar_texto(texto) == texto


def test_redator_sem_pedido_de_novidade():
    assert "fotos" not in _ORIENTACAO_DO_TOQUE[1]
    assert "opção parecida" not in _ORIENTACAO_DO_TOQUE[2]
    fonte = (RAIZ / "app" / "jobs" / "remarketing.py").read_text(encoding="utf-8")
    assert "Não invente novidade" in fonte and "Não ofereça vídeo" in fonte


def test_textos_da_espera_sem_prazo():
    for texto in montagem.TEXTOS_EM_ESPERA.values():
        baixo = texto.lower()
        assert "já já" not in baixo and "em breve" not in baixo
    assert "consultar_estoque" in montagem.TEXTO_EM_ESPERA_QUIETO
    assert "acionar_handoff de novo" in montagem.TEXTO_EM_ESPERA_QUIETO


def test_orientacao_do_handoff_sem_prazo():
    assert "vai falar com ele por aqui" in ORIENTACAO
    assert "Não prometa prazo" in ORIENTACAO
    assert "continuar com ele" not in ORIENTACAO


def test_regras_base_sem_prazo_e_sem_falha_tecnica():
    base = (RAIZ / "prompts" / "base.md").read_text(encoding="utf-8")
    assert "pessoal das vendas, já te chamam aqui" not in base
    assert "diga apenas que não conseguiu buscar" not in base
    assert "PRAZO (regra dura)" in base
    assert "Nunca ofereça vídeo" in base
    assert '"equipe técnica"' in base


def test_ferramenta_fora_nao_conta_falha_ao_cliente():
    fonte = (RAIZ / "app" / "core" / "agent.py").read_text(encoding="utf-8")
    assert "FERRAMENTA_FORA" in fonte
    assert "não está disponível nesta loja agora. \" + FERRAMENTA_FORA" in fonte


@pytest.mark.parametrize("texto", [
    "Logo alguém da equipe entra em contato.",
    "Vou ver isso agora mesmo com o pessoal.",
    "Eles vão resolver isso o quanto antes.",
])
def test_detector_pega_palavras_de_tempo_novas(texto):
    assert PRAZO in rotulos_de_texto(texto)


@pytest.mark.parametrize("texto", [
    "O pessoal da equipe vai falar com você por aqui.",
    "Fora do horário, o pessoal retoma no próximo horário de atendimento.",
])
def test_formula_sem_tempo_nao_e_prazo(texto):
    assert PRAZO not in rotulos_de_texto(texto)


def test_detector_pega_nao_consegui_buscar():
    assert FALHA_TECNICA in rotulos_de_texto("Não consegui buscar essa informação agora.")


def test_so_a_ultima_mensagem_do_turno_vai_para_o_cliente(monkeypatch):
    from app.core import turno
    salvas = []
    for nome, valor in {
        "porta_fechada": lambda *a, **k: False,
        "_o_que_aconteceu_fora": lambda *a, **k: [],
        "historico_se_esqueceu": lambda *a, **k: [],
        "registrar_se_pediu_parada": lambda *a, **k: None,
        "estado_do_handoff": lambda *a, **k: None,
        "registrar_uso": lambda *a, **k: None,
        "uso_das_mensagens": lambda *a, **k: None,
        "ferramentas_usadas": lambda *a, **k: [],
        "thread_id": lambda *a, **k: "teste-s6",
        "salvar_mensagem": lambda lead, direcao, texto, **k: salvas.append((direcao, texto)),
    }.items():
        monkeypatch.setattr(turno, nome, valor)

    junto = "Vou registrar aqui no sistema que você já comprou."
    final = "Parabéns pela compra, Carla! Fico à disposição."

    class GrafoFalso:
        def invoke(self, entrada, config):
            return {"messages": list(entrada["messages"]) + [
                AIMessage(content=junto, tool_calls=[{"name": "registrar_interesse",
                                                      "args": {"situacao": "sem_interesse"},
                                                      "id": "t1"}]),
                ToolMessage(content="Anotado.", tool_call_id="t1", name="registrar_interesse"),
                AIMessage(content=final),
            ]}

    r = asyncio.run(turno.executar_turno(1, "simulador", "lead-s6", "já comprei em outro lugar",
                                         grafo=GrafoFalso()))
    assert r.texto == final
    assert all(junto not in bolha for bolha in r.respostas)
    assert [t for d, t in salvas if d == "leo"] == [final]

"""
Bloco S7 (offline, sem Gemini): tom de voz no fim do prompt, apresentação sem
gênero, regra de assistente virtual intacta e prazo da visita no lead.
"""
import copy
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage

PASTA_TESTES = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PASTA_TESTES)
sys.path.insert(0, os.path.dirname(PASTA_TESTES))

import banco  # noqa: E402
import test_comportamento_etapa2_api as e25  # noqa: E402
from app.core import montagem  # noqa: E402
from app.lojas import PADROES  # noqa: E402
from tools import registrar_lead  # noqa: E402

RAIZ = Path(PASTA_TESTES).parent
FORMAL = "formal e respeitoso: trata o cliente por senhor ou senhora"
INFORMAL = e25.CONFIG_LOJA_2["tom"]


def _loja(tom=None, nome_agente=None):
    config = copy.deepcopy(PADROES)
    if tom:
        config["tom"] = tom
    if nome_agente:
        config["nome_agente"] = nome_agente
    return SimpleNamespace(id=1, nome="Loja Teste", segmento="veiculos", config=config)


def _prompt(loja, **extra):
    return montagem.montar_prompt(loja, montagem.ferramentas_da_loja(loja),
                                  datetime(2026, 11, 11, 10, 30), **extra)


def test_tom_fica_no_fim_do_prompt():
    p = _prompt(_loja(), primeiro_contato=True)
    i = p.index("TOM DE VOZ (vale")
    assert p.index("REGRA OBRIGATÓRIA DO HANDOFF") < i
    assert p.index("PRIMEIRO CONTATO") < i < p.index("DATA E HORA ATUAL")


def test_tom_formal_pede_senhor_desde_a_primeira_frase():
    assert '"o senhor" ou "a senhora" desde a primeira' in _prompt(_loja(FORMAL))


def test_tom_informal_nao_vira_formal():
    assert '"o senhor"' not in _prompt(_loja(INFORMAL))   # "informal" contém "formal"


def test_tom_padrao_nao_e_formal():
    assert '"o senhor"' not in _prompt(_loja())


def test_primeiro_contato_sem_artigo():
    p = _prompt(_loja(nome_agente="Duda"), primeiro_contato=True)
    assert "Aqui é Duda, da Loja Teste" in p
    assert "Aqui é o " not in p and "Aqui é a " not in p


def test_identidade_sem_artigo():
    p = _prompt(_loja())
    assert "Você é o assistente" not in p and "é o assistente virtual" not in p
    assert "assistente virtual da loja Loja Teste" in p


def test_regra_de_assistente_virtual_continua_igual():
    base = (RAIZ / "prompts" / "base.md").read_text(encoding="utf-8")
    assert "Apresente-se assim uma vez" in base
    assert "Nunca finja ser humano" in base
    assert "regra QUEM VOCÊ É" in _prompt(_loja(), primeiro_contato=True)


def test_agendamento_desligado_pede_prazo():
    aviso = montagem.AVISOS_MODULO_DESLIGADO["agendamento"]
    assert "prazo" in aviso and "quer visitar sábado" in aviso


def test_registrar_lead_explica_prazo_de_visita():
    assert "visitar" in registrar_lead.description


def test_registrar_lead_grava_prazo():
    registrar_lead.invoke({"nome": "Ana", "interesse": "Onix", "prazo": "quer visitar sábado",
                           "lead_id": "s7-visita", "loja_id": 1})
    con = banco.conectar()
    try:
        linha = con.execute("SELECT prazo FROM leads WHERE loja_id = 1 AND lead_id = 's7-visita'").fetchone()
    finally:
        con.close()
    assert linha["prazo"] == "quer visitar sábado"


def _conversa(falas, mensagens):
    c = e25.Conversa(loja_id=1, lead_id="x", falas=falas)
    c.novas_por_turno = [mensagens]
    return c


def _chamada(nome, args):
    return [AIMessage(content="", tool_calls=[{"name": nome, "args": args, "id": "1"}]),
            ToolMessage(content="ok", tool_call_id="1", name=nome)]


def test_visita_sem_prazo_avisa():
    c = _conversa(["quero visitar a loja sábado"], _chamada("registrar_lead", {"nome": "Ana", "interesse": "Onix"}))
    assert e25.VISITA_SEM_PRAZO in " ".join(m for _, m in e25.avisos_visita(c))


def test_visita_com_prazo_nao_avisa():
    c = _conversa(["quero visitar a loja sábado"],
                  _chamada("registrar_lead", {"nome": "Ana", "interesse": "Onix", "prazo": "quer visitar sábado"}))
    assert e25.avisos_visita(c) == []


def test_visita_agendada_nao_avisa():
    c = _conversa(["quero visitar a loja sábado"], _chamada("agendar_visita", {"data_hora": "sábado 10h"}))
    assert e25.avisos_visita(c) == []


def test_sem_pedido_de_visita_nao_avisa():
    c = _conversa(["quanto custa o Onix?"], _chamada("registrar_lead", {"nome": "Ana", "interesse": "Onix"}))
    assert e25.avisos_visita(c) == []


def test_loja_1_do_teste_e_formal():
    assert "senhor" in e25.CONFIG_LOJA_1["tom"]
    assert '"o senhor"' in _prompt(_loja(e25.CONFIG_LOJA_1["tom"]))

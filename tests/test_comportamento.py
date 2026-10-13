"""
Testes de COMPORTAMENTO do agente Léo (seção 11 do PDF: 15-20 conversas).

A ideia central (sugestão do analista): não testamos o TEXTO que o LLM gera
— que muda a cada execução e depende da API —, testamos as CHAMADAS DE TOOL,
que são determinísticas pela intenção do cliente.

Ex: "quero desconto" -> o agente TEM que chamar acionar_handoff.
    "quero um Civic"  -> nunca pode aparecer o ID do Civic 2017 (vendido).
    "qual a garantia?"-> tem que chamar buscar_conhecimento.

IMPORTANTE: estes testes INVOCAM O GEMINI DE VERDADE, então gastam API e
sofrem com 503/429. Por isso ficam marcados com @pytest.mark.api e NÃO rodam
no `pytest` normal. Para rodar só eles, quando a API estiver boa:

    pytest -m api -v

Para rodar todos MENOS estes (os unitários rápidos de sempre):

    pytest -m "not api" -v
"""

import os
import sys
import tempfile
import pytest

# Garante que o Python encontre os módulos da raiz do projeto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from banco import criar_tabelas, popular_estoque_exemplo

# Marca todos os testes deste arquivo como "api" (gastam Gemini)
pytestmark = pytest.mark.api


@pytest.fixture
def banco_com_estoque(monkeypatch):
    """Banco temporário populado com os 7 carros de exemplo (inclui o
    Civic 2017 vendido). Isola o teste do loja.db real."""
    fd, caminho = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(banco, "CAMINHO_BANCO", caminho)
    criar_tabelas()
    popular_estoque_exemplo()
    yield caminho
    if os.path.exists(caminho):
        os.remove(caminho)


def conversar(mensagem_cliente: str):
    """Envia UMA mensagem do cliente ao grafo e devolve a lista de mensagens
    resultante. Importa o grafo aqui dentro (não no topo) para não acionar o
    Gemini quando o pytest apenas COLETA os testes sem rodá-los."""
    from agent import agente_grafo
    from langchain_core.messages import HumanMessage

    resultado = agente_grafo.invoke({
        "messages": [HumanMessage(content=mensagem_cliente)],
        "lead_id": "teste-comportamento",
    })
    return resultado["messages"]


def tools_chamadas(mensagens) -> list:
    """Varre o histórico e retorna os NOMES de todas as tools que o agente
    chamou. É aqui que mora a verificação determinística."""
    nomes = []
    for msg in mensagens:
        chamadas = getattr(msg, "tool_calls", None)
        if chamadas:
            for c in chamadas:
                nomes.append(c["name"])
    return nomes


def texto_das_toolmessages(mensagens) -> str:
    """Junta o conteúdo das ToolMessages (o que as tools devolveram).
    Útil para checar que o estoque nunca vazou um carro vendido."""
    from langchain_core.messages import ToolMessage
    partes = []
    for msg in mensagens:
        if isinstance(msg, ToolMessage):
            partes.append(str(msg.content))
    return "\n".join(partes)


# ----------------------------------------------------------------------
# CASOS VERMELHOS: devem acionar handoff
# ----------------------------------------------------------------------

def test_pedido_de_desconto_aciona_handoff(banco_com_estoque):
    msgs = conversar("vocês conseguem dar um desconto nesse carro?")
    assert "acionar_handoff" in tools_chamadas(msgs)


def test_pedir_para_falar_com_pessoa_aciona_handoff(banco_com_estoque):
    msgs = conversar("quero falar com um vendedor de verdade, por favor")
    assert "acionar_handoff" in tools_chamadas(msgs)


# ----------------------------------------------------------------------
# ESTOQUE: usa a tool e NUNCA vaza carro vendido
# ----------------------------------------------------------------------

def test_pergunta_de_carro_consulta_estoque(banco_com_estoque):
    msgs = conversar("vocês têm algum Civic disponível?")
    assert "consultar_estoque" in tools_chamadas(msgs)


def test_estoque_nunca_oferece_carro_vendido(banco_com_estoque):
    # O Civic 2017 preto (82.000) está marcado como vendido no banco.
    msgs = conversar("quais Civic vocês têm?")
    retorno_tools = texto_das_toolmessages(msgs)
    # O que a tool devolveu NÃO pode conter o ano do carro vendido
    assert "2017" not in retorno_tools


# ----------------------------------------------------------------------
# POLÍTICAS: devem usar o RAG (buscar_conhecimento)
# ----------------------------------------------------------------------

def test_pergunta_de_garantia_usa_rag(banco_com_estoque):
    msgs = conversar("como funciona a garantia de vocês?")
    assert "buscar_conhecimento" in tools_chamadas(msgs)


def test_pergunta_de_financiamento_usa_rag_ou_simulador(banco_com_estoque):
    # "como funciona o financiamento" é política (RAG); pedir uma simulação
    # com números seria simular_financiamento. Aqui aceitamos qualquer um dos
    # dois, porque a fronteira é legítima e depende de como o cliente perguntou.
    msgs = conversar("como funciona o financiamento aqui na loja?")
    chamadas = tools_chamadas(msgs)
    assert "buscar_conhecimento" in chamadas or "simular_financiamento" in chamadas


# ----------------------------------------------------------------------
# TROCA: registra, mas é caso amarelo (sem valor)
# ----------------------------------------------------------------------

def test_cliente_com_troca_registra(banco_com_estoque):
    msgs = conversar("tenho um Gol 2015 pra dar na troca, dá pra aproveitar?")
    chamadas = tools_chamadas(msgs)
    # O agente pode registrar a troca OU pedir mais dados antes; o essencial
    # é que ele NÃO invente um valor. Se registrou, perfeito.
    assert "registrar_troca" in chamadas or len(chamadas) == 0

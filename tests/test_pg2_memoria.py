"""
PG2 (Maratona Postgres): memória das conversas do LangGraph no PostgreSQL.

- A conversa continua depois de reiniciar o processo (memória nova, conexões novas).
- O limite do L12 continua: conversa parada há mais de 24 h sai; acima do máximo, saem as
  mais antigas. Apagar uma conversa apaga só ela.
- Tudo no banco de teste; o grafo é pequeno e falso (sem IA).
"""
import time
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

import banco
from app.core.agent import MemoriaLimitada, memoria as memoria_do_leo


class Estado(TypedDict):
    messages: Annotated[list, add_messages]


def _no(estado):
    vistas = sum(1 for m in estado["messages"] if isinstance(m, HumanMessage))
    return {"messages": [AIMessage(content=f"já vi {vistas} mensagem(ns)")]}


def _grafo(memoria):
    g = StateGraph(Estado)
    g.add_node("leo", _no)
    g.add_edge(START, "leo")
    g.add_edge("leo", END)
    return g.compile(checkpointer=memoria)


def _falar(memoria, thread, texto="oi"):
    r = _grafo(memoria).invoke({"messages": [HumanMessage(content=texto)]},
                               {"configurable": {"thread_id": thread}})
    return r["messages"][-1].content


def _threads():
    c = banco.conectar()
    try:
        return {r[0] for r in c.execute("SELECT DISTINCT thread_id FROM checkpoints").fetchall()}
    finally:
        c.close()


def test_o_leo_usa_a_memoria_no_postgres():
    assert isinstance(memoria_do_leo, MemoriaLimitada)
    assert _falar(memoria_do_leo, "1:telegram:ana") == "já vi 1 mensagem(ns)"
    assert "1:telegram:ana" in _threads()


def test_conversa_continua_depois_de_reiniciar_o_processo():
    assert _falar(MemoriaLimitada(), "1:whatsapp:5581999998888") == "já vi 1 mensagem(ns)"
    assert _falar(MemoriaLimitada(), "1:whatsapp:5581999998888") == "já vi 2 mensagem(ns)"
    banco.fechar_pools()                         # "reinício": todas as conexões fechadas
    nova = MemoriaLimitada()
    assert _falar(nova, "1:whatsapp:5581999998888") == "já vi 3 mensagem(ns)"
    assert _falar(nova, "2:whatsapp:5581999998888") == "já vi 1 mensagem(ns)"   # outra loja


def test_limite_apaga_as_conversas_mais_antigas():
    memoria = MemoriaLimitada()
    memoria.PODAR_A_CADA_S = 10 ** 9              # só poda quando o teste mandar
    for i in range(5):
        _falar(memoria, f"1:telegram:t{i}")
        time.sleep(0.01)
    memoria.MAX_CONVERSAS = 3
    assert memoria.podar() == 2
    assert _threads() == {"1:telegram:t2", "1:telegram:t3", "1:telegram:t4"}


def test_conversa_parada_ha_mais_de_24h_sai():
    agora = [time.time()]
    memoria = MemoriaLimitada(relogio=lambda: agora[0])
    _falar(memoria, "1:telegram:velha")
    assert memoria.podar() == 0
    agora[0] += 25 * 3600
    assert memoria.podar() == 1
    assert _threads() == set()


def test_poda_roda_sozinha_ao_salvar():
    memoria = MemoriaLimitada()
    memoria.MAX_CONVERSAS = 2
    memoria.PODAR_A_CADA_S = 0
    for i in range(4):
        _falar(memoria, f"1:telegram:p{i}")
        time.sleep(0.01)
    assert len(_threads()) == 2


def test_apagar_uma_conversa_apaga_so_ela():
    memoria = MemoriaLimitada()
    _falar(memoria, "1:telegram:a")
    _falar(memoria, "1:telegram:b")
    memoria.delete_thread("1:telegram:a")
    assert _threads() == {"1:telegram:b"}
    assert _falar(memoria, "1:telegram:a") == "já vi 1 mensagem(ns)"   # recomeça do zero

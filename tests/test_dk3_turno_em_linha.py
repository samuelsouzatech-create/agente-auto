"""
DK3 (Maratona Docker): o turno não trava mais o servidor.

O turno usa o banco de forma síncrona. Antes, só a IA rodava fora do laço assíncrono; o resto
(guardas, mensagens, chamados, custos) travava o laço, e com muitas lojas os turnos andavam
um de cada vez. Agora o turno inteiro roda numa "linha do turno" (thread). Offline, LLM falso,
duas lojas.
"""
from __future__ import annotations

import asyncio
import threading
import time

from langchain_core.messages import AIMessage, HumanMessage

from app import ator
from app.core import turno
from app.mensagens import historico_do_lead


class GrafoLento:
    """Faz o papel do Léo: anota em qual linha rodou e responde com a loja e o cliente."""

    def __init__(self, espera=0.0):
        self.espera = espera
        self.linhas = []
        self.atores = []

    def invoke(self, entrada, config=None):
        self.linhas.append(threading.current_thread().name)
        self.atores.append(ator.ator_atual())
        time.sleep(self.espera)
        return {"messages": [HumanMessage(content=entrada["messages"][0].content),
                             AIMessage(content=f"Resposta para a loja {entrada['loja_id']}, "
                                               f"cliente {entrada['lead_id']}.")]}


def _segunda_loja() -> int:
    from app.lojas import criar_loja
    return criar_loja("Loja B do DK3")


def test_turno_roda_numa_linha_do_turno_e_nao_no_laco():
    grafo = GrafoLento()

    async def rodar():
        principal = threading.current_thread().name
        r = await turno.executar_turno(1, "simulador", "dk3-a", "tem civic?", grafo=grafo)
        return principal, r

    principal, r = asyncio.run(rodar())
    assert r.texto and "loja 1" in r.texto
    assert grafo.linhas and grafo.linhas[0].startswith("turno")
    assert grafo.linhas[0] != principal


def test_banco_lento_nao_trava_o_laco(monkeypatch):
    """Banco lento (0,3 s por gravação) dentro do turno: o laço continua girando."""
    original = turno.salvar_mensagem

    def salvar_devagar(*a, **k):
        time.sleep(0.3)
        return original(*a, **k)

    monkeypatch.setattr(turno, "salvar_mensagem", salvar_devagar)
    grafo = GrafoLento()

    async def rodar():
        voltas = 0
        acabou = asyncio.Event()

        async def relogio():
            nonlocal voltas
            while not acabou.is_set():
                voltas += 1
                await asyncio.sleep(0.01)

        tarefa = asyncio.create_task(relogio())
        await turno.executar_turno(1, "simulador", "dk3-lento", "oi", grafo=grafo)
        acabou.set()
        await tarefa
        return voltas

    voltas = asyncio.run(rodar())
    # O turno grava 2 mensagens (cliente e Léo): ~0,6 s de banco. Travando o laço, seriam ~0 voltas.
    assert voltas >= 20, voltas


def test_turnos_de_duas_lojas_ao_mesmo_tempo_nao_se_cruzam():
    loja_b = _segunda_loja()
    grafo = GrafoLento(espera=0.2)

    async def rodar():
        inicio = time.perf_counter()
        tarefas = [turno.executar_turno(loja, "simulador", f"dk3-{loja}-{n}", f"oi da loja {loja}", grafo=grafo)
                   for loja in (1, loja_b) for n in range(4)]
        resultados = await asyncio.gather(*tarefas)
        return resultados, time.perf_counter() - inicio

    resultados, duracao = asyncio.run(rodar())
    for loja, n, r in [(loja, n, None) for loja in (1, loja_b) for n in range(4)]:
        lead = f"dk3-{loja}-{n}"
        conversa = historico_do_lead(lead, loja_id=loja)
        assert [m["conteudo"] for m in conversa if m["direcao"] == "cliente"] == [f"oi da loja {loja}"]
        assert any(f"loja {loja}, cliente {lead}" in m["conteudo"] for m in conversa if m["direcao"] == "leo")
        outra = loja_b if loja == 1 else 1
        assert historico_do_lead(lead, loja_id=outra) == []        # a loja A nunca vê a B
    assert all(r.texto for r in resultados)
    # 8 turnos de 0,2 s de IA ao mesmo tempo: em paralelo, bem menos que 8 x 0,2 = 1,6 s.
    assert duracao < 1.2, duracao


def test_turno_leva_quem_esta_agindo_para_a_linha():
    grafo = GrafoLento()
    with ator.como("Pessoa DK3", "operador", "painel"):
        asyncio.run(turno.executar_turno(1, "simulador", "dk3-ator", "oi", grafo=grafo))
    assert grafo.atores[0] is not None and grafo.atores[0].pessoa == "Pessoa DK3"


def test_turno_com_foto_tambem_roda_fora_do_laco():
    from app.imagens import LeituraImagem
    linhas = []

    def leitor(imagem, mime):
        linhas.append(threading.current_thread().name)
        return LeituraImagem(ok=False)

    r = asyncio.run(turno.executar_turno_imagem(1, "simulador", "dk3-foto", b"x", "image/jpeg",
                                                grafo=GrafoLento(), leitor=leitor))
    assert r.texto                                   # resposta fixa da foto que não deu para ler
    assert linhas and linhas[0].startswith("turno")


def test_erro_da_ia_continua_virando_mensagem_de_erro():
    class Quebrado:
        def invoke(self, *a, **k):
            raise RuntimeError("falhou")

    r = asyncio.run(turno.executar_turno(1, "simulador", "dk3-erro", "oi", grafo=Quebrado()))
    assert r.texto == turno.MENSAGEM_ERRO


# ------------------------------------------------------------ banco: transação só quando precisa
import banco  # noqa: E402


def test_leitura_simples_nao_abre_transacao():
    c = banco.conectar()
    try:
        c.execute("SELECT COUNT(*) FROM lojas").fetchone()
        assert not c.in_transaction                      # nada de BEGIN/ROLLBACK por uma leitura
    finally:
        c.close()


def test_escrita_abre_transacao_e_fechar_sem_commit_desfaz():
    c = banco.conectar()
    try:
        c.execute("SELECT COUNT(*) FROM lojas").fetchone()
        c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo) "
                  "VALUES ('dk3-tx', 1, 'simulador', 'cliente', 'texto', 'some')")
        assert c.in_transaction
    finally:
        c.close()                                        # sem commit: desfaz (como o SQLite)
    assert historico_do_lead("dk3-tx", loja_id=1) == []


def test_commit_confirma_e_a_proxima_leitura_volta_sem_transacao():
    with banco.conectar() as c:
        c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo) "
                  "VALUES ('dk3-tx2', 1, 'simulador', 'cliente', 'texto', 'fica')")
    assert not c.in_transaction
    c.execute("SELECT 1").fetchone()
    assert not c.in_transaction
    c.close()
    assert [m["conteudo"] for m in historico_do_lead("dk3-tx2", loja_id=1)] == ["fica"]


def test_rollback_desfaz_o_que_veio_depois_da_leitura():
    c = banco.conectar()
    try:
        c.execute("SELECT 1").fetchone()
        c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo) "
                  "VALUES ('dk3-tx3', 1, 'simulador', 'cliente', 'texto', 'volta')")
        c.rollback()
        assert not c.in_transaction
        c.commit()                                       # nada aberto: não faz nada
    finally:
        c.close()
    assert historico_do_lead("dk3-tx3", loja_id=1) == []


def test_comandos_que_precisam_de_transacao():
    for comando in ("SELECT * FROM lojas FOR UPDATE", "SET LOCAL enable_seqscan = off",
                    "UPDATE lojas SET nome = nome", "SELECT nextval('x')",
                    "WITH a AS (DELETE FROM t RETURNING *) SELECT * FROM a",
                    "SELECT pg_advisory_xact_lock(1)"):
        assert not banco.leitura_simples(comando), comando
    for comando in ("SELECT * FROM lojas WHERE id = %s", "  select 1", "WITH a AS (SELECT 1) SELECT * FROM a",
                    "EXPLAIN SELECT 1"):
        assert banco.leitura_simples(comando), comando
    c = banco.conectar()
    try:
        c.execute("SELECT id FROM lojas WHERE id = 1 FOR UPDATE").fetchone()
        assert c.in_transaction                          # a trava da linha vale até o commit
    finally:
        c.close()


def test_somente_leitura_continua_recusando_escrita():
    import pytest as _pytest
    c = banco.conectar(somente_leitura=True)
    try:
        with _pytest.raises(Exception):
            c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo) "
                      "VALUES ('dk3-ro', 1, 'simulador', 'cliente', 'texto', 'x')")
    finally:
        c.close()


def test_conexao_volta_ao_pool_no_jeito_de_sempre():
    c = banco.conectar()
    bruta = c._bruta
    c.execute("SELECT 1").fetchone()
    c.close()
    assert bruta.autocommit is False


# ------------------------------------------------------------ memória sem a trava única
def test_memoria_sem_trava_unica_e_turnos_de_varias_conversas_ao_mesmo_tempo():
    import contextlib
    from concurrent.futures import ThreadPoolExecutor

    from langgraph.graph import END, START, StateGraph

    from app.core.agent import MemoriaLimitada
    from tests.test_pg3_carga import Estado

    memoria = MemoriaLimitada()
    assert isinstance(memoria.lock, contextlib.nullcontext)

    def no(e):
        time.sleep(0.05)
        return {"messages": [AIMessage(content=f"ok {e['lead_id']}")]}

    g = StateGraph(Estado)
    g.add_node("a", no)
    g.add_edge(START, "a")
    g.add_edge("a", END)
    grafo = g.compile(checkpointer=memoria)

    def conversa(n):
        cfg = {"configurable": {"thread_id": f"dk3-mem-{n}"}}
        for k in range(3):
            grafo.invoke({"messages": [HumanMessage(content=f"m{k}")], "lead_id": f"L{n}",
                          "loja_id": 1, "canal": "simulador"}, cfg)
        return len(grafo.get_state(cfg).values["messages"])

    with ThreadPoolExecutor(8) as linhas:
        tamanhos = list(linhas.map(conversa, range(8)))
    assert tamanhos == [6] * 8                           # 3 do cliente + 3 respostas, sem perder


def test_so_uma_poda_por_vez():
    from app.core.agent import MemoriaLimitada
    memoria = MemoriaLimitada()
    assert memoria._trava_da_poda.acquire(blocking=False)
    try:
        assert memoria.podar() == 0                      # outra linha está podando: não faz nada
    finally:
        memoria._trava_da_poda.release()

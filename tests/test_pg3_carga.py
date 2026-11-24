"""
PG3 (Maratona Postgres): o Léo aguenta 10 lojas ao mesmo tempo? Teste de CARGA, offline.

Fica FORA da suíte rápida (marcador "carga"). Para rodar (banco e Redis ligados):
    docker compose up -d              (o Redis do compose; o teste usa a gaveta 14, nunca a 0)
    .venv-teste\\Scripts\\python -m pytest -m carga tests/test_pg3_carga.py -s

O que ele faz:
- 10 lojas fictícias no banco de TESTE, cada uma com o próprio número de WhatsApp, no ar.
- 10 clientes por loja. Cada cliente manda uma rajada de 3 mensagens seguidas e, enquanto o
  Léo ainda responde, mais 2: todas chegam pelo MESMO caminho de verdade (POST do webhook com
  assinatura -> Redis: duplicata, debounce e trava por lead -> executar_turno -> envio).
- A IA é trocada por uma resposta falsa e rápida (0,1 a 0,3 s), que diz para qual loja e
  cliente está respondendo. A memória das conversas é a de verdade (PostgreSQL).
- Nada sai para a Meta: o envio é gravado numa lista.

Mede e escreve em logs/carga/: mensagens perdidas, respostas cruzadas, erros, tempo médio e
pior tempo, conexões do pool e memória do processo antes e depois.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import random
import statistics
import threading
import time
import uuid
from pathlib import Path
from typing import Annotated, TypedDict

import psutil
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

import banco
from app.core.agent import MemoriaLimitada

pytestmark = pytest.mark.carga

RAIZ = Path(__file__).resolve().parent.parent
LOJAS = int(os.getenv("CARGA_LOJAS", "10"))
LEADS = int(os.getenv("CARGA_LEADS", "10"))
RAJADA_1 = 3
RAJADA_2 = 2
DEBOUNCE_S = 1.5
SEGREDO = "segredo-do-teste-de-carga"


class Estado(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    lead_id: str
    loja_id: int
    canal: str
    equipe: dict
    sombra: bool


def _codigo(loja_id: int, lead_id: str) -> str:
    return f"loja{loja_id}cliente{lead_id[-4:]}"


def _no_falso(estado):
    """A "IA": demora um pouco e responde dizendo para quem está respondendo."""
    time.sleep(random.uniform(0.1, 0.3))
    codigo = _codigo(int(estado["loja_id"]), str(estado["lead_id"]))
    return {"messages": [AIMessage(content=f"Combinado, anotei tudo por aqui. Referência {codigo}.")]}


def _grafo_falso():
    g = StateGraph(Estado)
    g.add_node("agente", _no_falso)
    g.add_edge(START, "agente")
    g.add_edge("agente", END)
    return g.compile(checkpointer=MemoriaLimitada())


def _pacote(id_canal: str, numero: str, texto: str) -> dict:
    return {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": id_canal},
        "messages": [{"id": f"wamid.{uuid.uuid4().hex}", "from": numero, "type": "text",
                      "timestamp": str(int(time.time())), "text": {"body": texto}}]}}]}]}


def _assinar(corpo: bytes) -> str:
    return "sha256=" + hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()


@pytest.fixture
def redis_de_verdade():
    import app.redis_cliente as rc

    async def ping():
        return await rc.redis_cliente.ping()
    try:
        asyncio.run(ping())
    except Exception as erro:
        pytest.fail(f"O teste de carga precisa do Redis ligado (REDIS_URL): {erro!r}")
    yield


def _preparar_lojas() -> list[tuple[int, str]]:
    from app.canais import cadastrar_canal
    from app.lojas import criar_loja
    lojas = []
    c = banco.conectar()
    try:
        for i in range(LOJAS):
            loja_id = criar_loja(f"Loja de Carga {i + 1}")
            id_canal = f"99000{loja_id:04d}"
            cadastrar_canal(loja_id, "whatsapp", id_canal, f"TOKEN_CARGA_{loja_id}")
            c.execute("INSERT INTO estado_lojas (loja_id, estado, no_ar_em, alterado_por) "
                      "VALUES (?, 'no_ar', CURRENT_TIMESTAMP, 'Carga') ON CONFLICT (loja_id) "
                      "DO UPDATE SET estado = 'no_ar'", (loja_id,))
            lojas.append((loja_id, id_canal))
        c.commit()
    finally:
        c.close()
    return lojas


def _mensagens_do_banco():
    c = banco.conectar()
    try:
        return [dict(l) for l in c.execute(
            "SELECT loja_id, lead_id, direcao, conteudo FROM mensagens ORDER BY id").fetchall()]
    finally:
        c.close()


def test_10_lojas_ao_mesmo_tempo(monkeypatch, redis_de_verdade):
    from httpx import ASGITransport, AsyncClient
    import app.api.webhook as webhook
    import app.redis_debounce as debounce

    lojas = _preparar_lojas()
    enviados: list[tuple[int, str, str, float]] = []
    turnos: list[float] = []
    erros: list[str] = []
    ultima_chegada: dict[tuple[int, str], float] = {}

    async def enviar_falso(numero, texto, atraso=0, *, loja_id):
        enviados.append((loja_id, numero, texto, time.perf_counter()))

    async def nada(*a, **k):
        return None

    executar_original = webhook.executar_turno

    async def executar_medindo(*a, **k):
        inicio = time.perf_counter()
        try:
            return await executar_original(*a, **k)
        finally:
            turnos.append(time.perf_counter() - inicio)

    processar_original = webhook.processar_mensagem

    async def processar_contando_erros(*a, **k):
        try:
            return await processar_original(*a, **k)
        except Exception as erro:            # o que escapar do caminho de verdade
            erros.append(repr(erro))

    monkeypatch.setattr(webhook, "WHATSAPP_APP_SECRET", SEGREDO)
    monkeypatch.setattr(webhook, "agente_grafo", _grafo_falso())
    monkeypatch.setattr(webhook, "enviar_resposta_humanizada", enviar_falso)
    monkeypatch.setattr(webhook.canal_whatsapp, "marcar_lida", nada)
    monkeypatch.setattr(webhook, "executar_turno", executar_medindo)
    monkeypatch.setattr(webhook, "processar_mensagem", processar_contando_erros)
    monkeypatch.setattr(debounce, "DEBOUNCE_SEGUNDOS", DEBOUNCE_S)

    clientes = [(loja_id, id_canal, f"5581{9000 + loja_id:04d}{n:04d}")
                for loja_id, id_canal in lojas for n in range(LEADS)]
    textos: dict[tuple[int, str], list[str]] = {(l, num): [] for l, _, num in clientes}

    processo = psutil.Process()
    memoria_antes = processo.memory_info().rss
    pico = {"pool_size": 0, "esperando": 0, "postgres": 0}
    parar = threading.Event()

    def vigiar():
        while not parar.is_set():
            est = banco.estatisticas_do_pool()
            pico["pool_size"] = max(pico["pool_size"], est.get("pool_size", 0))
            pico["esperando"] = max(pico["esperando"], est.get("requests_waiting", 0))
            try:
                c = banco.conectar()
                try:
                    n = c.execute("SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database()").fetchone()[0]
                finally:
                    c.close()
                pico["postgres"] = max(pico["postgres"], n)
            except Exception:
                pass
            parar.wait(0.05)

    vigia = threading.Thread(target=vigiar, daemon=True)
    vigia.start()

    async def mandar(cli, id_canal, loja_id, numero, k):
        texto = f"mensagem {k} do cliente {numero[-4:]} para a loja {loja_id}"
        textos[(loja_id, numero)].append(texto)
        corpo = json.dumps(_pacote(id_canal, numero, texto)).encode()
        ultima_chegada[(loja_id, numero)] = time.perf_counter()
        r = await cli.post("/webhook", content=corpo, headers={
            "X-Hub-Signature-256": _assinar(corpo), "Content-Type": "application/json"})
        assert r.status_code == 200

    async def cliente(cli, loja_id, id_canal, numero):
        await asyncio.sleep(random.uniform(0, 0.5))
        tarefas = []
        for k in range(RAJADA_1):
            tarefas.append(asyncio.create_task(mandar(cli, id_canal, loja_id, numero, k + 1)))
            await asyncio.sleep(random.uniform(0.05, 0.3))
        await asyncio.sleep(DEBOUNCE_S + 0.4)            # o Léo está respondendo a 1ª rajada
        for k in range(RAJADA_2):
            tarefas.append(asyncio.create_task(mandar(cli, id_canal, loja_id, numero, RAJADA_1 + k + 1)))
            await asyncio.sleep(random.uniform(0.05, 0.3))
        await asyncio.gather(*tarefas)

    async def rodar():
        async with AsyncClient(transport=ASGITransport(app=webhook.app), base_url="http://teste") as cli:
            await asyncio.gather(*(cliente(cli, l, c, n) for l, c, n in clientes))

    inicio = time.perf_counter()
    asyncio.run(rodar())
    duracao = time.perf_counter() - inicio
    parar.set()
    vigia.join(2)
    memoria_depois = processo.memory_info().rss

    # ---------------------------------------------------------------- conferência
    gravadas = _mensagens_do_banco()
    perdidas, cruzadas = [], []
    for (loja_id, numero), lista in textos.items():
        do_cliente = " ".join(m["conteudo"] for m in gravadas
                              if m["loja_id"] == loja_id and m["lead_id"] == numero and m["direcao"] == "cliente")
        perdidas += [(loja_id, numero, t) for t in lista if t not in do_cliente]
    for m in gravadas:                               # mensagem gravada no lugar errado
        if m["direcao"] == "cliente" and f"para a loja {m['loja_id']}" not in m["conteudo"]:
            cruzadas.append(("cliente_na_loja_errada", m["loja_id"], m["lead_id"]))
        if m["direcao"] == "leo" and _codigo(m["loja_id"], m["lead_id"]) not in m["conteudo"]:
            cruzadas.append(("resposta_gravada_errada", m["loja_id"], m["lead_id"]))
    for loja_id, numero, texto, _ in enviados:       # resposta enviada para quem não era
        if _codigo(loja_id, numero) not in texto:
            cruzadas.append(("resposta_enviada_errada", loja_id, numero))
    sem_resposta = [k for k in textos if not any(e[0] == k[0] and e[1] == k[1] for e in enviados)]

    # tempo de resposta: da ÚLTIMA mensagem de cada rajada até o envio (inclui o debounce)
    respostas = {}
    for loja_id, numero, _, quando in enviados:
        respostas.setdefault((loja_id, numero), []).append(quando)
    espera = [max(v) - ultima_chegada[k] for k, v in respostas.items()]

    estat = banco.estatisticas_do_pool()
    relatorio = {
        "lojas": LOJAS, "clientes": len(clientes),
        "mensagens_mandadas": sum(len(v) for v in textos.values()),
        "turnos_do_leo": len(turnos), "respostas_enviadas": len(enviados),
        "mensagens_perdidas": len(perdidas), "respostas_cruzadas": len(cruzadas),
        "clientes_sem_resposta": len(sem_resposta), "erros": len(erros),
        "duracao_total_s": round(duracao, 1),
        "turno_medio_s": round(statistics.mean(turnos), 3) if turnos else None,
        "turno_pior_s": round(max(turnos), 3) if turnos else None,
        "espera_ate_a_ultima_resposta_media_s": round(statistics.mean(espera), 2) if espera else None,
        "espera_ate_a_ultima_resposta_pior_s": round(max(espera), 2) if espera else None,
        "debounce_s": DEBOUNCE_S,
        "pool_max": estat.get("pool_max"), "pool_conexoes_pico": pico["pool_size"],
        "pool_pedidos_esperando_pico": pico["esperando"],
        "pool_esperas_total": estat.get("requests_waiting", 0),
        "pool_tempo_de_espera_ms": estat.get("requests_wait_ms"),
        "pool_pedidos": estat.get("requests_num"),
        "conexoes_no_postgres_pico": pico["postgres"],
        "memoria_antes_mb": round(memoria_antes / 2**20, 1),
        "memoria_depois_mb": round(memoria_depois / 2**20, 1),
        "exemplos_perdidas": perdidas[:5], "exemplos_cruzadas": cruzadas[:5], "exemplos_erros": erros[:5],
    }
    pasta = RAIZ / "logs" / "carga"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"carga_{time.strftime('%Y%m%d_%H%M%S')}.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n" + json.dumps(relatorio, ensure_ascii=False, indent=1))

    assert perdidas == [], perdidas[:5]
    assert cruzadas == [], cruzadas[:5]
    assert erros == [], erros[:5]
    assert sem_resposta == [], sem_resposta[:5]

"""
Testes da Etapa 1, Bloco 3 - isolamento (item 1.5). Todos offline.

Provam: chaves do Redis com loja; lock/debounce de uma loja não afetam outra;
dedup no Redis (com plano B em memória); loja descoberta pelo canal; mesmo
número em duas lojas = memórias, históricos e handoffs separados.
"""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import uuid
from dataclasses import dataclass, field

import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from app.chaves import chave_redis, thread_id
from app.canais import (
    resolver_loja, cadastrar_canal, desativar_canal, listar_canais, id_bot_telegram,
)

LOJA_B = 42
SEGREDO = "segredo-de-teste"


# ---------------------------------------------------------------- apoio

def importar(nome):
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.setdefault("GOOGLE_API_KEY", "chave-falsa-so-para-importar")
    import importlib
    return importlib.import_module(nome)


@pytest.fixture
def redis_falso(monkeypatch):
    import fakeredis
    import app.redis_cliente as rc
    import app.redis_debounce as rd
    import app.redis_lock as rl
    import app.redis_atraso as ra
    falso = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    for modulo in (rc, rd, rl, ra):
        monkeypatch.setattr(modulo, "redis_cliente", falso)
    monkeypatch.setattr(rd, "DEBOUNCE_SEGUNDOS", 0.1)
    monkeypatch.setattr(ra, "ATRASO_ATIVO", (0, 0))
    monkeypatch.setattr(ra, "ATRASO_AUSENTE", (0, 0))
    return falso


@pytest.fixture
def loja_b():
    conexao = banco.conectar()
    conexao.execute("INSERT OR IGNORE INTO lojas (id, nome, segmento, config) "
                    "VALUES (?, 'Auto Bia', 'veiculos', '{}')", (LOJA_B,))
    conexao.commit()
    conexao.close()
    return LOJA_B


class GrafoEspiao:
    """Substitui o Léo e guarda o que recebeu (entrada + config)."""

    def __init__(self):
        self.chamadas = []

    def invoke(self, entrada, config=None):
        self.chamadas.append((entrada, config))
        return {"messages": [HumanMessage(content=entrada["messages"][0].content),
                             AIMessage(content="Oi!")]}


@dataclass
class Saidas:
    respostas: list = field(default_factory=list)


@pytest.fixture
def whatsapp(monkeypatch, redis_falso, loja_b):
    wh = importar("app.api.webhook")
    saidas = Saidas()

    async def resposta(numero, texto, atraso=0):
        saidas.respostas.append((numero, texto))

    async def foto(numero, url):
        return True

    monkeypatch.setattr(wh, "enviar_resposta_humanizada", resposta)
    monkeypatch.setattr(wh, "enviar_foto_whatsapp", foto)
    grafo = GrafoEspiao()
    monkeypatch.setattr(wh, "agente_grafo", grafo)
    return wh, grafo, saidas


# ------------------------------------------------------------- chaves

def test_chaves_padronizadas():
    assert chave_redis("lock", 2, "5581") == "lock:2:5581"
    assert chave_redis("buffer", None, "5581") == "buffer:1:5581"
    assert thread_id(2, "whatsapp", "5581") == "2:whatsapp:5581"


def test_lock_de_uma_loja_nao_trava_a_outra(redis_falso):
    from app.redis_lock import adquirir_lock, liberar_lock

    async def cenario():
        t1 = await adquirir_lock("5581", loja_id=1)
        tb = await adquirir_lock("5581", loja_id=LOJA_B)
        t1_de_novo = await adquirir_lock("5581", loja_id=1)
        await liberar_lock("5581", t1, loja_id=1)
        t1_depois = await adquirir_lock("5581", loja_id=1)
        return t1, tb, t1_de_novo, t1_depois

    t1, tb, t1_de_novo, t1_depois = asyncio.run(cenario())
    assert t1 and tb, "O mesmo número em lojas diferentes deve conseguir os dois locks."
    assert t1_de_novo is None, "Na MESMA loja o lock continua exclusivo."
    assert t1_depois


def test_debounce_nao_mistura_rajadas_de_lojas_diferentes(redis_falso):
    from app.redis_debounce import acumular_e_esperar

    async def cenario():
        return await asyncio.gather(
            acumular_e_esperar("5581", "quero civic", loja_id=1),
            acumular_e_esperar("5581", "quero renegade", loja_id=LOJA_B),
        )

    assert asyncio.run(cenario()) == ["quero civic", "quero renegade"]


def test_carimbo_de_visto_leva_a_loja(redis_falso):
    from app.redis_atraso import calcular_atraso
    asyncio.run(calcular_atraso("5581", loja_id=LOJA_B))
    assert asyncio.run(redis_falso.keys("*")) == [f"visto:{LOJA_B}:5581"]


# -------------------------------------------------------------- dedup

def test_dedup_no_redis_por_canal(redis_falso):
    from app.dedup import ja_processada

    async def cenario():
        return [
            await ja_processada("whatsapp", "wamid.1"),
            await ja_processada("whatsapp", "wamid.1"),
            await ja_processada("telegram", "wamid.1"),
        ]

    assert asyncio.run(cenario()) == [False, True, False]
    assert asyncio.run(redis_falso.ttl("dedup:whatsapp:wamid.1")) > 0


def test_dedup_sem_redis_usa_memoria_local(monkeypatch):
    import app.redis_cliente as rc
    from app.dedup import ja_processada

    class RedisFora:
        async def set(self, *args, **kwargs):
            raise ConnectionError("redis fora do ar")

    monkeypatch.setattr(rc, "redis_cliente", RedisFora())
    id_mensagem = f"wamid.{uuid.uuid4().hex}"

    async def cenario():
        return [await ja_processada("whatsapp", id_mensagem),
                await ja_processada("whatsapp", id_mensagem)]

    assert asyncio.run(cenario()) == [False, True]


# ------------------------------------------------------------- canais

def test_sem_canal_cadastrado_vale_a_loja_1():
    assert resolver_loja("whatsapp", "qualquer") == 1
    assert resolver_loja("whatsapp", None) == 1


def test_canal_cadastrado_aponta_para_a_loja_certa(loja_b):
    cadastrar_canal(1, "whatsapp", "PNID_1")
    cadastrar_canal(LOJA_B, "whatsapp", "PNID_B")
    assert resolver_loja("whatsapp", "PNID_1") == 1
    assert resolver_loja("whatsapp", "PNID_B") == LOJA_B
    assert resolver_loja("whatsapp", "DESCONHECIDO") is None
    assert resolver_loja("whatsapp", None) is None
    assert resolver_loja("telegram", "123") == 1  # nenhum Telegram cadastrado ainda


def test_canal_desativado_deixa_de_resolver(loja_b):
    cadastrar_canal(1, "whatsapp", "PNID_1")
    cadastrar_canal(LOJA_B, "whatsapp", "PNID_B")
    desativar_canal("whatsapp", "PNID_B")
    assert resolver_loja("whatsapp", "PNID_B") is None


def test_recadastrar_move_o_canal_sem_duplicar(loja_b):
    cadastrar_canal(1, "telegram", "777")
    cadastrar_canal(LOJA_B, "telegram", "777")
    assert resolver_loja("telegram", "777") == LOJA_B
    assert len(listar_canais()) == 1


def test_cadastrar_canal_valida_os_dados(loja_b):
    with pytest.raises(ValueError):
        cadastrar_canal(999, "whatsapp", "X")
    with pytest.raises(ValueError):
        cadastrar_canal(1, "fax", "X")
    with pytest.raises(ValueError):
        cadastrar_canal(1, "whatsapp", "  ")


def test_id_do_bot_telegram():
    assert id_bot_telegram("123456:ABC-def") == "123456"
    assert id_bot_telegram("") == ""
    assert id_bot_telegram(None) == ""
    assert id_bot_telegram("sem-dois-pontos") == ""


# --------------------------------------------- webhook descobre a loja

def _corpo(phone_number_id=None, numero="5581999990000", texto="oi"):
    valor = {"messages": [{"id": f"wamid.{uuid.uuid4().hex}", "from": numero,
                           "type": "text", "text": {"body": texto}}]}
    if phone_number_id:
        valor["metadata"] = {"phone_number_id": phone_number_id}
    return json.dumps({"entry": [{"changes": [{"value": valor}]}]}).encode()


def _assinar(corpo):
    return "sha256=" + hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()


@pytest.fixture
def webhook_http(monkeypatch, loja_b):
    from fastapi.testclient import TestClient
    wh = importar("app.api.webhook")
    agendadas = []

    async def processar_falso(numero, texto, id_audio=None, loja_id=1):
        agendadas.append((numero, texto, loja_id))

    async def nunca_duplicada(canal, id_mensagem):
        return False

    monkeypatch.setattr(wh, "processar_mensagem", processar_falso)
    monkeypatch.setattr(wh, "ja_processada", nunca_duplicada)
    monkeypatch.setattr(wh, "WHATSAPP_APP_SECRET", SEGREDO)
    return TestClient(wh.app), agendadas


def _post(cliente, corpo):
    return cliente.post("/webhook", content=corpo, headers={
        "Content-Type": "application/json", "X-Hub-Signature-256": _assinar(corpo)})


def test_webhook_entrega_a_mensagem_para_a_loja_dona_do_numero(webhook_http):
    cliente, agendadas = webhook_http
    cadastrar_canal(1, "whatsapp", "PNID_1")
    cadastrar_canal(LOJA_B, "whatsapp", "PNID_B")
    assert _post(cliente, _corpo("PNID_B", texto="tem Renegade?")).status_code == 200
    assert agendadas == [("5581999990000", "tem Renegade?", LOJA_B)]


def test_webhook_ignora_numero_nao_cadastrado(webhook_http):
    cliente, agendadas = webhook_http
    cadastrar_canal(1, "whatsapp", "PNID_1")
    assert _post(cliente, _corpo("PNID_ESTRANHO")).status_code == 200
    assert agendadas == []


def test_webhook_sem_canais_cadastrados_usa_loja_1(webhook_http):
    cliente, agendadas = webhook_http
    _post(cliente, _corpo("PNID_QUALQUER", texto="oi"))
    assert agendadas == [("5581999990000", "oi", 1)]


# ------------------------------------- mesmo número em duas lojas

def test_mesmo_numero_em_duas_lojas_tem_memoria_e_historico_separados(whatsapp):
    from app.mensagens import historico_do_lead
    wh, grafo, saidas = whatsapp

    async def cenario():
        await asyncio.gather(
            wh.processar_mensagem("5581", "oi loja 1", None, 1),
            wh.processar_mensagem("5581", "oi loja B", None, LOJA_B),
        )

    asyncio.run(cenario())

    vistos = {
        e["loja_id"]: (e["messages"][0].content, c["configurable"]["thread_id"], e["canal"])
        for e, c in grafo.chamadas
    }
    assert vistos == {
        1: ("oi loja 1", "1:whatsapp:5581", "whatsapp"),
        LOJA_B: ("oi loja B", f"{LOJA_B}:whatsapp:5581", "whatsapp"),
    }
    assert [m["conteudo"] for m in historico_do_lead("5581", loja_id=1)] == ["oi loja 1", "Oi!"]
    assert [m["conteudo"] for m in historico_do_lead("5581", loja_id=LOJA_B)] == ["oi loja B", "Oi!"]


def test_vendedor_de_uma_loja_nao_silencia_o_leo_da_outra(whatsapp):
    from app.handoff import assumir_handoff
    from tools import acionar_handoff
    wh, grafo, saidas = whatsapp
    acionar_handoff.func(motivo="desconto", resumo="r", lead_id="5581", loja_id=LOJA_B)
    assumir_handoff("5581", "Ana", loja_id=LOJA_B)

    asyncio.run(wh.processar_mensagem("5581", "baixa o preço?", None, LOJA_B))
    assert grafo.chamadas == [], "Na loja B o vendedor assumiu: Léo em silêncio."

    asyncio.run(wh.processar_mensagem("5581", "tem Civic?", None, 1))
    assert len(grafo.chamadas) == 1, "Na loja 1 não há vendedor: o Léo responde."


def test_telegram_usa_memoria_da_loja(monkeypatch, redis_falso, loja_b):
    tb = importar("app.api.telegram_bot")
    grafo = GrafoEspiao()
    monkeypatch.setattr(tb, "agente_grafo", grafo)
    resposta, _ = asyncio.run(tb.processar_texto("777", "oi", loja_id=LOJA_B))
    entrada, config = grafo.chamadas[0]
    assert resposta == "Oi!"
    assert entrada["loja_id"] == LOJA_B
    assert config["configurable"]["thread_id"] == f"{LOJA_B}:telegram:777"

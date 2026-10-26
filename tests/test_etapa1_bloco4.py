"""
Testes da Etapa 1, Bloco 4 - canais unificados (itens 1.6 e 1.7). Todos offline.

Provam: executar_turno() único (silêncio, guarda, handoff, erro); a mesma
conversa dá o mesmo resultado no WhatsApp, Telegram e simulador; payload com
várias mensagens; mídia não suportada; marcar como lida; contrato dos canais.
"""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import uuid
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.mensagens import historico_do_lead

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


class GrafoRoteiro:
    """Substitui o Léo: devolve um turno roteirizado (com fotos, se pedir)."""

    def __init__(self, texto="Oi!", urls=(), extras=(), erro=None):
        self.texto, self.urls, self.extras, self.erro = texto, list(urls), list(extras), erro
        self.chamadas = []

    def invoke(self, entrada, config=None):
        self.chamadas.append((entrada, config))
        if self.erro:
            raise self.erro
        mensagens = [HumanMessage(content=entrada["messages"][0].content)]
        if self.urls:
            mensagens.append(AIMessage(content="", tool_calls=[
                {"name": "enviar_fotos", "args": {}, "id": "c-fotos"}]))
            mensagens.append(ToolMessage(content="Enviando fotos.", tool_call_id="c-fotos",
                                         name="enviar_fotos",
                                         artifact={"tipo": "fotos", "urls": list(self.urls)}))
        mensagens.extend(self.extras)
        mensagens.append(AIMessage(content=self.texto))
        return {"messages": mensagens}


def _abrir_e_assumir(lead_id, loja_id=1):
    from tools import acionar_handoff
    from app.handoff import assumir_handoff
    acionar_handoff.func(motivo="desconto", resumo="r", lead_id=lead_id, loja_id=loja_id)
    assumir_handoff(lead_id, "Ana", loja_id=loja_id)


def _payload(*mensagens, phone_number_id=None, statuses=None):
    valor = {}
    if mensagens:
        valor["messages"] = list(mensagens)
    if statuses:
        valor["statuses"] = statuses
    if phone_number_id:
        valor["metadata"] = {"phone_number_id": phone_number_id}
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": valor}]}]}


def _msg(tipo="text", numero="5581", id_=None, **campos):
    msg = {"id": id_ or f"wamid.{uuid.uuid4().hex}", "from": numero,
           "timestamp": "1700000000", "type": tipo}
    msg.update(campos)
    return msg


def _texto(texto, **kw):
    return _msg("text", text={"body": texto}, **kw)


# ------------------------------------------------ executar_turno (1.6)

def test_turno_normal_limpa_markdown_traz_fotos_e_grava_historico():
    turno = importar("app.core.turno")
    grafo = GrafoRoteiro("O **Civic 2019** está disponível!", urls=["http://f/1.jpg"])
    r = asyncio.run(turno.executar_turno(1, "simulador", "lead-1", "tem civic?", grafo=grafo))

    assert r.texto == "O Civic 2019 está disponível!"
    assert r.midias == ["http://f/1.jpg"]
    assert not r.silenciado and not r.handoff_aberto
    entrada, config = grafo.chamadas[0]
    assert config["configurable"]["thread_id"] == "1:simulador:lead-1"
    assert (entrada["loja_id"], entrada["canal"], entrada["lead_id"]) == (1, "simulador", "lead-1")
    assert [(m["direcao"], m["conteudo"], m["canal"]) for m in historico_do_lead("lead-1")] == [
        ("cliente", "tem civic?", "simulador"),
        ("leo", "O Civic 2019 está disponível!", "simulador"),
    ]


def test_turno_em_silencio_quando_o_vendedor_assumiu():
    turno = importar("app.core.turno")
    _abrir_e_assumir("lead-2")
    grafo = GrafoRoteiro()
    r = asyncio.run(turno.executar_turno(1, "whatsapp", "lead-2", "baixa o preço?", grafo=grafo))
    assert r.silenciado and r.texto is None
    assert grafo.chamadas == []
    assert [m["direcao"] for m in historico_do_lead("lead-2")] == ["cliente"]


def test_turno_guarda_barra_preco_inventado():
    turno = importar("app.core.turno")
    from app.guarda_politica import MENSAGEM_SEGURA
    from app.handoff import estado_do_handoff
    grafo = GrafoRoteiro("O Civic sai por R$ 77.000", urls=["http://f/1.jpg"])
    r = asyncio.run(turno.executar_turno(1, "telegram", "lead-3", "quanto é?", grafo=grafo))
    assert r.texto == MENSAGEM_SEGURA
    assert r.midias == [] and r.handoff_aberto
    assert estado_do_handoff("lead-3", 1) == "aguardando_humano"


def test_turno_avisa_quando_o_leo_chamou_o_vendedor():
    turno = importar("app.core.turno")
    extras = [
        AIMessage(content="", tool_calls=[{"name": "acionar_handoff", "args": {}, "id": "c-h"}]),
        ToolMessage(content="Handoff acionado.", tool_call_id="c-h", name="acionar_handoff"),
    ]
    grafo = GrafoRoteiro("Vou chamar um vendedor para você.", extras=extras)
    r = asyncio.run(turno.executar_turno(1, "whatsapp", "lead-4", "quero desconto", grafo=grafo))
    assert r.handoff_aberto


def test_turno_com_erro_do_gemini_responde_com_honestidade():
    turno = importar("app.core.turno")
    grafo = GrafoRoteiro(erro=RuntimeError("Gemini fora do ar"))
    r = asyncio.run(turno.executar_turno(1, "whatsapp", "lead-5", "oi", grafo=grafo))
    assert r.texto == turno.MENSAGEM_ERRO
    assert historico_do_lead("lead-5")[-1]["conteudo"] == turno.MENSAGEM_ERRO


def test_midia_nao_suportada_responde_e_respeita_o_vendedor():
    turno = importar("app.core.turno")
    r = turno.turno_midia_nao_suportada(1, "whatsapp", "lead-6", "image")
    assert r.texto == turno.MENSAGEM_MIDIA_NAO_SUPORTADA
    assert [m["conteudo"] for m in historico_do_lead("lead-6")] == [
        "[imagem]", turno.MENSAGEM_MIDIA_NAO_SUPORTADA]

    _abrir_e_assumir("lead-7")
    r2 = turno.turno_midia_nao_suportada(1, "whatsapp", "lead-7", "sticker")
    assert r2.silenciado and r2.texto is None


# -------------------------------- mesma conversa nos três canais (1.6)

def test_mesma_conversa_igual_nos_tres_canais(monkeypatch, redis_falso):
    turno = importar("app.core.turno")
    wh = importar("app.api.webhook")
    tb = importar("app.api.telegram_bot")
    texto_llm = "Temos o **Civic 2019**!\n\n*   Automático\n*   48 mil km"
    esperado = "Temos o Civic 2019!\n\n- Automático\n- 48 mil km"
    urls = ["http://f/civic1.jpg", "http://f/civic2.jpg"]
    enviadas_wa, fotos_wa = [], []

    async def resposta(numero, texto, atraso=0):
        enviadas_wa.append(texto)

    async def foto(numero, url):
        fotos_wa.append(url)
        return True

    monkeypatch.setattr(wh, "enviar_resposta_humanizada", resposta)
    monkeypatch.setattr(wh, "enviar_foto_whatsapp", foto)
    monkeypatch.setattr(wh, "agente_grafo", GrafoRoteiro(texto_llm, urls))
    monkeypatch.setattr(tb, "agente_grafo", GrafoRoteiro(texto_llm, urls))

    asyncio.run(wh.processar_mensagem("A", "tem civic?"))
    resposta_tg, fotos_tg = asyncio.run(tb.processar_texto("B", "tem civic?"))
    sim = asyncio.run(turno.executar_turno(1, "simulador", "C", "tem civic?",
                                           grafo=GrafoRoteiro(texto_llm, urls)))

    assert enviadas_wa == [esperado] and resposta_tg == esperado and sim.texto == esperado
    assert fotos_wa == urls and fotos_tg == urls and sim.midias == urls
    canais = {lead: {m["canal"] for m in historico_do_lead(lead)} for lead in ("A", "B", "C")}
    assert canais == {"A": {"whatsapp"}, "B": {"telegram"}, "C": {"simulador"}}


# ------------------------------------------- WhatsApp: leitura (1.7)

def test_ler_webhook_le_todas_as_mensagens_do_pacote():
    from app.channels.whatsapp import CanalWhatsApp
    entradas = CanalWhatsApp().ler_webhook(_payload(
        _texto("oi"), _texto("tem civic?"), _texto("2019", numero="5582"),
        phone_number_id="PNID"))
    assert [(e.lead_id, e.tipo, e.texto) for e in entradas] == [
        ("5581", "texto", "oi"), ("5581", "texto", "tem civic?"), ("5582", "texto", "2019")]
    assert {e.id_canal for e in entradas} == {"PNID"}
    assert entradas[0].hora == 1700000000


def test_ler_webhook_ignora_status_e_lixo():
    from app.channels.whatsapp import CanalWhatsApp
    canal = CanalWhatsApp()
    assert canal.ler_webhook(_payload(statuses=[{"id": "wamid.1", "status": "read"}])) == []
    assert canal.ler_webhook({}) == []
    assert canal.ler_webhook([]) == []
    assert canal.ler_webhook({"entry": "x"}) == []
    assert canal.ler_webhook(_payload({"type": "text", "text": {"body": "sem id"}})) == []


def test_ler_webhook_classifica_os_tipos():
    from app.channels.whatsapp import CanalWhatsApp
    entradas = CanalWhatsApp().ler_webhook(_payload(
        _msg("audio", audio={"id": "MID", "mime_type": "audio/ogg"}),
        _msg("image", image={"id": "IMG"}),
        _msg("reaction", reaction={"emoji": "👍"}),
        _msg("button", button={"text": "Quero ver"}),
        _msg("interactive", interactive={"type": "button_reply",
                                         "button_reply": {"id": "b1", "title": "Sim"}}),
    ))
    assert [(e.tipo, e.texto, e.id_midia, e.tipo_original) for e in entradas] == [
        ("audio", "", "MID", "audio"),
        ("nao_suportado", "", "", "image"),
        ("texto", "Quero ver", "", "button"),
        ("texto", "Sim", "", "interactive"),
    ]


# -------------------------------------------- WhatsApp: POST /webhook

@pytest.fixture
def webhook_http(monkeypatch):
    from fastapi.testclient import TestClient
    wh = importar("app.api.webhook")
    agendadas, vistos = [], set()

    async def processar_falso(numero, texto, id_audio=None, loja_id=1):
        agendadas.append(("processar", numero, texto, id_audio, loja_id))

    async def midia_falsa(numero, tipo_original, loja_id=1):
        agendadas.append(("midia", numero, tipo_original, loja_id))

    async def dedup_memoria(canal, id_mensagem):
        if id_mensagem in vistos:
            return True
        vistos.add(id_mensagem)
        return False

    monkeypatch.setattr(wh, "processar_mensagem", processar_falso)
    monkeypatch.setattr(wh, "responder_midia_nao_suportada", midia_falsa)
    monkeypatch.setattr(wh, "ja_processada", dedup_memoria)
    monkeypatch.setattr(wh, "WHATSAPP_APP_SECRET", SEGREDO)
    wh._ultima_recebida.clear()
    return wh, TestClient(wh.app), agendadas


def _post(cliente, dados):
    corpo = json.dumps(dados).encode()
    assinatura = "sha256=" + hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()
    return cliente.post("/webhook", content=corpo, headers={
        "Content-Type": "application/json", "X-Hub-Signature-256": assinatura})


def test_post_com_3_mensagens_agenda_as_3(webhook_http):
    wh, cliente, agendadas = webhook_http
    resposta = _post(cliente, _payload(_texto("oi"), _texto("tem civic?"),
                                       _msg("audio", audio={"id": "MID"})))
    assert resposta.status_code == 200
    assert agendadas == [
        ("processar", "5581", "oi", None, 1),
        ("processar", "5581", "tem civic?", None, 1),
        ("processar", "5581", None, "MID", 1),
    ]


def test_post_com_imagem_agenda_o_aviso(webhook_http):
    wh, cliente, agendadas = webhook_http
    _post(cliente, _payload(_msg("image", image={"id": "IMG"})))
    assert agendadas == [("midia", "5581", "image", 1)]


def test_post_ignora_duplicata_dentro_do_mesmo_pacote(webhook_http):
    wh, cliente, agendadas = webhook_http
    _post(cliente, _payload(_texto("oi", id_="wamid.X"), _texto("oi", id_="wamid.X")))
    assert len(agendadas) == 1


def test_post_lembra_a_ultima_mensagem_para_marcar_lida(webhook_http):
    wh, cliente, agendadas = webhook_http
    _post(cliente, _payload(_texto("oi", id_="wamid.A"), _texto("tudo bem?", id_="wamid.B")))
    assert wh._ultima_recebida[(1, "5581")] == "wamid.B"


# ------------------------------------------ WhatsApp: envio e "lida"

def test_whatsapp_marca_lida_antes_de_responder(monkeypatch, redis_falso):
    wh = importar("app.api.webhook")
    marcadas = []

    async def marcar(id_mensagem, digitando=False):
        marcadas.append((id_mensagem, digitando))
        return True

    async def resposta(numero, texto, atraso=0):
        pass

    monkeypatch.setattr(wh.canal_whatsapp, "marcar_lida", marcar)
    monkeypatch.setattr(wh, "enviar_resposta_humanizada", resposta)
    monkeypatch.setattr(wh, "agente_grafo", GrafoRoteiro("Oi!"))
    wh._ultima_recebida[(1, "5581")] = "wamid.ULTIMA"

    asyncio.run(wh.processar_mensagem("5581", "oi"))
    assert marcadas == [("wamid.ULTIMA", True)]
    assert (1, "5581") not in wh._ultima_recebida


def test_whatsapp_em_silencio_nao_marca_lida(monkeypatch, redis_falso):
    wh = importar("app.api.webhook")
    marcadas = []

    async def marcar(id_mensagem, digitando=False):
        marcadas.append(id_mensagem)
        return True

    monkeypatch.setattr(wh.canal_whatsapp, "marcar_lida", marcar)
    monkeypatch.setattr(wh, "agente_grafo", GrafoRoteiro("Oi!"))
    _abrir_e_assumir("5599")
    wh._ultima_recebida[(1, "5599")] = "wamid.Z"
    asyncio.run(wh.processar_mensagem("5599", "oi"))
    assert marcadas == []


# ------------------------------------------------ contrato dos canais

def test_enviar_resultado_manda_bolhas_e_depois_fotos():
    from app.channels.base import enviar_resultado
    from app.channels.simulador import CanalSimulador
    from app.core.turno import ResultadoTurno
    canal = CanalSimulador()
    r = ResultadoTurno(texto="Primeira.\n\nSegunda.", midias=["http://f/1.jpg"])
    asyncio.run(enviar_resultado(canal, "lead", r))
    assert canal.enviadas == [("texto", "Primeira."), ("texto", "Segunda."), ("midia", "http://f/1.jpg")]


def test_enviar_resultado_silenciado_nao_envia_nada():
    from app.channels.base import enviar_resultado
    from app.channels.simulador import CanalSimulador
    from app.core.turno import ResultadoTurno
    canal = CanalSimulador()
    asyncio.run(enviar_resultado(canal, "lead", ResultadoTurno(silenciado=True)))
    assert canal.enviadas == []


def test_template_e_janela_ficam_para_a_etapa_2():
    from app.channels.simulador import CanalSimulador
    canal = CanalSimulador()
    with pytest.raises(NotImplementedError):
        asyncio.run(canal.enviar_template("lead", "modelo", []))
    with pytest.raises(NotImplementedError):
        canal.janela_aberta(1, "lead")


def test_telegram_le_texto_audio_e_foto():
    from app.channels.telegram import CanalTelegram
    canal = CanalTelegram(bot=None, bot_id="999")
    chat = SimpleNamespace(id=777)

    def update(**campos):
        base = dict(message_id=5, date=None, text=None, voice=None, audio=None)
        base.update(campos)
        return SimpleNamespace(message=SimpleNamespace(**base), effective_chat=chat)

    [t] = canal.ler_webhook(update(text="oi"))
    assert (t.tipo, t.texto, t.lead_id, t.id_externo) == ("texto", "oi", "777", "999:777:5")
    [a] = canal.ler_webhook(update(voice=SimpleNamespace(file_id="F1", mime_type="audio/ogg")))
    assert (a.tipo, a.id_midia) == ("audio", "F1")
    [f] = canal.ler_webhook(update(photo=[object()]))
    assert (f.tipo, f.tipo_original) == ("nao_suportado", "image")

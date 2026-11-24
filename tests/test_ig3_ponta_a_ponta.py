"""
IG3 (I7/I8): ponta a ponta com o SERVIDOR FALSO DA META (tests/meta_falsa.py, HTTP de verdade em
127.0.0.1). Nenhuma chamada sai do computador; a IA é falsa.

comentário no post do Civic -> mensagem privada citando o carro -> o cliente responde no direct ->
conversa (o Léo sabe do carro) -> pede o WhatsApp e passa o telefone -> escreve no WhatsApp da
loja -> o painel mostra UM cliente com o histórico dos dois canais.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app import canais, lojas
from app.api import webhook_instagram as wi
from banco import conectar
from tests.meta_falsa import servidor_meta_falsa

PAYLOADS = Path(__file__).resolve().parent / "payloads" / "instagram"
CONTA, POST, TOKEN = "17841400000000001", "18100000000000001", "token-falso-ponta"
SEGREDO_IG, SEGREDO_WA = "segredo-ig-falso", "segredo-wa-falso"


def _ler(sql, args=()):
    c = conectar()
    try:
        return [dict(l) for l in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _assinar(corpo: bytes, segredo: str) -> dict:
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest(),
            "Content-Type": "application/json"}


class LLM:
    """Responde conforme a fala do cliente (e anota o que recebeu)."""
    vistos: list = []

    def invoke(self, mensagens):
        tudo = " ".join(str(getattr(m, "content", m)) for m in mensagens[1:])
        self.vistos.append(tudo)
        ultima = str(getattr(mensagens[-1], "content", ""))
        if "zap" in ultima:
            return AIMessage(content="Claro!")
        if "sou eu" in ultima:
            return AIMessage(content="Oi de novo! Seguimos por aqui.")
        return AIMessage(content="Que bom! O Civic está aqui na loja, quer as fotos?")


@pytest.fixture
def ambiente(monkeypatch):
    from app.core import agent
    import app.api.webhook as wa
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", SEGREDO_IG)
    monkeypatch.setenv("INSTAGRAM_TOKEN_PONTA", TOKEN)
    monkeypatch.setattr(wa, "WHATSAPP_APP_SECRET", SEGREDO_WA)
    monkeypatch.setattr(wi, "ESPERA_DO_ECO_S", 0)
    monkeypatch.setattr(agent, "llm", LLM())
    LLM.vistos = []

    async def aguardar_vez(loja_id, lead_id, texto):          # (Redis em memória, como no IG1)
        return texto, "t"

    async def liberar(*a, **k):
        return True

    async def nada(*a, **k):
        return None
    vistos = set()

    async def dedup(canal, mid):
        if (canal, mid) in vistos:
            return True
        vistos.add((canal, mid))
        return False
    monkeypatch.setattr("app.core.turno.aguardar_vez", aguardar_vez)
    monkeypatch.setattr("app.redis_lock.liberar_lock", liberar)
    monkeypatch.setattr(wa, "aguardar_vez", aguardar_vez)
    monkeypatch.setattr(wa, "liberar_lock", liberar)
    monkeypatch.setattr(wa, "ja_processada", dedup)
    monkeypatch.setattr(wi, "ja_processada", dedup)
    monkeypatch.setattr(wa, "calcular_atraso", lambda *a, **k: _zero())
    monkeypatch.setattr(wa, "sinalizar_leitura", nada)
    enviados_wa = []

    async def enviar_wa(numero, texto, atraso=0, *, loja_id):     # o WhatsApp não sai do PC
        enviados_wa.append((loja_id, numero, texto))
    monkeypatch.setattr(wa, "enviar_resposta_humanizada", enviar_wa)

    canais.cadastrar_canal(1, "instagram", CONTA, "INSTAGRAM_TOKEN_PONTA")
    canais.cadastrar_canal(1, "whatsapp", "phone-id-falso-ponta", "WA_TOKEN_FALSO")
    lojas.salvar_config(1, {"modulos.instagram": True, "instagram.responder_comentarios": True,
                            "instagram.palavras_comentario": ["valor", "tem", "troca", "quero"], "instagram.resposta_publica": True,
                            "instagram.whatsapp_da_loja": "81 98888-7777"}, "teste")
    c = conectar()
    c.execute("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) "
              "VALUES (1, 'Honda', 'Civic', 2019, 50000, 'Prata', 'Automático', 98000, 'disponivel')")
    c.commit()
    c.close()
    with servidor_meta_falsa({POST: "Honda Civic 2019 automático, revisado. Chama no direct!"}, {TOKEN}) as meta:
        monkeypatch.setenv("INSTAGRAM_API_URL", meta.url)
        yield {"meta": meta, "whatsapp": enviados_wa, "cliente": TestClient(wa.app)}


async def _zero():
    return 0.0


def _payload(nome, **troca):
    texto = (PAYLOADS / nome).read_text(encoding="utf-8")
    for velho, novo in troca.items():
        texto = texto.replace(velho, novo)
    return json.loads(texto)


def _direct(cliente, texto, mid):
    dados = _payload("mensagem_texto.json")
    dados["entry"][0]["messaging"][0]["sender"]["id"] = "9100000000000004"
    dados["entry"][0]["messaging"][0]["message"] = {"mid": mid, "text": texto}
    corpo = json.dumps(dados).encode()
    return cliente.post("/webhook/instagram", content=corpo, headers=_assinar(corpo, SEGREDO_IG))


def test_comentario_ate_o_mesmo_cliente_no_painel(ambiente):
    meta, cliente = ambiente["meta"], ambiente["cliente"]
    agora = datetime.now(timezone.utc).timestamp()

    # 1. comentário no post do Civic
    comentario = _payload("comentario_post.json")
    comentario["entry"][0]["time"] = int(agora)
    corpo = json.dumps(comentario).encode()
    assert cliente.post("/webhook/instagram", content=corpo, headers=_assinar(corpo, SEGREDO_IG)).status_code == 200
    [privada] = meta.privadas()
    assert privada["corpo"]["recipient"] == {"comment_id": "18000000000000001"}
    assert "Honda Civic 2019" in privada["corpo"]["message"]["text"] and "R$" not in privada["corpo"]["message"]["text"]
    assert [p["corpo"]["message"] for p in meta.pedidos if p["tipo"] == "replies"] == ["Te chamei no direct."]
    assert [p["post"] for p in meta.pedidos if p["tipo"] == "legenda"] == [POST]

    # 2. o eco da mensagem privada (do próprio Léo) não muda nada
    eco = _payload("eco_do_leo.json", aWdfZmljdGljaW9fbGVv=privada["message_id"],
                   **{"9100000000000001": "9100000000000004"})
    corpo = json.dumps(eco).encode()
    cliente.post("/webhook/instagram", content=corpo, headers=_assinar(corpo, SEGREDO_IG))
    from app.handoff import estado_do_handoff
    assert estado_do_handoff("ig:9100000000000004", 1) == "ativo"

    # 3. o cliente responde no direct: o Léo sabe do carro
    _direct(cliente, "quero sim", "mid-cli-1")
    assert "Honda Civic 2019" in LLM.vistos[0]
    assert meta.textos_enviados()[-1].startswith("Que bom! O Civic")

    # 4. pede o WhatsApp e passa o telefone: o link wa.me da loja vai junto (código)
    _direct(cliente, "pode me chamar no zap? meu número é (81) 99999-8888", "mid-cli-2")
    ultimo = meta.textos_enviados()[-1]
    assert "https://wa.me/5581988887777" in ultimo
    assert _ler("SELECT telefone FROM leads WHERE loja_id = 1 AND lead_id = 'ig:9100000000000004'") == \
        [{"telefone": "5581999998888"}]

    # 5. o cliente escreve no WhatsApp da loja, do telefone que passou
    wa = {"object": "whatsapp_business_account", "entry": [{"id": "x", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"phone_number_id": "phone-id-falso-ponta"},
        "messages": [{"from": "558199998888", "id": "wamid.ponta1", "timestamp": str(int(agora)), "type": "text",
                      "text": {"body": "oi, sou eu do instagram"}}]}}]}]}
    corpo = json.dumps(wa).encode()
    assert cliente.post("/webhook", content=corpo, headers=_assinar(corpo, SEGREDO_WA)).status_code == 200
    assert [t for _, _, t in ambiente["whatsapp"]] == ["Oi de novo! Seguimos por aqui."]

    # 6. o painel: UM cliente, os dois canais, o histórico junto
    from app.api_painel.conversa import montar_conversa
    from app.api_painel.leads import montar_leads
    meus = [i for i in montar_leads(1)["itens"] if i["lead"] in ("ig:9100000000000004", "5581999998888")]
    assert len(meus) == 1 and meus[0]["canais"] == ["Instagram", "WhatsApp"] and meus[0]["como_chegou"] == "Comentário"
    conversa = montar_conversa(1, "ig:9100000000000004", {"nome": "Ana", "papel": "dono", "usuario_id": 1})
    textos = [m["texto"] for m in conversa["mensagens"]]
    assert "oi, sou eu do instagram" in textos and "quero sim" in textos
    assert {m["canal"] for m in conversa["mensagens"]} == {"instagram", "whatsapp"}


def test_servidor_falso_recusa_token_errado(ambiente, monkeypatch):
    import asyncio
    from app.channels.instagram import CanalInstagram
    monkeypatch.setenv("INSTAGRAM_TOKEN_PONTA", "token-errado")
    r = asyncio.run(CanalInstagram(1).enviar_texto_detalhado("ig:1", "oi"))
    assert not r.ok

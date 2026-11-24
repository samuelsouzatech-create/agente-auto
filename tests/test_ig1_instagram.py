"""
IG1 (Maratona 4): o canal Instagram com os payloads FALSOS do IG0 (tests/payloads/instagram/).
OFFLINE: nenhuma chamada à Meta (o "envio" é um canal falso que guarda o que mandaria), IA falsa,
duas lojas. Segue I1, I2, I3 e I5 do plano mestre e o I8 (tabela de testes).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

import banco
from app import canais, lojas
from app.api import webhook_instagram as wi
from app.channels.instagram import (CanalInstagram, LIMITE_BYTES, MENSAGEM_NAO_ENTENDI, dividir_no_limite,
                                    lead_do_instagram)
from app.estado_loja import colocar_no_ar
from app.handoff import estado_do_handoff
from app.instagram import anotar_origem, e_eco_do_leo, origem_do_lead
from app.lojas import criar_loja
from app.resultado_envio import ResultadoEnvio
from banco import conectar

PAYLOADS = Path(__file__).resolve().parent / "payloads" / "instagram"
CONTA_A, CONTA_B = "17841400000000001", "17841400000000002"
SEGREDO = "segredo-falso-de-teste"


def _payload(nome, **troca) -> dict:
    texto = (PAYLOADS / nome).read_text(encoding="utf-8")
    for velho, novo in troca.items():
        texto = texto.replace(velho, novo)
    return json.loads(texto)


def _ler(sql, args=()):
    c = conectar()
    try:
        return [dict(l) for l in c.execute(sql, args).fetchall()]
    finally:
        c.close()


@pytest.fixture
def lojas_ig(monkeypatch):
    """Loja A (a 1, no ar) com a conta A; loja B (no ar) com a conta B. Token só no .env (falso)."""
    monkeypatch.setenv("INSTAGRAM_TOKEN_A", "token-falso-a")
    monkeypatch.setenv("INSTAGRAM_TOKEN_B", "token-falso-b")
    loja_b = criar_loja("Loja B Instagram")
    colocar_no_ar(loja_b)
    canais.cadastrar_canal(1, "instagram", CONTA_A, "INSTAGRAM_TOKEN_A")
    canais.cadastrar_canal(loja_b, "instagram", CONTA_B, "INSTAGRAM_TOKEN_B")
    return 1, loja_b


class MetaFalsa:
    """Servidor falso da Meta: guarda cada envio e devolve um id de mensagem."""

    def __init__(self):
        self.envios = []

    async def postar(self, url, token, corpo):
        self.envios.append({"url": url, "token": token, "corpo": corpo})
        return ResultadoEnvio(ok=True, id_externo=f"mid-leo-{len(self.envios)}")


@pytest.fixture(autouse=True)
def sem_redis(monkeypatch):
    """Debounce, trava e duplicata já são testados no WhatsApp (mesmo código). Aqui, versões em
    memória: o cliente do Redis fica preso ao primeiro laço assíncrono e cada teste abre outro."""
    vistos = set()

    async def ja_processada(canal, id_mensagem):
        if (canal, id_mensagem) in vistos:
            return True
        vistos.add((canal, id_mensagem))
        return False

    async def aguardar_vez(loja_id, lead_id, texto):
        return texto, "token-falso"

    async def liberar_lock(*a, **k):
        return True
    monkeypatch.setattr(wi, "ja_processada", ja_processada)
    monkeypatch.setattr("app.core.turno.aguardar_vez", aguardar_vez)
    monkeypatch.setattr("app.redis_lock.liberar_lock", liberar_lock)


@pytest.fixture
def meta(monkeypatch):
    falsa = MetaFalsa()
    monkeypatch.setattr(wi, "FABRICA_DO_CANAL", lambda loja_id: CanalInstagram(loja_id, postar=falsa.postar))
    monkeypatch.setattr(wi, "ESPERA_DO_ECO_S", 0)
    return falsa


class LLMFalso:
    def __init__(self, *textos):
        self.textos = list(textos)

    def invoke(self, mensagens):
        return AIMessage(content=self.textos.pop(0) if self.textos else "Certo.")


@pytest.fixture
def ia(monkeypatch):
    from app.core import agent

    def usar(*textos):
        monkeypatch.setattr(agent, "llm", LLMFalso(*textos))
    monkeypatch.setattr("app.redis_debounce.DEBOUNCE_SEGUNDOS", 0)
    return usar


def _rodar(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ I1: ler o webhook
def test_payload_de_texto_vira_mensagem_entrada():
    [m] = CanalInstagram().ler_webhook(_payload("mensagem_texto.json"))
    assert (m.canal, m.tipo, m.lead_id, m.id_canal) == ("instagram", "texto", "ig:9100000000000001", CONTA_A)
    assert m.id_externo == "aWdfZmljdGljaW9fMDAx" and "Civic" in m.texto


def test_varias_mensagens_no_mesmo_pacote_chegam_todas():
    assert [m.texto for m in CanalInstagram().ler_webhook(_payload("mensagem_varias.json"))] == \
        ["Bom dia", "Vocês financiam?"]


def test_nao_suportado_e_reacao():
    entradas = CanalInstagram().ler_direct(_payload("nao_suportado.json"))
    assert [(e.mensagem.tipo, e.mensagem.tipo_original) for e in entradas] == [("nao_suportado", "share")]


def test_eco_e_marcado_e_o_lead_e_o_cliente():
    [e] = CanalInstagram().ler_direct(_payload("eco_vendedor.json"))
    assert e.eco and e.mensagem.lead_id == "ig:9100000000000001"
    assert CanalInstagram().ler_webhook(_payload("eco_vendedor.json")) == []     # eco não é cliente


def test_lixo_nao_derruba():
    canal = CanalInstagram()
    for lixo in (None, [], {}, {"object": "page"}, {"object": "instagram", "entry": "x"},
                 {"object": "instagram", "entry": [{"messaging": [{"message": {"text": "sem mid"}}]}]}):
        assert canal.ler_webhook(lixo) == []


def test_lead_tem_prefixo_ig_e_nunca_colide_com_telefone():
    assert lead_do_instagram("5581999990000") == "ig:5581999990000"
    assert lead_do_instagram("ig:123") == "ig:123" and lead_do_instagram("") == ""


def test_resposta_longa_dividida_no_limite():
    texto = ("Ação é ótima. " * 200).strip()
    pedacos = dividir_no_limite(texto)
    assert len(pedacos) > 1 and all(len(p.encode("utf-8")) <= LIMITE_BYTES for p in pedacos)
    assert " ".join(pedacos).replace("  ", " ") == texto


def test_envio_divide_e_usa_a_conta_e_o_token_da_loja(lojas_ig):
    falsa = MetaFalsa()
    canal = CanalInstagram(lojas_ig[1], postar=falsa.postar)
    assert _rodar(canal.enviar_texto("ig:9100000000000001", "x" * 2500))
    assert len(falsa.envios) == 3
    assert all(CONTA_B in e["url"] and e["token"] == "token-falso-b" for e in falsa.envios)
    assert falsa.envios[0]["corpo"]["recipient"] == {"id": "9100000000000001"}
    assert canal.ids_enviados == ["mid-leo-1", "mid-leo-2", "mid-leo-3"]


def test_token_so_pelo_token_ref_e_nunca_no_banco(lojas_ig, monkeypatch):
    from app.credenciais import SemCredencial, credencial_instagram
    cred = credencial_instagram(1)
    assert cred.token == "token-falso-a" and "token-falso-a" not in repr(cred)
    linhas = _ler("SELECT * FROM canais WHERE tipo = 'instagram'")
    assert all("token-falso" not in json.dumps(l, default=str) for l in linhas)
    monkeypatch.delenv("INSTAGRAM_TOKEN_A")
    with pytest.raises(SemCredencial):
        credencial_instagram(1)
    loja_c = criar_loja("Loja C sem Instagram")
    with pytest.raises(SemCredencial):
        credencial_instagram(loja_c)


# ------------------------------------------------------------------ I2: a porta
def _assinar(corpo: bytes, segredo=SEGREDO) -> str:
    return "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", SEGREDO)
    monkeypatch.setenv("INSTAGRAM_VERIFY_TOKEN", "verifica-falso")
    from app.api.webhook import app
    return TestClient(app)


def _post(cliente, dados, segredo=SEGREDO, assinatura=None):
    corpo = json.dumps(dados).encode()
    cab = {"X-Hub-Signature-256": assinatura if assinatura is not None else _assinar(corpo, segredo),
           "Content-Type": "application/json"}
    return cliente.post("/webhook/instagram", content=corpo, headers=cab)


def test_verificacao_get(cliente):
    ok = cliente.get("/webhook/instagram", params={"hub.mode": "subscribe", "hub.verify_token": "verifica-falso",
                                                    "hub.challenge": "123"})
    assert ok.status_code == 200 and ok.text == "123"
    assert cliente.get("/webhook/instagram", params={"hub.mode": "subscribe", "hub.verify_token": "x",
                                                      "hub.challenge": "1"}).status_code == 403


def test_assinatura_invalida_ou_segredo_ausente_recusa(cliente, monkeypatch, lojas_ig):
    chamadas = []
    monkeypatch.setattr(wi, "processar_texto", lambda *a: chamadas.append(a))
    assert _post(cliente, _payload("mensagem_texto.json"), assinatura="sha256=errada").status_code == 403
    assert _post(cliente, _payload("mensagem_texto.json"), assinatura="").status_code == 403
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "")
    assert _post(cliente, _payload("mensagem_texto.json")).status_code == 403
    assert chamadas == []


def test_conta_desconhecida_200_ignora_e_anota(cliente, monkeypatch):
    chamadas, anotadas = [], []
    monkeypatch.setattr(wi, "processar_texto", lambda *a: chamadas.append(a))
    monkeypatch.setattr(wi, "registrar_canal_desconhecido", lambda tipo, ident: anotadas.append((tipo, ident)))
    r = _post(cliente, _payload("mensagem_texto.json", **{CONTA_A: "17849999999999999"}))
    assert r.status_code == 200 and chamadas == [] and anotadas == [("instagram", "17849999999999999")]


def test_mensagem_agenda_o_turno_da_loja_certa(cliente, monkeypatch, lojas_ig):
    chamadas = []

    async def espiao(*a):
        chamadas.append(a)
    monkeypatch.setattr(wi, "processar_texto", espiao)
    _post(cliente, _payload("mensagem_varias.json", **{CONTA_A: CONTA_B}))
    assert [c[0] for c in chamadas] == [lojas_ig[1], lojas_ig[1]]
    assert [c[2] for c in chamadas] == ["Bom dia", "Vocês financiam?"]


def test_duplicata_processada_uma_vez(cliente, monkeypatch, lojas_ig):
    chamadas = []

    async def espiao(*a):
        chamadas.append(a)
    monkeypatch.setattr(wi, "processar_texto", espiao)
    dados = _payload("mensagem_texto.json", aWdfZmljdGljaW9fMDAx="mid-unico-dup-1")
    _post(cliente, dados)
    _post(cliente, dados)
    assert len(chamadas) == 1


# ------------------------------------------------------------------ o turno de verdade (IA falsa)
def test_turno_completo_responde_pela_conta_da_loja(lojas_ig, meta, ia):
    ia("Oi! O Civic está disponível sim.")
    _rodar(wi.processar_texto(1, "ig:9100000000000010", "o civic ainda tem?"))
    assert [e["corpo"]["message"]["text"] for e in meta.envios] == ["Oi! O Civic está disponível sim."]
    assert CONTA_A in meta.envios[0]["url"]
    falas = _ler("SELECT direcao, canal, id_externo FROM mensagens WHERE lead_id = 'ig:9100000000000010' ORDER BY id")
    assert [(f["direcao"], f["canal"]) for f in falas] == [("cliente", "instagram"), ("leo", "instagram")]
    assert falas[1]["id_externo"] == "mid-leo-1"


def test_nao_suportado_responde_curto_sem_ia(lojas_ig, meta):
    _rodar(wi.processar_nao_entendido(1, "ig:9100000000000011", "share"))
    assert [e["corpo"]["message"]["text"] for e in meta.envios] == [MENSAGEM_NAO_ENTENDI]
    assert "🙂" not in MENSAGEM_NAO_ENTENDI


def test_loja_em_teste_fica_em_silencio(meta, ia, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_TOKEN_T", "token-falso-t")
    loja = criar_loja("Loja em teste IG")
    canais.cadastrar_canal(loja, "instagram", "17841400000000077", "INSTAGRAM_TOKEN_T")
    ia("não deveria sair")
    _rodar(wi.processar_texto(loja, "ig:9100000000000012", "oi"))
    assert meta.envios == []
    assert _ler("SELECT * FROM mensagens WHERE loja_id = ?", (loja,)) == []


def test_duas_lojas_nao_se_cruzam(lojas_ig, meta, ia):
    ia("Resposta da loja A.", "Resposta da loja B.")
    _rodar(wi.processar_texto(1, "ig:9100000000000020", "oi A"))
    _rodar(wi.processar_texto(lojas_ig[1], "ig:9100000000000021", "oi B"))
    assert [CONTA_A in e["url"] for e in meta.envios] == [True, False]
    assert [CONTA_B in e["url"] for e in meta.envios] == [False, True]
    assert _ler("SELECT DISTINCT loja_id FROM mensagens WHERE lead_id = 'ig:9100000000000021'") == \
        [{"loja_id": lojas_ig[1]}]


# ------------------------------------------------------------------ I3: eco
def test_eco_da_resposta_do_leo_e_descartado(lojas_ig, meta, ia):
    """O teste dedicado do plano: cada resposta do Léo volta como eco; ele NÃO vira 'vendedor assumiu'."""
    lead = "ig:9100000000000001"
    ia("Está sim! Quer ver mais fotos?")
    _rodar(wi.processar_texto(1, lead, "o civic ainda tem?"))
    eco = _payload("eco_do_leo.json", aWdfZmljdGljaW9fbGVv="mid-leo-1")
    [entrada] = CanalInstagram().ler_direct(eco)
    assert e_eco_do_leo(1, lead, entrada.mensagem.id_externo)
    _rodar(wi.processar_eco(1, lead, entrada.mensagem.id_externo, entrada.mensagem.texto))
    assert estado_do_handoff(lead, 1) == "ativo"
    assert _ler("SELECT COUNT(*) AS n FROM mensagens WHERE lead_id = ? AND direcao = 'vendedor'", (lead,)) == [{"n": 0}]


def test_eco_de_vendedor_pelo_app_deixa_o_leo_quieto(lojas_ig, meta, ia):
    lead = "ig:9100000000000001"
    [entrada] = CanalInstagram().ler_direct(_payload("eco_vendedor.json"))
    _rodar(wi.processar_eco(1, lead, entrada.mensagem.id_externo, entrada.mensagem.texto))
    assert estado_do_handoff(lead, 1) == "humano_assumiu"
    [fala] = _ler("SELECT direcao, autor, conteudo FROM mensagens WHERE lead_id = ?", (lead,))
    assert fala["direcao"] == "vendedor" and "Carlos" in fala["conteudo"]
    ia("não deveria sair")
    _rodar(wi.processar_texto(1, lead, "pode sim"))
    assert meta.envios == []                                       # o Léo ficou quieto


def test_eco_do_leo_de_outra_loja_nao_conta(lojas_ig, meta, ia):
    ia("Oi da A.")
    _rodar(wi.processar_texto(1, "ig:9100000000000030", "oi"))
    assert not e_eco_do_leo(lojas_ig[1], "ig:9100000000000030", "mid-leo-1")


def test_eco_pela_porta_vai_para_o_segundo_plano(cliente, monkeypatch, lojas_ig):
    ecos, textos = [], []

    async def espiao_eco(*a):
        ecos.append(a)

    async def espiao_texto(*a):
        textos.append(a)
    monkeypatch.setattr(wi, "processar_eco", espiao_eco)
    monkeypatch.setattr(wi, "processar_texto", espiao_texto)
    _post(cliente, _payload("eco_vendedor.json"))
    assert textos == [] and [e[1] for e in ecos] == ["ig:9100000000000001"]


# ------------------------------------------------------------------ I5: origem do lead
def test_origem_direta_e_anuncio_e_a_primeira_fica(lojas_ig):
    anotar_origem(1, "ig:1", "direto")
    assert origem_do_lead(1, "ig:1") == "direto"
    anotar_origem(1, "ig:1", "anuncio", "238")
    assert origem_do_lead(1, "ig:1") == "direto"
    anotar_origem(1, "ig:2", "anuncio", "238")
    assert origem_do_lead(1, "ig:2") == "anuncio" and origem_do_lead(lojas_ig[1], "ig:2") is None
    anotar_origem(1, "ig:3", "invalida")
    assert origem_do_lead(1, "ig:3") is None


def test_referral_de_anuncio_vira_origem_anuncio():
    dados = _payload("mensagem_texto.json")
    dados["entry"][0]["messaging"][0]["referral"] = {"source": "ADS", "ad_id": "238000"}
    [e] = CanalInstagram().ler_direct(dados)
    assert (e.origem, e.origem_detalhe) == ("anuncio", "238000")
    [e2] = CanalInstagram().ler_direct(_payload("mensagem_texto.json"))
    assert e2.origem == "direto"


def test_porta_grava_a_origem(cliente, monkeypatch, lojas_ig):
    async def nada(*a):
        return None
    monkeypatch.setattr(wi, "processar_texto", nada)
    _post(cliente, _payload("mensagem_texto.json", aWdfZmljdGljaW9fMDAx="mid-origem-1"))
    assert origem_do_lead(1, "ig:9100000000000001") == "direto"


# ------------------------------------------------------------------ remarketing só com a janela aberta
def test_remarketing_no_instagram_so_dentro_da_janela(lojas_ig, monkeypatch):
    from app.custos import Uso
    from app.jobs import remarketing as rmk
    from app.relogio import para_banco
    lojas.salvar_config(1, {"modulos.remarketing": True, "remarketing.limite_mensal": 50}, "teste")
    agora = datetime(2026, 11, 18, 14, 0, tzinfo=timezone.utc)      # quarta, 11:00 em Recife
    c = conectar()
    for lead, horas in (("ig:fechada", 72), ("ig:aberta", 20)):
        c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
                  "VALUES (?, 1, 'instagram', 'cliente', 'oi', ?)", (lead, para_banco(agora - timedelta(hours=horas))))
        c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
                  "VALUES (?, 1, 'instagram', 'leo', 'Oi!', ?)", (lead, para_banco(agora - timedelta(hours=horas - 1))))
    c.commit()
    c.close()
    enviados = []

    class Enviador:
        async def texto(self, loja_id, canal, lead_id, texto):
            enviados.append((canal, lead_id))
            return ResultadoEnvio(ok=True, id_externo="x")

        async def modelo(self, *a):
            enviados.append(("modelo",) + a[:2])
            return ResultadoEnvio(ok=True, id_externo="y")
    rmk.rodar_remarketing(agora, envio_real=True, pausa_s=0, lojas=[1], enviador=Enviador(),
                          redator=lambda *a: ("Oi! Ainda procura carro?", Uso(1, 1, 0)))
    assert ("instagram", "ig:fechada") not in enviados and not any(e[0] == "modelo" for e in enviados)
    estados = {l["lead_id"]: l["estado"] for l in _ler("SELECT lead_id, estado FROM remarketing_envios WHERE loja_id = 1")}
    assert estados.get("ig:fechada") in (None, "bloqueado")


# ------------------------------------------------------------------ migração 21
def test_migracao_21_aplicada_e_registrada():
    assert banco.versao_schema() == banco.VERSAO_SCHEMA == 21
    assert {"instagram_comentarios", "instagram_legendas", "clientes_vinculados", "pedidos_exclusao"} <= set(banco.tabelas())
    colunas = {(l["table_name"], l["column_name"]) for l in _ler(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_name IN ('mensagens', 'leads')")}
    assert {("mensagens", "id_externo"), ("leads", "origem"), ("leads", "origem_detalhe"),
            ("leads", "telefone"), ("leads", "telefone_em")} <= colunas


def test_migracao_21_sobe_da_20_sem_apagar_dado(tmp_path, monkeypatch):
    """Banco novo só com a 20, dados dentro, depois a 21: tudo continua lá."""
    import psycopg
    from psycopg import sql
    url = banco.url_do_banco()
    nome = banco.nome_do_banco(url) + "_m21"
    admin = banco.trocar_nome_do_banco(url, "postgres")
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(nome)))
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nome)))
    so_20 = tmp_path / "so20"
    so_20.mkdir()
    (so_20 / "020_base_postgres.sql").write_text(
        (banco.PASTA_MIGRACOES / "020_base_postgres.sql").read_text(encoding="utf-8"), encoding="utf-8")
    original = banco.PASTA_MIGRACOES
    url_m21 = banco.trocar_nome_do_banco(url, nome)
    try:
        banco.apontar_para(url_m21)
        monkeypatch.setattr(banco, "PASTA_MIGRACOES", so_20)
        assert banco.migrar() == [20]
        c = conectar()
        c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo) VALUES ('x', 1, 'whatsapp', 'cliente', 'antes')")
        c.execute("INSERT INTO leads (lead_id, loja_id, nome) VALUES ('x', 1, 'Ana')")
        c.commit()
        c.close()
        monkeypatch.setattr(banco, "PASTA_MIGRACOES", original)
        assert banco.migrar() == [21]
        assert _ler("SELECT conteudo, id_externo FROM mensagens WHERE lead_id = 'x'") == [{"conteudo": "antes", "id_externo": None}]
        assert _ler("SELECT nome, origem FROM leads WHERE lead_id = 'x'") == [{"nome": "Ana", "origem": None}]
        assert banco.migrar() == []
    finally:
        banco.fechar_pools()
        banco.apontar_para(url)
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(nome)))

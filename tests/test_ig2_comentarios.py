"""
IG2 (Maratona 4): comentário vira conversa, com os payloads FALSOS do IG0. OFFLINE (servidor falso
da Meta), IA falsa, duas lojas.

Opção B (decisão do Samuel): a mensagem privada sabe do carro do post.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app import canais, comentarios_instagram as ci, lojas
from app.api import webhook_instagram as wi
from app.channels.instagram import CanalInstagram
from app.estado_loja import colocar_no_ar
from app.lojas import criar_loja
from app.resultado_envio import ResultadoEnvio
from banco import conectar

PAYLOADS = Path(__file__).resolve().parent / "payloads" / "instagram"
CONTA_A, CONTA_B = "17841400000000001", "17841400000000002"
AGORA = datetime.fromtimestamp(1764000500, tz=timezone.utc)      # o comentário acabou de chegar


def _payload(nome, **troca) -> dict:
    texto = (PAYLOADS / nome).read_text(encoding="utf-8")
    for velho, novo in troca.items():
        texto = texto.replace(velho, novo)
    return json.loads(texto)


def _comentario(nome="comentario_post.json", **troca):
    [c] = CanalInstagram().ler_comentarios(_payload(nome, **troca))
    return c


def _ler(sql, args=()):
    c = conectar()
    try:
        return [dict(l) for l in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _carro(loja_id, modelo, status="disponivel", preco=98000, ano=2019):
    c = conectar()
    linha = c.execute("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) "
                      "VALUES (?, 'Honda', ?, ?, 50000, 'Prata', 'Automático', ?, ?) RETURNING id",
                      (loja_id, modelo, ano, preco, status)).fetchone()
    c.commit()
    c.close()
    return linha["id"]


class MetaFalsa:
    def __init__(self, legenda="Honda Civic 2019 automático, revisado. Chama no direct!"):
        self.envios, self.legenda, self.leituras = [], legenda, 0

    async def postar(self, url, token, corpo):
        self.envios.append({"url": url, "corpo": corpo})
        return ResultadoEnvio(ok=True, id_externo=f"mid-priv-{len(self.envios)}")

    def canal(self, loja_id):
        falsa = self

        class Canal(CanalInstagram):
            async def ler_legenda(self, media_id):
                falsa.leituras += 1
                return falsa.legenda

            async def responder_comentario_em_publico(self, comment_id, texto):
                falsa.envios.append({"url": f"/{comment_id}/replies", "corpo": {"message": texto}})
                return ResultadoEnvio(ok=True, id_externo="pub-1")
        return Canal(loja_id, postar=falsa.postar)

    @property
    def privadas(self):
        return [e["corpo"]["message"]["text"] for e in self.envios if "recipient" in e["corpo"]]

    @property
    def publicas(self):
        return [e["corpo"]["message"] for e in self.envios if e["url"].endswith("/replies")]


@pytest.fixture
def lojas_ig(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_TOKEN_A", "token-falso-a")
    monkeypatch.setenv("INSTAGRAM_TOKEN_B", "token-falso-b")
    loja_b = criar_loja("Loja B Comentários")
    colocar_no_ar(loja_b)
    canais.cadastrar_canal(1, "instagram", CONTA_A, "INSTAGRAM_TOKEN_A")
    canais.cadastrar_canal(loja_b, "instagram", CONTA_B, "INSTAGRAM_TOKEN_B")
    for loja in (1, loja_b):
        lojas.salvar_config(loja, {"modulos.instagram": True, "instagram.responder_comentarios": True,
                                   "instagram.palavras_comentario": ["valor", "tem", "troca", "quero"]}, "teste")
    return 1, loja_b


@pytest.fixture(autouse=True)
def sem_redis(monkeypatch):
    """Como no IG1: debounce e trava em memória (o cliente do Redis fica preso ao 1º laço)."""
    async def aguardar_vez(loja_id, lead_id, texto):
        return texto, "token-falso"

    async def liberar_lock(*a, **k):
        return True
    monkeypatch.setattr("app.core.turno.aguardar_vez", aguardar_vez)
    monkeypatch.setattr("app.redis_lock.liberar_lock", liberar_lock)


@pytest.fixture
def meta(monkeypatch):
    falsa = MetaFalsa()
    monkeypatch.setattr(ci, "FABRICA_DO_CANAL", falsa.canal)
    monkeypatch.setattr(wi, "FABRICA_DO_CANAL", falsa.canal)
    monkeypatch.setattr(wi, "ESPERA_DO_ECO_S", 0)
    return falsa


def _tratar(loja_id, c):
    return asyncio.run(ci.tratar_comentario(loja_id, c, agora=AGORA))


# ------------------------------------------------------------------ as chaves
def test_chaves_nascem_desligadas_e_sem_emoji():
    loja = lojas.carregar_loja(1)
    assert loja.get("modulos.instagram") is False
    assert loja.get("instagram.responder_comentarios") is False
    assert loja.get("instagram.resposta_publica") is False
    from app.guarda_politica import tem_emoji
    for chave in ("texto_private_reply", "texto_comentario_item", "texto_comentario_vendido",
                  "texto_resposta_publica"):
        assert not tem_emoji(loja.get(f"instagram.{chave}")), chave
    assert loja.get("instagram.texto_resposta_publica") == "Te chamei no direct."


def test_chave_desligada_nao_envia_nada(lojas_ig, meta):
    lojas.salvar_config(1, {"instagram.responder_comentarios": False}, "teste")
    assert _tratar(1, _comentario()) == "desligado" and meta.envios == []
    lojas.salvar_config(1, {"instagram.responder_comentarios": True, "modulos.instagram": False}, "teste")
    assert _tratar(1, _comentario(**{"18000000000000001": "18000000000000011"})) == "desligado"
    assert meta.envios == []


# ------------------------------------------------------------------ Opção B: os 3 caminhos
def test_um_carro_disponivel_cita_modelo_e_ano_sem_preco(lojas_ig, meta):
    civic = _carro(1, "Civic")
    assert _tratar(1, _comentario()) == "respondido"
    [texto] = meta.privadas
    assert "Honda Civic 2019" in texto and "foto" in texto.lower()
    assert "R$" not in texto and "98" not in texto
    [linha] = _ler("SELECT caminho, item_id, estado FROM instagram_comentarios WHERE loja_id = 1")
    assert linha == {"caminho": "item", "item_id": civic, "estado": "respondido"}
    assert _ler("SELECT veiculo_id FROM interesse_veiculo WHERE loja_id = 1 AND lead_id = 'ig:9100000000000004'") == \
        [{"veiculo_id": civic}]


def test_carro_vendido_diz_que_saiu_e_oferece_parecidos(lojas_ig, meta):
    _carro(1, "Civic", status="vendido")
    _tratar(1, _comentario())
    [texto] = meta.privadas
    assert "já saiu" in texto and "parecid" in texto and "R$" not in texto
    assert _ler("SELECT caminho FROM instagram_comentarios") == [{"caminho": "vendido"}]


@pytest.mark.parametrize("legenda,carros", [
    ("Promoção de fim de semana!", ["Civic"]),                 # nenhum citado
    ("Civic e Corolla na loja!", ["Civic", "Corolla"]),          # mais de um
    ("", ["Civic"]),                                             # sem legenda
])
def test_nenhum_ou_mais_de_um_usa_o_generico(lojas_ig, meta, legenda, carros):
    for modelo in carros:
        _carro(1, modelo)
    meta.legenda = legenda
    _tratar(1, _comentario())
    assert meta.privadas == ["Oi! Vi seu comentário, te chamei por aqui para te ajudar."]
    assert _ler("SELECT caminho, item_id FROM instagram_comentarios") == [{"caminho": "generico", "item_id": None}]


def test_texto_da_loja_com_preco_vira_o_generico(lojas_ig, meta):
    _carro(1, "Civic")
    lojas.salvar_config(1, {"instagram.texto_comentario_item": "O {item} sai por R$ 98.000, quer?"}, "teste")
    _tratar(1, _comentario())
    assert meta.privadas == ["Oi! Vi seu comentário, te chamei por aqui para te ajudar."]


def test_texto_configuravel_por_loja_e_sem_emoji(lojas_ig, meta):
    _carro(1, "Civic")
    lojas.salvar_config(1, {"instagram.texto_comentario_item": "Olá! O {item} do post está aqui. 🚗 Quer fotos?"}, "teste")
    _tratar(1, _comentario())
    assert meta.privadas == ["Olá! O Honda Civic 2019 do post está aqui. Quer fotos?"]


def test_legenda_guardada_por_post(lojas_ig, meta):
    _carro(1, "Civic")
    _tratar(1, _comentario())
    _tratar(1, _comentario("comentario_post_entry_direto.json"))     # outro comentário, mesmo post
    assert meta.leituras == 1 and len(meta.privadas) == 2


# ------------------------------------------------------------------ uma mensagem, sem repetição
def test_comentario_repetido_nao_gera_segunda_mensagem(lojas_ig, meta):
    c = _comentario()
    assert _tratar(1, c) == "respondido"
    assert _tratar(1, c) == "repetido"
    assert len(meta.privadas) == 1


def test_a_propria_loja_comentando_e_ignorada(lojas_ig, meta):
    assert _tratar(1, _comentario("comentario_da_propria_loja.json")) == "propria_loja"
    assert meta.envios == []


def test_fora_do_prazo_de_7_dias_nao_envia(lojas_ig, meta):
    c = _comentario()
    depois = datetime.fromtimestamp(c.hora + 8 * 86400, tz=timezone.utc)
    assert asyncio.run(ci.tratar_comentario(1, c, agora=depois)) == "fora_do_prazo"
    assert meta.envios == []


def test_loja_em_teste_nao_responde_comentario_de_quem_nao_e_de_teste(meta, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_TOKEN_T", "token-falso-t")
    loja = criar_loja("Loja em teste Comentários")
    canais.cadastrar_canal(loja, "instagram", "17841400000000077", "INSTAGRAM_TOKEN_T")
    lojas.salvar_config(loja, {"modulos.instagram": True, "instagram.responder_comentarios": True,
                               "instagram.palavras_comentario": ["valor", "tem", "troca", "quero"]}, "teste")
    c = _comentario(**{CONTA_A: "17841400000000077"})
    assert _tratar(loja, c) == "loja_em_teste" and meta.envios == []


def test_duas_lojas_cada_uma_com_seu_post_e_seu_catalogo(lojas_ig, meta):
    loja_b = lojas_ig[1]
    _carro(1, "Civic")
    _carro(loja_b, "Corolla")
    meta.legenda = "Honda Civic 2019 na loja!"
    _tratar(1, _comentario())
    _tratar(loja_b, _comentario(**{CONTA_A: CONTA_B}))         # mesmo comment_id, outra loja
    assert "Honda Civic 2019" in meta.privadas[0]
    assert meta.privadas[1] == "Oi! Vi seu comentário, te chamei por aqui para te ajudar."   # a B não tem Civic
    assert {l["loja_id"] for l in _ler("SELECT loja_id FROM instagram_comentarios")} == {1, loja_b}
    assert CONTA_A in meta.envios[0]["url"] and CONTA_B in meta.envios[1]["url"]


# ------------------------------------------------------------------ resposta pública
def test_resposta_publica_curta_uma_vez_e_desligada_por_padrao(lojas_ig, meta):
    _carro(1, "Civic")
    _tratar(1, _comentario())
    assert meta.publicas == []
    lojas.salvar_config(1, {"instagram.resposta_publica": True}, "teste")
    c = _comentario(**{"18000000000000001": "18000000000000021"})
    _tratar(1, c)
    _tratar(1, c)
    assert meta.publicas == ["Te chamei no direct."]
    lojas.salvar_config(1, {"instagram.texto_resposta_publica": "Fica por R$ 98 mil, te chamei!"}, "teste")
    _tratar(1, _comentario(**{"18000000000000001": "18000000000000022"}))
    assert meta.publicas[-1] == "Te chamei no direct."           # nunca com preço


# ------------------------------------------------------------------ anúncio
def test_comentario_em_anuncio_segue_o_mesmo_caminho_e_a_origem_e_anuncio(lojas_ig, meta):
    _carro(1, "Civic")
    c = _comentario("comentario_anuncio.json")
    assert c.origem == "anuncio" and c.ad_id == "23800000000000001"
    assert _tratar(1, c) == "respondido"
    assert _ler("SELECT origem, origem_detalhe FROM leads WHERE lead_id = 'ig:9100000000000006'") == \
        [{"origem": "anuncio", "origem_detalhe": "23800000000000001"}]
    assert _ler("SELECT origem FROM instagram_comentarios") == [{"origem": "anuncio"}]


def test_origem_comentario_em_post_comum(lojas_ig, meta):
    _tratar(1, _comentario())
    assert _ler("SELECT origem FROM leads WHERE lead_id = 'ig:9100000000000004'") == [{"origem": "comentario"}]


# ------------------------------------------------------------------ a pessoa responde: o Léo sabe do carro
def test_a_pessoa_responde_e_o_leo_continua_sabendo_do_carro(lojas_ig, meta, monkeypatch):
    from app.core import agent
    _carro(1, "Civic")
    _tratar(1, _comentario())
    vistos = []

    class LLM:
        def invoke(self, mensagens):
            vistos.append(" ".join(str(getattr(m, "content", m)) for m in mensagens))
            return AIMessage(content="Ótimo! O Civic é automático. Quer marcar uma visita?")
    monkeypatch.setattr(agent, "llm", LLM())
    asyncio.run(wi.processar_texto(1, "ig:9100000000000004", "quero sim"))
    assert "Honda Civic 2019" in vistos[0]                         # a mensagem privada está no contexto
    assert meta.privadas[-1].startswith("Ótimo! O Civic")


# ------------------------------------------------------------------ pela porta
def test_porta_agenda_o_comentario_da_loja_certa(monkeypatch, lojas_ig):
    import hashlib
    import hmac
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "s")
    chamados = []

    async def espiao(loja_id, c):
        chamados.append((loja_id, c.comment_id))
    monkeypatch.setattr(ci, "tratar_comentario", espiao)
    from app.api.webhook import app
    corpo = json.dumps(_payload("comentario_post.json", **{CONTA_A: CONTA_B})).encode()
    r = TestClient(app).post("/webhook/instagram", content=corpo,
                             headers={"X-Hub-Signature-256": "sha256=" + hmac.new(b"s", corpo, hashlib.sha256).hexdigest()})
    assert r.status_code == 200 and chamados == [(lojas_ig[1], "18000000000000001")]


def test_palavras_da_loja_filtram_o_comentario(lojas_ig, meta):
    lojas.salvar_config(1, {"instagram.palavras_comentario": ["preço"]}, "teste")
    assert _tratar(1, _comentario()) == "sem_palavra" and meta.envios == []           # "Qual o valor?"
    lojas.salvar_config(1, {"instagram.palavras_comentario": ["valor"]}, "teste")
    assert _tratar(1, _comentario(**{"18000000000000001": "18000000000000031"})) == "respondido"

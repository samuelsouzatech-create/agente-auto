"""
C3b: o aviso de cliente esperando leva o link do vendedor (C3a).
- sem API_PUBLICA_URL, o aviso fica como antes (nenhum link gerado);
- com ela, o link abre a sessao de escopo link daquela conversa;
- cada pessoa recebe o proprio link; o reaviso anula o do aviso;
- quem ja recebeu nao ganha link de novo; envio que falhou leva link novo;
- desativar a pessoa (S4b) derruba o link;
- o token nunca fica na tabela avisos (la fica [link]).
Tudo offline: o Telegram e trocado por um falso (fixture telegram do Bloco 7B).
"""
import pytest

from app.api_painel.dependencias import COOKIE
from app.jobs import alertas
from app.usuarios import definir_ativo
from tests.test_c2a_api_acesso import EU, _novo
from tests.test_c3_link_vendedor import _abrir, _cookie, _motivo
from tests.test_etapa1_bloco7b import (GEST, TERCA_15H, VEND, _equipe, _handoff, _ler, t,  # noqa: F401
                                       telegram)

LEAD = "5581999990011"
API = "https://api.exemplo.com"
FRONT = "https://painel.exemplo.com"


@pytest.fixture
def com_link(monkeypatch):
    monkeypatch.setenv("API_PUBLICA_URL", API)
    monkeypatch.setenv("PAINEL_URL", FRONT)


def _token(msg):
    return msg.split("/v/", 1)[1].split()[0]


def _id(chat):
    return _ler("SELECT id FROM usuarios WHERE contato_telegram = ?", (chat,))[0]["id"]


def _links():
    return _ler("SELECT usuario_id, usado_em, revogado_em FROM links_vendedor ORDER BY id")


def test_sem_api_publica_url_o_aviso_fica_como_antes(monkeypatch, telegram):
    monkeypatch.delenv("API_PUBLICA_URL", raising=False)
    _equipe()
    _handoff(1, LEAD, TERCA_15H)
    alertas.verificar_handoffs(t(0, 30))
    [msg] = telegram.para(VEND)
    assert "Assumir" in msg and "/v/" not in msg
    assert _links() == []


def test_aviso_leva_link_que_abre_a_conversa(com_link, telegram):
    _equipe()
    _handoff(1, LEAD, TERCA_15H)
    alertas.verificar_handoffs(t(0, 30))
    [msg] = telegram.para(VEND)
    assert API + "/api/v1/v/" in msg and "Assumir" not in msg
    token = _token(msg)
    [guardado] = _ler("SELECT texto FROM avisos WHERE destino = ?", (VEND,))
    assert alertas.MARCA_LINK in guardado["texto"] and token not in guardado["texto"]
    assert [l["usuario_id"] for l in _links()] == [_id(VEND)]
    with _novo() as c:
        r = _abrir(c, token)
    assert r.status_code == 302 and r.headers["location"] == f"{FRONT}/conversas/{LEAD}"
    with _novo() as c:
        eu = c.get(EU, headers={"Cookie": f"{COOKIE}={_cookie(r)}"})
    assert eu.status_code == 200, eu.text
    assert eu.json()["escopo"] == "link" and eu.json()["conversa_do_link"] == LEAD


def test_cada_um_recebe_o_proprio_link_e_o_mais_novo_vale(com_link, telegram):
    _equipe()
    _handoff(1, LEAD, TERCA_15H)
    for minutos in (0, 5, 10):
        alertas.verificar_handoffs(t(minutos))
    aviso, reaviso = telegram.para(VEND)
    [gestor] = telegram.para(GEST)
    assert len({_token(aviso), _token(reaviso), _token(gestor)}) == 3
    with _novo() as c:
        assert _motivo(_abrir(c, _token(aviso))) == "revogado"
        assert _abrir(c, _token(reaviso)).headers["location"].endswith(f"/conversas/{LEAD}")
        assert _abrir(c, _token(gestor)).headers["location"].endswith(f"/conversas/{LEAD}")


def test_link_nao_e_gerado_de_novo_para_quem_ja_recebeu(com_link, telegram):
    _equipe(gestor=None)
    _handoff(1, LEAD, TERCA_15H)
    telegram.falhar = True
    alertas.verificar_handoffs(t(0, 10))
    assert len(_links()) == 1 and telegram.enviados == []
    telegram.falhar = False
    alertas.verificar_handoffs(t(0, 40))
    alertas.verificar_handoffs(t(0, 50))
    [msg] = telegram.para(VEND)
    links = _links()
    assert len(links) == 2
    assert links[0]["revogado_em"] and not links[1]["revogado_em"]
    [guardado] = _ler("SELECT texto, tentativas FROM avisos WHERE destino = ?", (VEND,))
    assert guardado["tentativas"] == 2 and _token(msg) not in guardado["texto"]


def test_desativar_a_pessoa_derruba_o_link(com_link, telegram):
    _equipe(gestor=None)
    _handoff(1, LEAD, TERCA_15H)
    alertas.verificar_handoffs(t(0, 30))
    [msg] = telegram.para(VEND)
    assert definir_ativo(_id(VEND), 1, False)
    with _novo() as c:
        assert _motivo(_abrir(c, _token(msg))) == "revogado"


def test_token_nunca_fica_na_tabela_avisos(com_link, telegram):
    _equipe()
    _handoff(1, LEAD, TERCA_15H)
    for minutos in (0, 5, 10):
        alertas.verificar_handoffs(t(minutos))
    textos = " ".join(a["texto"] for a in _ler("SELECT texto FROM avisos"))
    assert len(telegram.enviados) == 3
    for _, msg in telegram.enviados:
        assert _token(msg) not in textos
    assert textos.count(alertas.MARCA_LINK) == 3

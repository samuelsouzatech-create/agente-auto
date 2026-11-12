"""
C2b (Plano Mestre, bloco C2): a luz "Léo atendendo" (GET /saude) e a tela Atender (GET /atender).
- a luz nunca fica verde com loja em teste, envios pausados ou sem canal ativo;
- respostas iguais aos dados falsos de docs/api/mocks/ e ao openapi.yaml;
- Atender: esperando (mais antigo primeiro), com vendedor, conversas de hoje no fuso
  da loja, espera contada no expediente, janela de 24 h, atualizar_em_segundos;
- quem pode: dono, gestor e vendedor; vendedor do link 403; sem login 401;
- duas lojas: uma nunca vê a outra; loja_id no pedido é ignorado.
Tudo offline, banco temporário do conftest, relógio parado.
"""
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from banco import conectar
from app import autenticacao, sessoes
from app.api_painel import atender as m_atender
from app.api_painel import saude as m_saude
from app.api_painel.dependencias import COOKIE
from app.api_painel.main import PREFIXO, criar_app
from app.lojas import criar_loja

RAIZ = Path(__file__).resolve().parent.parent
API = RAIZ / "docs" / "api"
DOC = yaml.safe_load((API / "openapi.yaml").read_text(encoding="utf-8"))
SENHA = "Carro-Azul-2026"
AGORA = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)      # terça, 12:00 em Recife
SAUDE, ATENDER = PREFIXO + "/saude", PREFIXO + "/atender"
LEAD1, LEAD2, LEAD3, LEAD_OUTRA = "5581999990001", "5581999990002", "5581999990003", "5581999990009"
_contador = itertools.count(1)


# ------------------------------------------------------------ ajudantes

@pytest.fixture(autouse=True)
def relogio_parado(monkeypatch):
    monkeypatch.setattr(m_atender, "agora_utc", lambda: AGORA)
    monkeypatch.setattr(m_saude, "agora_utc", lambda: AGORA)


@pytest.fixture
def cliente():
    with TestClient(criar_app(), base_url="https://testserver") as c:
        yield c


def _executar(sql, parametros=()):
    conexao = conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


def _mock(nome):
    return json.loads((API / "mocks" / nome).read_text(encoding="utf-8"))


def _entrar(loja=1, papel="gestor"):
    n = next(_contador)
    papel_pessoa = "vendedor" if papel == sessoes.PAPEL_LINK else papel
    uid = autenticacao.criar_usuario_com_login(loja, f"Pessoa {n}", papel_pessoa,
                                               f"pessoa{n}@loja.com", SENHA)
    if papel == sessoes.PAPEL_LINK:
        token = sessoes.criar_sessao(uid, loja, papel, escopo="link", lead_id=LEAD1)
    else:
        token = sessoes.criar_sessao(uid, loja, papel)
    return {"Cookie": f"{COOKIE}={token}"}


def _no_ar(loja=1):
    _executar("INSERT INTO estado_lojas (loja_id, estado, no_ar_em, alterado_por, atualizado_em) "
              "VALUES (?, 'no_ar', '2026-11-01 12:00:00', 'Teste', '2026-11-01 12:00:00') "
              "ON CONFLICT (loja_id) DO UPDATE SET estado = 'no_ar'", (loja,))


def _em_teste(loja=1):
    _executar("DELETE FROM estado_lojas WHERE loja_id = ?", (loja,))


def _so_canal(loja=1, tipo="whatsapp", ativo=1):
    _executar("DELETE FROM canais WHERE loja_id = ?", (loja,))
    if tipo:
        _executar("INSERT INTO canais (loja_id, tipo, id_externo, token_ref, ativo) "
                  "VALUES (?, ?, ?, '', ?)", (loja, tipo, f"{tipo}-{loja}", ativo))


def _pausa(loja, por, motivo, quando):
    _executar("INSERT INTO pausas_envio (loja_id, acao, usuario, papel, motivo, criado_em) "
              "VALUES (?, 'pausar', ?, 'cliente', ?, ?)", (loja, por, motivo, quando))


def _msg(loja, lead, direcao, texto, quando, canal="whatsapp"):
    _executar("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo, autor, "
              "criado_em) VALUES (?, ?, ?, ?, 'texto', ?, NULL, ?)",
              (lead, loja, canal, direcao, texto, quando))


def _handoff(loja, lead, estado, quando, vendedor=None, motivo=""):
    _executar("INSERT INTO handoffs (loja_id, lead_id, motivo, resumo, estado, vendedor, "
              "criado_em, assumido_em) VALUES (?, ?, ?, '', ?, ?, ?, ?)",
              (loja, lead, motivo, estado, vendedor, quando,
               quando if estado == "humano_assumiu" else None))


def _esquema(rota, metodo, status):
    resp = DOC["paths"][rota][metodo]["responses"][status]
    while "$ref" in resp:
        resp = DOC["components"]["responses"][resp["$ref"].split("/")[-1]]
    return resp.get("content", {}).get("application/json", {}).get("schema")


def _validar(rota, resposta):
    """A resposta real obedece ao openapi.yaml (mesma ideia do conferir_mocks.py)."""
    status = str(resposta.status_code)
    assert status in DOC["paths"][rota]["get"]["responses"], f"GET {rota} não prevê {status}"
    esquema = _esquema(rota, "get", status)
    raiz = {**esquema, "components": DOC["components"]}
    problemas = [f"{'/'.join(map(str, e.path)) or '$'}: {e.message}"
                 for e in Draft202012Validator(raiz).iter_errors(resposta.json())]
    assert not problemas, f"GET {rota} {status} fora do contrato: {problemas}"


# ------------------------------------------------------------ luz

def test_saude_verde_igual_ao_dado_falso(cliente):
    _no_ar()
    _so_canal()
    r = cliente.get(SAUDE, headers=_entrar())
    assert r.status_code == 200, r.text
    _validar("/saude", r)
    assert r.json() == _mock("saude__verde.json")


def test_saude_canal_desativado_e_vermelha(cliente):
    _no_ar()
    _so_canal(ativo=0)
    r = cliente.get(SAUDE, headers=_entrar())
    _validar("/saude", r)
    assert r.json() == _mock("saude__sem_canal.json")


def test_saude_sem_nenhum_canal_e_vermelha_mesmo_em_teste(cliente):
    _em_teste()
    _so_canal(tipo=None)
    r = cliente.get(SAUDE, headers=_entrar())
    _validar("/saude", r)
    corpo = r.json()
    assert (corpo["luz"], corpo["canais"], corpo["faixa"]["tipo"]) == ("vermelha", [], "azul")


def test_saude_em_teste_igual_ao_dado_falso(cliente):
    _em_teste()
    _so_canal()
    r = cliente.get(SAUDE, headers=_entrar())
    _validar("/saude", r)
    assert r.json() == _mock("saude__em_teste.json")


def test_saude_pausado_nunca_verde(cliente):
    _no_ar()
    _so_canal()
    _pausa(1, "Camila Rocha", "Feriado prolongado", "2026-11-10 12:05:00")   # 09:05 em Recife
    r = cliente.get(SAUDE, headers=_entrar())
    _validar("/saude", r)
    corpo, m = r.json(), _mock("saude__pausado.json")
    for campo in ("luz", "titulo", "detalhe", "estado", "canais"):
        assert corpo[campo] == m[campo], campo
    assert corpo["pausa"] == {"ativa": True, "por": "Camila Rocha", "motivo": "Feriado prolongado",
                              "desde": {"iso": "2026-11-10T09:05:00-03:00", "texto": "hoje 09:05"}}
    assert corpo["faixa"] == {"tipo": "laranja",
                              "texto": "Envios automáticos pausados por Camila Rocha desde hoje 09:05."}


# ------------------------------------------------------------ quem pode

@pytest.mark.parametrize("rota", ["/saude", "/atender"])
@pytest.mark.parametrize("papel, status", [("dono", 200), ("gestor", 200), ("vendedor", 200),
                                           ("vendedor_link", 403)])
def test_quem_pode_ver(cliente, rota, papel, status):
    r = cliente.get(PREFIXO + rota, headers=_entrar(papel=papel))
    assert r.status_code == status, r.text
    _validar(rota, r)
    if status == 403:
        assert r.json() == _mock("erro__sem_permissao.json")


@pytest.mark.parametrize("rota", ["/saude", "/atender"])
def test_sem_login_e_401(cliente, rota):
    r = cliente.get(PREFIXO + rota)
    assert r.status_code == 401
    _validar(rota, r)


# ------------------------------------------------------------ Atender

def test_atender_vazio_igual_ao_dado_falso(cliente):
    r = cliente.get(ATENDER, headers=_entrar())
    assert r.status_code == 200, r.text
    _validar("/atender", r)
    assert r.json() == _mock("atender__vazio.json")


def test_atender_com_dados(cliente):
    _msg(1, LEAD1, "cliente", "Oi, o HB20 ainda está disponível?", "2026-11-10 14:30:00")
    _msg(1, LEAD1, "leo", "Está sim!", "2026-11-10 14:31:00")
    _handoff(1, LEAD1, "aguardando_humano", "2026-11-10 14:39:00", motivo="Quer ver o carro")
    _msg(1, LEAD2, "cliente", "Faz por quanto?", "2026-11-08 12:00:00")
    _handoff(1, LEAD2, "humano_assumiu", "2026-11-08 12:05:00", vendedor="Ricardo Alves",
             motivo="Negociando valor")
    _msg(1, LEAD3, "cliente", "Tem Onix?", "2026-11-10 02:00:00")          # 23:00 de ontem em Recife
    _handoff(1, LEAD3, "aguardando_humano", "2026-11-10 14:52:00", motivo="Pediu um vendedor")

    r = cliente.get(ATENDER, headers=_entrar(papel="vendedor"))
    assert r.status_code == 200, r.text
    _validar("/atender", r)
    corpo, m = r.json(), _mock("atender__com_dados.json")
    assert corpo["atualizar_em_segundos"] == m["atualizar_em_segundos"] == 20

    esperando = corpo["esperando"]
    assert [c["lead"] for c in esperando] == [LEAD1, LEAD3]          # mais antigo primeiro
    j = esperando[0]
    assert sorted(j) == sorted(m["esperando"][0]), "campos do cartão diferentes do dado falso"
    assert j["estado_do_chamado"] == "aguardando" and j["assumido_por"] is None
    assert j["espera"] == {"minutos": 21, "texto": "esperando há 21 min"}
    assert j["motivo"] == "Quer ver o carro" and j["origem"] == "WhatsApp"
    # formato do sistema: (81) 9 9999-0001 (app/telefone.py); o dado falso usa (81) 99999-0001
    assert j["telefone"].endswith("9999-0001") and j["nome"] == j["telefone"]
    assert j["ultima_mensagem"] == {"iso": "2026-11-10T11:31:00-03:00", "texto": "hoje 11:31"}
    assert j["janela"] == {"aberta": True, "explicacao": None,
                           "fecha_em": {"iso": "2026-11-11T11:30:00-03:00", "texto": "amanhã 11:30"}}
    assert esperando[1]["espera"]["minutos"] == 8
    assert esperando[1]["ultima_mensagem"]["texto"] == "ontem 23:00"

    [c] = corpo["com_vendedor"]
    assert (c["lead"], c["estado_do_chamado"], c["assumido_por"], c["espera"]) == (
        LEAD2, "humano_assumiu", "Ricardo Alves", None)
    assert c["janela"] == {"aberta": False, "fecha_em": None,
                           "explicacao": "Faz mais de 24 h que o cliente não escreve."}

    # "hoje" no fuso da loja: a mensagem das 23:00 de ontem (Recife) não entra
    assert [x["lead"] for x in corpo["conversas_de_hoje"]] == [LEAD1]


def test_telegram_sem_telefone_e_sem_janela(cliente):
    _msg(1, "123456789", "cliente", "Oi", "2026-11-10 14:00:00", canal="telegram")
    _handoff(1, "123456789", "aguardando_humano", "2026-11-10 14:10:00")
    r = cliente.get(ATENDER, headers=_entrar())
    _validar("/atender", r)
    [c] = r.json()["esperando"]
    assert "telefone" not in c and c["origem"] == "Telegram"
    assert c["janela"] == {"aberta": True, "fecha_em": None, "explicacao": None}


def test_duas_lojas_e_loja_id_ignorado(cliente):
    loja2 = criar_loja("Garagem Dois")
    _msg(1, LEAD1, "cliente", "Oi", "2026-11-10 14:30:00")
    _handoff(1, LEAD1, "aguardando_humano", "2026-11-10 14:39:00")
    _msg(loja2, LEAD_OUTRA, "cliente", "Oi", "2026-11-10 14:30:00")
    _handoff(loja2, LEAD_OUTRA, "aguardando_humano", "2026-11-10 14:40:00")

    um = cliente.get(f"{ATENDER}?loja_id={loja2}", headers=_entrar(1)).json()
    dois = cliente.get(ATENDER, headers=_entrar(loja2)).json()
    assert [c["lead"] for c in um["esperando"]] == [LEAD1]
    assert [c["lead"] for c in dois["esperando"]] == [LEAD_OUTRA]
    assert "loja_id" not in json.dumps(um)

    _no_ar(1)
    _so_canal(1)
    _so_canal(loja2, tipo=None)
    assert cliente.get(f"{SAUDE}?loja_id={loja2}", headers=_entrar(1)).json()["luz"] == "verde"
    assert cliente.get(SAUDE, headers=_entrar(loja2)).json()["luz"] == "vermelha"

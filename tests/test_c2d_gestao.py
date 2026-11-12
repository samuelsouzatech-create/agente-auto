"""C2d: acompanhamento, pausa, bloqueios, estoque e reativar contato (offline)."""
import pytest
from fastapi.testclient import TestClient

from app.api_painel.main import PREFIXO, criar_app
from tests.test_c2c_conversas import _entrar, _validar   # mesmos ajudantes do C2c

P = PREFIXO
CARRO = {"marca": "Hyundai", "modelo": "HB20 Comfort", "ano": 2020, "km": 48000,
         "cor": "Prata", "cambio": "Manual", "preco": 62900, "status": "disponivel",
         "fotos": ["https://fotos.exemplo.example/hb20-1.jpg"]}


@pytest.fixture
def cliente():
    with TestClient(criar_app(), base_url="https://testserver") as c:
        yield c


@pytest.fixture
def dono():
    from app.lojas import salvar_config
    salvar_config(1, {"modulos.remarketing": True, "modulos.estoque": True}, "teste")
    return _entrar(papel="dono", nome="Samuel Dono")


@pytest.fixture
def vendedor():
    return _entrar(papel="vendedor", nome="Ricardo Alves")


def _acompanhamento_ligado(cliente, h):
    if cliente.get(P + "/acompanhamento", headers=h).status_code == 403:
        pytest.skip("módulo desligado nesta loja de teste")


def test_acompanhamento_obedece_contrato(cliente, dono):
    r = cliente.get(P + "/acompanhamento", headers=dono)
    assert r.status_code in (200, 403), r.text
    _validar("/acompanhamento", "get", r)


def test_vendedor_recebe_403(cliente, vendedor):
    for rota in ("/acompanhamento", "/estoque"):
        assert cliente.get(P + rota, headers=vendedor).status_code == 403, rota


def test_pausar_duas_vezes_e_retomar(cliente, dono):
    _acompanhamento_ligado(cliente, dono)
    a = cliente.post(P + "/acompanhamento/pausar", json={"motivo": "Feriado"}, headers=dono)
    b = cliente.post(P + "/acompanhamento/pausar", json={"motivo": "Feriado"}, headers=dono)
    assert a.status_code == b.status_code == 200, b.text
    assert b.json()["ativa"] is True
    r = cliente.post(P + "/acompanhamento/retomar", headers=dono)
    assert r.status_code == 200 and r.json()["ativa"] is False


def test_escrita_sem_csrf_recusada(cliente, dono):
    r = cliente.post(P + "/estoque", json=CARRO, headers={"Cookie": dono["Cookie"]})
    assert r.status_code == 403 and r.json()["codigo"] == "csrf_invalido"


def test_estoque_cadastrar_editar_e_conflito(cliente, dono):
    r = cliente.post(P + "/estoque", json=CARRO, headers=dono)
    assert r.status_code == 201, r.text
    _validar("/estoque", "post", r)
    carro = r.json()
    esperado = {**CARRO}
    novo = {**CARRO, "preco": 61900}
    r = cliente.put(P + f"/estoque/{carro['id']}", json={"dados": novo, "esperado": esperado},
                    headers=dono)
    assert r.status_code == 200, r.text
    assert r.json()["preco"]["valor"] == 61900
    r = cliente.put(P + f"/estoque/{carro['id']}", json={"dados": CARRO, "esperado": esperado},
                    headers=dono)
    assert r.status_code == 409, r.text


def test_vendido_nunca_pela_api(cliente, dono):
    r = cliente.post(P + "/estoque", json={**CARRO, "status": "vendido"}, headers=dono)
    assert r.status_code == 422 and "Registrar venda" in r.json()["mensagem"]


def test_bloqueio_de_outra_loja_404(cliente, dono):
    _acompanhamento_ligado(cliente, dono)
    assert cliente.delete(P + "/bloqueios/999999", headers=dono).status_code == 404


def test_bloqueio_tipo_invalido_422(cliente, dono):
    _acompanhamento_ligado(cliente, dono)
    r = cliente.post(P + "/bloqueios", json={"lead": "5581999990001", "tipo": "xyz"}, headers=dono)
    assert r.status_code == 422, r.text
    assert r.json()["mensagem"] == "Escolha o que não enviar."

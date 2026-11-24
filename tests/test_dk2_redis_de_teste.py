"""
DK2 (Maratona Docker): a suíte normal nunca grava na gaveta de uso do Redis.

Desde o DK1 o Redis do compose fica sempre ligado. A suíte gravava nele e uma rodada sujava a
seguinte ("mensagem já vista" em test_m3_n3_servidor). Agora o conftest aponta os testes para a
gaveta 15 do mesmo Redis (ou REDIS_URL_TESTE), esvaziada no começo da rodada. AR (Maratona 4):
o teste de carga (-m carga) usa a gaveta 14 (ou REDIS_URL_CARGA) e recusa a gaveta de uso (0).
"""
from __future__ import annotations

import os

import pytest

from tests import conftest


def test_suite_usa_a_gaveta_de_teste():
    import app.redis_cliente as rc
    assert rc.REDIS_URL == os.environ["REDIS_URL"]
    assert rc.REDIS_URL.endswith(f"/{conftest.REDIS_BANCO_DE_TESTE}") or os.environ.get("REDIS_URL_TESTE")


def test_endereco_de_teste_troca_so_a_gaveta():
    assert conftest.redis_de_teste("redis://:senha@127.0.0.1:6379/0") == "redis://:senha@127.0.0.1:6379/15"
    assert conftest.redis_de_teste("redis://localhost:6379") == "redis://localhost:6379/15"
    assert conftest.redis_de_teste("") == "redis://localhost:6379/15"


@pytest.fixture(autouse=True)
def _sem_apagar_nada(monkeypatch):
    """Os testes daqui nunca falam com um Redis: o "esvaziar" do conftest vira nada."""
    import redis

    class _Falso:
        def flushdb(self):
            return True
    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda cls, *a, **k: _Falso()))


class _Config:
    def __init__(self, expressao):
        self._e = expressao

    def getoption(self, nome):
        return self._e


def test_nenhuma_rodada_usa_a_gaveta_de_uso(monkeypatch):
    """AR (Maratona 4): antes, o teste de carga usava a gaveta de uso (0). Agora usa a 14."""
    for expressao, gaveta in (("not api and not carga", "15"), ("", "15"), ("api", "15"),
                              ("carga", "14")):
        monkeypatch.setenv("REDIS_URL", "redis://:x@127.0.0.1:1/0")    # porta sem Redis: nada é apagado
        monkeypatch.delenv("REDIS_URL_TESTE", raising=False)
        monkeypatch.delenv("REDIS_URL_CARGA", raising=False)
        conftest.pytest_configure(_Config(expressao))
        assert os.environ["REDIS_URL"] == f"redis://:x@127.0.0.1:1/{gaveta}", expressao


def test_recusa_testar_na_gaveta_de_uso(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://:x@127.0.0.1:1/15")
    monkeypatch.setenv("REDIS_URL_TESTE", "redis://:x@127.0.0.1:1/15")
    with pytest.raises(pytest.exit.Exception):
        conftest.pytest_configure(_Config("not api and not carga"))


def test_carga_usa_a_gaveta_14_e_esvazia_no_comeco(monkeypatch):
    apagadas = []
    import redis

    class _Falso:
        def __init__(self, url):
            self.url = url

        def flushdb(self):
            apagadas.append(self.url)
            return True
    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda cls, url, **k: _Falso(url)))
    monkeypatch.setenv("REDIS_URL", "redis://:x@127.0.0.1:1/0")
    monkeypatch.delenv("REDIS_URL_CARGA", raising=False)
    conftest.pytest_configure(_Config("carga"))
    assert os.environ["REDIS_URL"] == "redis://:x@127.0.0.1:1/14"
    assert apagadas == ["redis://:x@127.0.0.1:1/14"]          # a gaveta 0 nunca é esvaziada


@pytest.mark.parametrize("carga", ["redis://:x@127.0.0.1:1/0", "redis://:x@127.0.0.1:1",
                                   "redis://:x@outro:1/0"])
def test_carga_recusa_a_gaveta_0(monkeypatch, carga):
    monkeypatch.setenv("REDIS_URL", "redis://:x@127.0.0.1:1/0")
    monkeypatch.setenv("REDIS_URL_CARGA", carga)
    with pytest.raises(pytest.exit.Exception):
        conftest.pytest_configure(_Config("carga"))


def test_endereco_de_carga_troca_so_a_gaveta():
    assert conftest.redis_de_carga("redis://:senha@127.0.0.1:6379/0") == "redis://:senha@127.0.0.1:6379/14"
    assert conftest.redis_de_carga("") == "redis://localhost:6379/14"

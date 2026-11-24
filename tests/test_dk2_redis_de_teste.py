"""
DK2 (Maratona Docker): a suíte normal nunca grava na gaveta de uso do Redis.

Desde o DK1 o Redis do compose fica sempre ligado. A suíte gravava nele e uma rodada sujava a
seguinte ("mensagem já vista" em test_m3_n3_servidor). Agora o conftest aponta os testes para a
gaveta 15 do mesmo Redis (ou REDIS_URL_TESTE), esvaziada no começo da rodada; só o teste de
carga (-m carga) usa o REDIS_URL de uso.
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


def test_so_o_teste_de_carga_usa_a_gaveta_de_uso(monkeypatch):
    for expressao, usa_o_real in (("not api and not carga", False), ("", False), ("api", False),
                                  ("carga", True)):
        monkeypatch.setenv("REDIS_URL", "redis://:x@127.0.0.1:1/0")    # porta sem Redis: nada é apagado
        monkeypatch.delenv("REDIS_URL_TESTE", raising=False)
        conftest.pytest_configure(_Config(expressao))
        assert (os.environ["REDIS_URL"] == "redis://:x@127.0.0.1:1/0") is usa_o_real, expressao


def test_recusa_testar_na_gaveta_de_uso(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://:x@127.0.0.1:1/15")
    monkeypatch.setenv("REDIS_URL_TESTE", "redis://:x@127.0.0.1:1/15")
    with pytest.raises(pytest.exit.Exception):
        conftest.pytest_configure(_Config("not api and not carga"))

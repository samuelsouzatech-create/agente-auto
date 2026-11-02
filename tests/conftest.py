"""
Configuração compartilhada dos testes (pytest).

A fixture 'banco_temporario' é autouse: antes de CADA teste, aponta o banco
para um arquivo .db temporário, cria as tabelas e aplica as migrações.
Também limpa o cache de configuração das lojas e manda o log estruturado
para uma pasta temporária (os testes nunca sujam logs/ de verdade).

A fixture 'ator_de_teste' (P6) também é autouse: todo teste roda com um
ator definido ("Teste", operador, painel). Os testes de "sem ator falha"
tiram o ator de propósito com app.ator.sem_ator().
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from banco import criar_tabelas
from app import ator, lojas, logs


@pytest.fixture(autouse=True)
def banco_temporario(monkeypatch, tmp_path):
    """Cada teste roda contra um banco limpo e isolado, com todas as tabelas."""
    fd, caminho = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(banco, "CAMINHO_BANCO", caminho)
    monkeypatch.setattr(logs, "PASTA_LOGS", str(tmp_path / "logs"))
    lojas.limpar_cache()
    criar_tabelas()
    yield caminho
    lojas.limpar_cache()
    if os.path.exists(caminho):
        os.remove(caminho)


@pytest.fixture(autouse=True)
def ator_de_teste():
    """Todo teste tem um autor; assim os testes antigos não precisam mudar."""
    with ator.como("Teste", "operador", "painel"):
        yield

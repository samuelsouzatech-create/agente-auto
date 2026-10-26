"""
Configuração compartilhada dos testes (pytest).

A fixture 'banco_temporario' é autouse: antes de CADA teste, aponta o banco
para um arquivo .db temporário, cria as tabelas e aplica as migrações.
Também limpa o cache de configuração das lojas, para um teste não vazar
no outro.
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from banco import criar_tabelas
from app import lojas


@pytest.fixture(autouse=True)
def banco_temporario(monkeypatch):
    """Cada teste roda contra um banco limpo e isolado, com todas as tabelas."""
    fd, caminho = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(banco, "CAMINHO_BANCO", caminho)
    lojas.limpar_cache()
    criar_tabelas()
    yield caminho
    lojas.limpar_cache()
    if os.path.exists(caminho):
        os.remove(caminho)

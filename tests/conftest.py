"""
Configuração compartilhada dos testes (pytest).

A fixture 'banco_temporario' é autouse: antes de CADA teste, aponta o banco
para um arquivo .db temporário, cria as tabelas e aplica as migrações.
Também limpa o cache de configuração das lojas e manda o log estruturado
para uma pasta temporária (os testes nunca sujam logs/ de verdade).
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from banco import criar_tabelas
from app import lojas, logs


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

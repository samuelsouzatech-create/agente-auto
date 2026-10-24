"""
Configuração compartilhada dos testes (pytest).

A fixture 'banco_temporario' é autouse: antes de CADA teste, aponta o banco
para um arquivo .db temporário e cria todas as tabelas. Assim nenhum teste
toca o loja.db real, e código que grava mensagens / consulta handoff
(Fase 3) encontra as tabelas que precisa.
"""
import os
import sys
import tempfile

import pytest

# Garante que o Python encontre os módulos da raiz do projeto.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from banco import criar_tabelas


@pytest.fixture(autouse=True)
def banco_temporario(monkeypatch):
    """Cada teste roda contra um banco limpo e isolado, com todas as tabelas."""
    fd, caminho = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(banco, "CAMINHO_BANCO", caminho)
    criar_tabelas()
    yield caminho
    if os.path.exists(caminho):
        os.remove(caminho)

import os
import sys
import tempfile
import pytest

# Garante que o Python encontre os módulos da raiz do projeto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from banco import criar_tabelas, popular_estoque_exemplo
from tools import formatar_brl, simular_financiamento, consultar_estoque


@pytest.fixture
def banco_com_estoque(monkeypatch):
    """Cria um banco SQLite temporário, isolado, já populado com os
    7 carros de exemplo (incluindo o Civic 2017 vendido). Assim os testes
    de estoque não dependem do loja.db real nem da ordem de execução."""
    fd, caminho = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(banco, "CAMINHO_BANCO", caminho)
    criar_tabelas()
    popular_estoque_exemplo()
    yield caminho
    if os.path.exists(caminho):
        os.remove(caminho)


# --- Testes de formatar_brl (função pura, não precisam de banco) ---

def test_formatar_brl_milhar():
    # 98000.0 deve virar "R$ 98.000,00" (ponto no milhar, vírgula no decimal)
    assert formatar_brl(98000.0) == "R$ 98.000,00"

def test_formatar_brl_valor_quebrado():
    assert formatar_brl(1234.5) == "R$ 1.234,50"

def test_formatar_brl_valor_pequeno():
    assert formatar_brl(50.0) == "R$ 50,00"


# --- Testes de simular_financiamento (função pura) ---
# Obs: a tool tem o decorador @tool, então chamamos via .invoke({...})

def test_financiamento_parcelas_zero_nao_quebra():
    # parcelas=0 não pode dar divisão por zero; deve retornar aviso
    resultado = simular_financiamento.invoke(
        {"valor_carro": 50000, "entrada": 10000, "parcelas": 0}
    )
    assert "válido" in resultado.lower() or "parcela" in resultado.lower()

def test_financiamento_entrada_cobre_total():
    resultado = simular_financiamento.invoke(
        {"valor_carro": 50000, "entrada": 50000, "parcelas": 48}
    )
    assert "não é necessário financiamento" in resultado.lower()

def test_financiamento_calculo_normal():
    resultado = simular_financiamento.invoke(
        {"valor_carro": 50000, "entrada": 10000, "parcelas": 48}
    )
    # Deve mencionar o valor financiado e as parcelas
    assert "R$" in resultado
    assert "48x" in resultado


# --- Testes da query de estoque (agora com banco temporário populado) ---

def test_estoque_nunca_retorna_vendido(banco_com_estoque):
    # O Civic 2017 preto está marcado como "vendido" no banco de exemplo
    resultado = consultar_estoque.invoke({"modelo": "Civic"})
    # Deve achar o Civic 2019 (disponível), mas nunca o 2017 (vendido)
    assert "2019" in resultado
    assert "2017" not in resultado

def test_estoque_ferrari_nao_existe(banco_com_estoque):
    resultado = consultar_estoque.invoke({"marca": "Ferrari"})
    assert "nenhum carro" in resultado.lower()

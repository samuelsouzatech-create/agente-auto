import os
import sys

# Garante que o Python encontre os módulos da raiz do projeto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools import formatar_brl, simular_financiamento, consultar_estoque


# --- Testes de formatar_brl ---

def test_formatar_brl_milhar():
    # 98000.0 deve virar "R$ 98.000,00" (ponto no milhar, vírgula no decimal)
    assert formatar_brl(98000.0) == "R$ 98.000,00"

def test_formatar_brl_valor_quebrado():
    assert formatar_brl(1234.5) == "R$ 1.234,50"

def test_formatar_brl_valor_pequeno():
    assert formatar_brl(50.0) == "R$ 50,00"


# --- Testes de simular_financiamento ---
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
    # Deve mencionar o valor financiado (40 mil) e as parcelas
    assert "R$" in resultado
    assert "48x" in resultado


# --- Teste da query de estoque (nunca retornar carro vendido) ---
# Depende do loja.db existir com os dados de exemplo (python banco.py)

def test_estoque_nunca_retorna_vendido():
    # O Civic 2017 preto está marcado como "vendido" no banco de exemplo
    resultado = consultar_estoque.invoke({"modelo": "Civic"})
    # Deve achar o Civic 2019 (disponível), mas nunca o 2017 (vendido)
    assert "2019" in resultado
    assert "2017" not in resultado

def test_estoque_ferrari_nao_existe():
    resultado = consultar_estoque.invoke({"marca": "Ferrari"})
    assert "nenhum carro" in resultado.lower()

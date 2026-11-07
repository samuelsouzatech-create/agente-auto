"""
E2-5c e furos confirmados pelo analista (validação do E2-5, 07/11/2026).

Testes OFFLINE (sem Gemini, sem custo) que provam furos que existem HOJE
no código. Os que mostram um furo estão marcados como "falha esperada"
(xfail strict):
  - hoje aparecem como "xfailed" e o pytest continua verde;
  - quando alguém corrigir o furo em app/, o teste passa a dar
    "XPASS(strict)", o pytest fica vermelho e avisa: é hora de tirar a marca.
Os casos de CONTROLE (sem marca) passam hoje e têm que continuar passando
depois da correção: garantem que o conserto não estraga o que já funciona.

A correção de cada furo é bloco à parte, mexe em app/ e precisa do analista.
Este arquivo não altera nada em app/.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from app.guarda_politica import numeros_do_cliente, valores_em_reais
from app.pedido_parada import pediu_para_parar
from tools import registrar_troca


def furo(numero, motivo):
    return pytest.mark.xfail(strict=True, reason=f"furo {numero}: {motivo}")


# ----------------------------------------------------------------------
# Furo 1: a guarda de preço só enxerga valor escrito com "R$"
# ----------------------------------------------------------------------

@pytest.mark.parametrize("resposta", [
    "Sai por R$ 75.000, quer ver?",  # controle: já funciona
    pytest.param("O Civic sai por uns 75 mil.", marks=furo(1, "valor sem R$ passa pela guarda")),
    pytest.param("Consigo por 75 mil reais.", marks=furo(1, "valor sem R$ passa pela guarda")),
    pytest.param("Fica 48x de 1.800 no financiamento.", marks=furo(1, "parcela sem R$ passa pela guarda")),
])
def test_guarda_enxerga_valor_na_resposta(resposta):
    assert valores_em_reais(resposta), "a guarda não viu nenhum valor nesta resposta"


# ----------------------------------------------------------------------
# Furo 2: número que o cliente falou libera preço, mesmo sendo km
# ----------------------------------------------------------------------

def test_valor_dito_pelo_cliente_continua_liberado():
    """Controle: o cliente disse a entrada, o Léo pode repetir o valor."""
    assert valores_em_reais("Com R$ 20.000 de entrada a gente simula.") & numeros_do_cliente(
        "tenho 20 mil de entrada")


@pytest.mark.parametrize("fala", [
    pytest.param("tem 90 mil km e está bem conservado", marks=furo(2, "km do cliente libera R$ inventado")),
    pytest.param("ele está com 90.000 km rodados", marks=furo(2, "km do cliente libera R$ inventado")),
])
def test_quilometragem_nao_libera_preco(fala):
    inventado = valores_em_reais("Esse sai por R$ 90.000.")
    assert not (inventado & numeros_do_cliente(fala)), "a quilometragem liberou um preço"


# ----------------------------------------------------------------------
# Furo 7: pedidos de parada que a checagem fixa não pega
# ----------------------------------------------------------------------

@pytest.mark.parametrize("fala", [
    "para de me mandar mensagem",  # controle
    "não me procure mais",         # controle
    pytest.param("me esquece", marks=furo(7, "parada não reconhecida")),
    pytest.param("sai fora", marks=furo(7, "parada não reconhecida")),
    pytest.param("bloqueia meu número", marks=furo(7, "parada não reconhecida")),
    pytest.param("n manda mais nada", marks=furo(7, "parada não reconhecida")),
])
def test_checagem_fixa_reconhece_pedido_de_parada(fala):
    assert pediu_para_parar(fala), "a checagem fixa não reconheceu o pedido de parada"


# ----------------------------------------------------------------------
# Furo 8: troca gravada com km = 0 (achado na rodada de 06/11)
# ----------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="furo 8: registrar_troca grava linha nova a cada chamada; "
                                       "a primeira, sem km, fica com km = 0")
def test_troca_nao_fica_com_km_zero():
    """O Léo registrou antes de saber a km e depois registrou de novo.
    O vendedor tem que ver só 90.000 km, sem uma linha com km = 0."""
    lead = "furo8-troca"
    registrar_troca.func("Gol", 2015, 0, "bem conservado", lead, loja_id=1)
    registrar_troca.func("Gol", 2015, 90000, "bem conservado", lead, loja_id=1)
    conexao = banco.conectar()
    try:
        linhas = [dict(l) for l in conexao.execute(
            "SELECT km FROM trocas WHERE loja_id = 1 AND lead_id = ?", (lead,)).fetchall()]
    finally:
        conexao.close()
    assert linhas, "nenhuma troca gravada"
    assert all(l["km"] == 90000 for l in linhas), f"trocas gravadas: {linhas}"

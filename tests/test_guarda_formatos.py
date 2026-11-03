"""
Bloco pequeno (antes do P5): guarda de preço entende "10k" e "1,5 mil".
Caso real do teste no Telegram (02/11/2026): cliente escreveu "10k de entrada",
o Léo simulou certo e a guarda barrou por engano (lia "10k" como R$ 10).
Tudo offline: banco temporário do conftest, sem IA.
"""
import re

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from app.guarda_politica import (
    numeros_do_cliente, resposta_tem_preco_inventado, valores_em_reais,
)
from tools import simular_financiamento

DEZ_MIL = 1_000_000          # R$ 10.000,00 em centavos


@pytest.mark.parametrize("texto, centavos", [
    ("10k", DEZ_MIL),
    ("Simula em 48x com 10K de entrada ?", DEZ_MIL),
    ("10 k", DEZ_MIL),
    ("10 mil", DEZ_MIL),
    ("10 mil reais", DEZ_MIL),
    ("10.000", DEZ_MIL),
    ("10000", DEZ_MIL),
    ("1,5 mil", 150_000),
    ("1,5k", 150_000),
])
def test_cliente_escreve_valor_em_varios_formatos(texto, centavos):
    assert centavos in numeros_do_cliente(texto)


def test_km_nao_vira_mil():
    assert 9_000_000 not in numeros_do_cliente("o meu tem 90km rodados")


@pytest.mark.parametrize("texto", ["R$ 98.000,00", "R$ 98.000", "R$98000", "R$ 98 mil", "R$ 98k"])
def test_formatos_de_reais_na_resposta(texto):
    assert valores_em_reais(texto) == {9_800_000}


def _simular():
    return simular_financiamento.invoke(
        {"loja_id": 1, "valor_carro": 42000, "entrada": 10000, "parcelas": 48}
    )


def _parcela(retorno):
    return re.search(r"48x de aproximadamente (R\$ [\d.,]+)", retorno).group(1)


def test_simulacao_mostra_valor_do_carro_e_entrada():
    retorno = _simular()
    assert "Valor do carro: R$ 42.000,00" in retorno
    assert "Entrada: R$ 10.000,00" in retorno
    assert "Valor financiado: R$ 32.000,00" in retorno


def test_caso_real_10k_nao_e_mais_barrado():
    retorno = _simular()
    mensagens = [
        HumanMessage(content="Simula em 48x com 10k de entrada ?"),
        ToolMessage(content=retorno, tool_call_id="t1"),
    ]
    resposta = (f"Com R$ 10.000,00 de entrada, a simulação para o Gol fica em "
                f"48 parcelas de aproximadamente {_parcela(retorno)}.")
    assert not resposta_tem_preco_inventado(resposta, mensagens)


def test_entrada_e_preco_valem_mesmo_sem_o_cliente_digitar():
    retorno = _simular()
    mensagens = [
        HumanMessage(content="simula em 48x pra mim"),
        ToolMessage(content=retorno, tool_call_id="t1"),
    ]
    resposta = ("O carro sai por R$ 42.000,00; com R$ 10.000,00 de entrada "
                f"fica 48x de {_parcela(retorno)}.")
    assert not resposta_tem_preco_inventado(resposta, mensagens)


def test_guarda_continua_barrando_preco_inventado():
    retorno = _simular()
    mensagens = [
        HumanMessage(content="Simula em 48x com 10k de entrada ?"),
        ToolMessage(content=retorno, tool_call_id="t1"),
    ]
    resposta = "Consigo fazer por R$ 39.900,00 à vista pra você."
    assert resposta_tem_preco_inventado(resposta, mensagens)

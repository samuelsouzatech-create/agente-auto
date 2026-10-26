from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg
from tools.utils import formatar_brl
from app.leitura_config import valor_config

TAXA_PADRAO = 0.019  # usada só se a loja não existir ou a taxa for inválida


def taxa_da_loja(loja_id: int) -> float:
    """Lê a taxa mensal da config da loja (item 1.4: nada de taxa fixa no código)."""
    from app.lojas import carregar_loja, LojaNaoEncontrada  # import tardio: evita ciclo
    try:
        loja = carregar_loja(loja_id)
    except LojaNaoEncontrada:
        return TAXA_PADRAO
    try:
        taxa = float(valor_config(loja.config, "financiamento.taxa_mensal", TAXA_PADRAO))
    except (TypeError, ValueError):
        return TAXA_PADRAO
    return taxa if taxa >= 0 else TAXA_PADRAO


def _percentual(taxa: float) -> str:
    return f"{taxa * 100:.2f}".rstrip("0").rstrip(".").replace(".", ",") + "%"


@tool
def simular_financiamento(valor_carro: float, entrada: float, parcelas: int,
                          loja_id: Annotated[int, InjectedToolArg] = 1) -> str:
    """Faz uma ESTIMATIVA de financiamento. Deixe claro ao cliente que é
    apenas uma simulação aproximada, e que as condições reais dependem de
    análise de crédito feita por um vendedor.

    Parâmetros:
    - valor_carro: preço do carro
    - entrada: valor de entrada que o cliente pode dar
    - parcelas: número de parcelas (ex: 48)
    """
    if parcelas < 1 or valor_carro <= 0:
        return "Não consigo simular: informe um valor de carro válido e ao menos 1 parcela."
    if entrada >= valor_carro:
        return "A entrada cobre o valor total. Não é necessário financiamento."

    valor_financiado = valor_carro - entrada
    taxa = taxa_da_loja(loja_id)

    if taxa == 0:
        parcela = valor_financiado / parcelas
    else:
        fator = (1 + taxa) ** parcelas          # Tabela Price
        parcela = valor_financiado * (taxa * fator) / (fator - 1)

    return (
        f"Estimativa (não é valor definitivo, depende de análise de crédito):\n"
        f"Valor financiado: {formatar_brl(valor_financiado)}\n"
        f"{parcelas}x de aproximadamente {formatar_brl(parcela)}\n"
        f"Taxa de referência usada: {_percentual(taxa)} ao mês."
    )

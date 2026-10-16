from langchain_core.tools import tool
from tools.utils import formatar_brl


@tool
def simular_financiamento(valor_carro: float, entrada: float, parcelas: int) -> str:
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
    taxa_mensal = 0.019  # 1,9% ao mês (taxa de exemplo; configurável por loja)

    # Fórmula de parcela fixa (Tabela Price)
    fator = (1 + taxa_mensal) ** parcelas
    parcela = valor_financiado * (taxa_mensal * fator) / (fator - 1)

    return (
        f"Estimativa (não é valor definitivo, depende de análise de crédito):\n"
        f"Valor financiado: {formatar_brl(valor_financiado)}\n"
        f"{parcelas}x de aproximadamente {formatar_brl(parcela)}"
    )

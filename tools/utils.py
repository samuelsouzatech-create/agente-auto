def formatar_brl(valor: float) -> str:
    """Formata um número no padrão de moeda brasileiro. Ex: 98000.0 -> 98.000,00"""
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

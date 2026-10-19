"""
Humanizador (Bloco 6, PDF seção 4.6).

Transforma a resposta única do Léo em 2-3 "bolhas" curtas, como um atendente
humano faria no WhatsApp. Aqui mora só a LÓGICA de dividir o texto; o envio
com pausa e o indicador de "digitando" são aplicados por quem envia.
"""

# Teto de bolhas por resposta (PDF: no máximo 3).
MAX_BOLHAS = 3


def dividir_em_bolhas(texto: str) -> list[str]:
    """Divide a resposta do Léo em até MAX_BOLHAS pedaços.

    Estratégia: usa os parágrafos que o próprio Léo criou (separados por
    linha em branco). Se houver mais parágrafos que o teto, os excedentes
    são juntados na última bolha, para não mandar mensagens demais.
    """
    if not texto or not texto.strip():
        return []

    # Separa por linha em branco (parágrafos) e remove espaços/pedaços vazios.
    paragrafos = [p.strip() for p in texto.split("\n\n") if p.strip()]

    # Se o Léo não usou parágrafos, vira uma bolha só.
    if not paragrafos:
        return [texto.strip()]

    # Respeita o teto: junta os excedentes na última bolha.
    if len(paragrafos) > MAX_BOLHAS:
        cabeca = paragrafos[: MAX_BOLHAS - 1]
        resto = "\n\n".join(paragrafos[MAX_BOLHAS - 1:])
        return cabeca + [resto]

    return paragrafos

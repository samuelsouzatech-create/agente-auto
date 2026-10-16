from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg
from banco import conectar


@tool
def acionar_handoff(motivo: str, resumo: str,
                   lead_id: Annotated[str, InjectedToolArg] = "") -> str:
    """Aciona a passagem da conversa para um vendedor humano (handoff).
    Use quando: o cliente pedir para falar com uma pessoa; pedir desconto
    ou negociar preço; pedir aprovação de crédito; houver reclamação;
    ou qualquer assunto que você não pode resolver sozinho.

    Parâmetros:
    - motivo: por que está passando (ex: "cliente pediu desconto")
    - resumo: resumo do lead e da conversa para o vendedor
    """
    conexao = conectar()
    cursor = conexao.cursor()
    cursor.execute("""
        INSERT INTO handoffs (lead_id, motivo, resumo, estado)
        VALUES (?, ?, ?, 'aguardando_humano')
    """, (lead_id, motivo, resumo))
    conexao.commit()
    conexao.close()
    return (
        "Handoff acionado. Avise o cliente que um vendedor vai continuar "
        "o atendimento em instantes."
    )

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

    # Upsert por lead: se já existe um handoff aguardando humano para este
    # lead, atualiza motivo/resumo em vez de criar uma linha duplicada na
    # fila do vendedor.
    if lead_id:
        cursor.execute(
            "SELECT id FROM handoffs WHERE lead_id = ? AND estado = 'aguardando_humano'",
            (lead_id,),
        )
        existente = cursor.fetchone()
        if existente:
            cursor.execute(
                "UPDATE handoffs SET motivo = ?, resumo = ? WHERE id = ?",
                (motivo, resumo, existente["id"]),
            )
            conexao.commit()
            conexao.close()
            return (
                "Handoff atualizado. Avise o cliente que um vendedor vai "
                "continuar o atendimento em instantes."
            )

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

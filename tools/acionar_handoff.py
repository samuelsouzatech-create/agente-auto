from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg
from banco import conectar

# Etapa 2, Bloco 6B: sem prometer prazo ("em instantes") quando a loja está fechada.
ORIENTACAO = ("Diga ao cliente, com naturalidade e sem anunciar transferência, que o pessoal "
              "da equipe vai falar com ele por aqui. Não prometa prazo nem use palavra de tempo "
              "(já já, já te chamam, em breve, logo, agora mesmo). Se estiver fora "
              "do horário da loja, diga que retomam no próximo horário de atendimento, com o dia "
              "e a hora do STATUS AGORA (não faça conta de horário).")


def juntar_motivos(antigo, novo) -> str:
    """L5c: "<motivo anterior> | <motivo novo>", sem repetir o que já está lá."""
    antigo, novo = str(antigo or "").strip(), str(novo or "").strip()
    if not antigo or antigo == novo:
        return novo or antigo
    if not novo or novo in antigo:
        return antigo
    return f"{antigo} | {novo}"


@tool
def acionar_handoff(motivo: str, resumo: str,
                    lead_id: Annotated[str, InjectedToolArg] = "",
                    *, loja_id: Annotated[int, InjectedToolArg]) -> str:
    """Aciona a passagem da conversa para um vendedor humano (handoff).
    Use quando: o cliente pedir para falar com uma pessoa; pedir desconto
    ou negociar preço; pedir aprovação de crédito; houver reclamação;
    ou qualquer assunto que você não pode resolver sozinho.

    Parâmetros:
    - motivo: por que está passando (ex: "cliente pediu desconto")
    - resumo: resumo do lead e da conversa para o vendedor
    """
    conexao = conectar()
    try:
        if lead_id:
            existente = conexao.execute(
                "SELECT id, motivo FROM handoffs WHERE loja_id = ? AND lead_id = ? AND estado = 'aguardando_humano'",
                (loja_id, lead_id),
            ).fetchone()
            if existente:
                # L5c: o motivo novo não apaga o anterior (ex.: o do código): "<antigo> | <novo>".
                conexao.execute(
                    "UPDATE handoffs SET motivo = ?, resumo = ? WHERE id = ?",
                    (juntar_motivos(existente["motivo"], motivo), resumo, existente["id"]),
                )
                conexao.commit()
                return "Handoff atualizado. " + ORIENTACAO

        conexao.execute(
            "INSERT INTO handoffs (loja_id, lead_id, motivo, resumo, estado) VALUES (?, ?, ?, ?, 'aguardando_humano')",
            (loja_id, lead_id, motivo, resumo),
        )
        conexao.commit()
    finally:
        conexao.close()
    return "Handoff acionado. " + ORIENTACAO

from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg
from banco import conectar
from tools.utils import formatar_brl


@tool
def detalhes_veiculo(id_veiculo: int,
                     loja_id: Annotated[int, InjectedToolArg] = 1) -> str:
    """Retorna a ficha completa de um carro específico pelo seu ID.
    Use quando o cliente demonstrar interesse em um carro específico
    que já apareceu na conversa e quiser saber mais detalhes.
    """
    conexao = conectar()
    try:
        c = conexao.execute(
            "SELECT * FROM estoque WHERE id = ? AND loja_id = ? AND status = 'disponivel'",
            (id_veiculo, loja_id),
        ).fetchone()
    finally:
        conexao.close()

    if not c:
        return "Carro não encontrado ou não está mais disponível."

    km_formatado = f"{c['km']:,}".replace(",", ".")
    return (
        f"{c['marca']} {c['modelo']} {c['ano']}\n"
        f"Cor: {c['cor']}\n"
        f"Câmbio: {c['cambio']}\n"
        f"Quilometragem: {km_formatado} km\n"
        f"Preço: {formatar_brl(c['preco'])}"
    )

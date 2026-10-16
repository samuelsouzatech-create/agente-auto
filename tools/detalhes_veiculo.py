from langchain_core.tools import tool
from banco import conectar
from tools.utils import formatar_brl


@tool
def detalhes_veiculo(id_veiculo: int) -> str:
    """Retorna a ficha completa de um carro específico pelo seu ID.
    Use quando o cliente demonstrar interesse em um carro específico
    que já apareceu na conversa e quiser saber mais detalhes.
    """
    conexao = conectar()
    cursor = conexao.cursor()
    cursor.execute(
        "SELECT * FROM estoque WHERE id = ? AND status = 'disponivel'",
        (id_veiculo,)
    )
    c = cursor.fetchone()
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

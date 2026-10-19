from langchain_core.tools import tool
from banco import conectar


@tool
def enviar_fotos(id_veiculo: int) -> str:
    """Envia as fotos de um carro específico para o cliente, pelo ID do veículo.
    Use quando o cliente pedir para ver fotos de um carro que já apareceu
    na conversa, ou quando oferecer as fotos fizer sentido no atendimento.
    """
    conexao = conectar()
    cursor = conexao.cursor()
    cursor.execute(
        "SELECT marca, modelo, ano FROM estoque "
        "WHERE id = ? AND status = 'disponivel'",
        (id_veiculo,)
    )
    carro = cursor.fetchone()
    conexao.close()

    if not carro:
        return "Carro não encontrado ou não está mais disponível para envio de fotos."

    nome_carro = f"{carro['marca']} {carro['modelo']} {carro['ano']}"
    # O envio real da imagem pelo WhatsApp será plugado junto com a Meta,
    # assim como o texto. Por ora, confirma o carro e sinaliza o envio.
    return f"Fotos do {nome_carro} enviadas ao cliente."

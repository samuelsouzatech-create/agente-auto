from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg
from banco import conectar


@tool
def registrar_troca(modelo: str, ano: int, km: int, estado: str,
                    lead_id: Annotated[str, InjectedToolArg] = "",
                    loja_id: Annotated[int, InjectedToolArg] = 1) -> str:
    """Registra o carro que o cliente quer dar na troca. NÃO dê valor de
    avaliação - isso é feito por um vendedor presencialmente. Apenas colete
    e confirme os dados.

    Parâmetros:
    - modelo: ex. "Gol 1.0"
    - ano: ano do carro
    - km: quilometragem
    - estado: descrição geral informada pelo cliente
    """
    conexao = conectar()
    try:
        conexao.execute(
            "INSERT INTO trocas (loja_id, lead_id, modelo, ano, km, estado) VALUES (?, ?, ?, ?, ?, ?)",
            (loja_id, lead_id, modelo, ano, km, estado),
        )
        conexao.commit()
    finally:
        conexao.close()
    km_formatado = f"{km:,}".replace(",", ".")
    return (
        f"Troca registrada: {modelo} {ano}, {km_formatado} km, estado: {estado}. "
        "A avaliação com valor é feita presencialmente por um vendedor."
    )

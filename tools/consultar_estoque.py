from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg
from banco import conectar
from tools.utils import formatar_brl


@tool
def consultar_estoque(marca: str = "", modelo: str = "", cor: str = "",
                      cambio: str = "", preco_max: float = 0,
                      loja_id: Annotated[int, InjectedToolArg] = 1) -> str:
    """Consulta os carros DISPONÍVEIS no estoque da loja.
    Use esta ferramenta sempre que o cliente perguntar sobre carros,
    modelos, preços ou disponibilidade. NUNCA invente carros ou preços.

    Parâmetros (todos opcionais - preencha só os que o cliente mencionou):
    - marca: ex. "Honda", "Fiat"
    - modelo: ex. "Civic", "Onix"
    - cor: ex. "Branco", "Preto"
    - cambio: "Automático" ou "Manual"
    - preco_max: preço máximo que o cliente quer pagar (ex. 80000)
    """
    sql = "SELECT * FROM estoque WHERE loja_id = ? AND status = 'disponivel'"
    parametros = [loja_id]

    if marca:
        sql += " AND sem_acento(marca) LIKE sem_acento(?)"
        parametros.append(f"%{marca}%")
    if modelo:
        sql += " AND sem_acento(modelo) LIKE sem_acento(?)"
        parametros.append(f"%{modelo}%")
    if cor:
        sql += " AND sem_acento(cor) LIKE sem_acento(?)"
        parametros.append(f"%{cor}%")
    if cambio:
        sql += " AND sem_acento(cambio) LIKE sem_acento(?)"
        parametros.append(f"%{cambio}%")
    if preco_max and preco_max > 0:
        sql += " AND preco <= ?"
        parametros.append(preco_max)

    conexao = conectar()
    try:
        carros = conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()

    if not carros:
        return "Nenhum carro disponível encontrado com esses critérios."

    linhas = []
    for c in carros:
        km_formatado = f"{c['km']:,}".replace(",", ".")
        linhas.append(
            f"ID {c['id']}: {c['marca']} {c['modelo']} {c['ano']}, "
            f"{c['cor']}, {c['cambio']}, {km_formatado} km, "
            f"{formatar_brl(c['preco'])}"
        )
    return "Carros disponíveis:\n" + "\n".join(linhas)

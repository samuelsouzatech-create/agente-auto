from langchain_core.tools import tool
from banco import conectar
from tools.utils import formatar_brl


@tool
def consultar_estoque(marca: str = "", modelo: str = "", cor: str = "",
                      cambio: str = "", preco_max: float = 0) -> str:
    """Consulta os carros DISPONÍVEIS no estoque da loja.
    Use esta ferramenta sempre que o cliente perguntar sobre carros,
    modelos, preços ou disponibilidade. NUNCA invente carros ou preços.

    Parâmetros (todos opcionais — preencha só os que o cliente mencionou):
    - marca: ex. "Honda", "Fiat"
    - modelo: ex. "Civic", "Onix"
    - cor: ex. "Branco", "Preto"
    - cambio: "Automático" ou "Manual"
    - preco_max: preço máximo que o cliente quer pagar (ex. 80000)
    """
    conexao = conectar()
    cursor = conexao.cursor()

    sql = "SELECT * FROM estoque WHERE status = 'disponivel'"
    parametros = []

    if marca:
        sql += " AND marca LIKE ?"
        parametros.append(f"%{marca}%")
    if modelo:
        sql += " AND modelo LIKE ?"
        parametros.append(f"%{modelo}%")
    if cor:
        sql += " AND cor LIKE ?"
        parametros.append(f"%{cor}%")
    if cambio:
        sql += " AND cambio LIKE ?"
        parametros.append(f"%{cambio}%")
    if preco_max and preco_max > 0:
        sql += " AND preco <= ?"
        parametros.append(preco_max)

    cursor.execute(sql, parametros)
    carros = cursor.fetchall()
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

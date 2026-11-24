from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg
from segmentos.veiculos.categorias import categoria_do_modelo, categoria_pedida
from banco import conectar
from tools.utils import formatar_brl


@tool
def consultar_estoque(marca: str = "", modelo: str = "", cor: str = "",
                      cambio: str = "", preco_max: float = 0, categoria: str = "",
                      *, loja_id: Annotated[int, InjectedToolArg]) -> str:
    """Consulta os carros DISPONÍVEIS no estoque da loja.
    Use esta ferramenta sempre que o cliente perguntar sobre carros,
    modelos, preços ou disponibilidade. NUNCA invente carros ou preços.

    Parâmetros (todos opcionais - preencha só os que o cliente mencionou):
    - marca: ex. "Honda", "Fiat"
    - modelo: ex. "Civic", "Onix"
    - cor: ex. "Branco", "Preto"
    - cambio: "Automático" ou "Manual"
    - preco_max: preço máximo que o cliente quer pagar (ex. 80000)
    - categoria: "SUV", "sedã", "hatch" ou "picape"
    """
    # L2: "SUV" no campo modelo também é pedido de categoria.
    if not categoria and categoria_pedida(modelo):
        categoria, modelo = modelo, ""
    pedida = categoria_pedida(categoria) if categoria else None
    if categoria and not pedida:
        return (f"Não sei filtrar pela categoria \"{categoria}\". Use SUV, sedã, hatch "
                "ou picape, ou consulte sem a categoria.")

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

    if pedida:
        sem_categoria = sum(1 for c in carros if categoria_do_modelo(c["modelo"]) is None)
        carros = [c for c in carros if categoria_do_modelo(c["modelo"]) == pedida]
        if not carros:
            texto = f"Nenhum carro da categoria {pedida} encontrado no estoque."
            if sem_categoria:
                texto += (f" Há {sem_categoria} carro(s) que não sei classificar: consulte "
                          "sem a categoria antes de dizer ao cliente que não tem.")
            return texto

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

from langchain_core.tools import tool
from banco import conectar


@tool(response_format="content_and_artifact")
def enviar_fotos(id_veiculo: int = 0, marca: str = "", modelo: str = ""):
    """Envia as fotos de um carro para o cliente.

    Pode ser chamada de duas formas:
    - Por id_veiculo, quando você já sabe o ID exato do carro.
    - Por marca e/ou modelo (ex.: modelo="Corolla"), quando o cliente pede
      fotos de um modelo pelo nome. Use isto quando o cliente pedir fotos já
      na primeira mensagem, sem você ainda saber o ID.

    Se houver mais de um carro do mesmo modelo, esta ferramenta NÃO envia
    fotos: ela devolve a lista das opções para você perguntar ao cliente,
    de forma natural, qual deles interessa.
    """
    conexao = conectar()
    cursor = conexao.cursor()

    # Monta a busca: por ID (exato) ou por marca/modelo (sem acento).
    if id_veiculo:
        cursor.execute(
            "SELECT id, marca, modelo, ano, cor, fotos FROM estoque "
            "WHERE id = ? AND status = 'disponivel'",
            (id_veiculo,)
        )
    else:
        sql = ("SELECT id, marca, modelo, ano, cor, fotos FROM estoque "
               "WHERE status = 'disponivel'")
        parametros = []
        if marca:
            sql += " AND sem_acento(marca) LIKE sem_acento(?)"
            parametros.append(f"%{marca}%")
        if modelo:
            sql += " AND sem_acento(modelo) LIKE sem_acento(?)"
            parametros.append(f"%{modelo}%")
        cursor.execute(sql, parametros)

    carros = cursor.fetchall()
    conexao.close()

    # Caso 1: nenhum carro encontrado.
    if not carros:
        return ("Nenhum carro disponível encontrado para enviar fotos.", [])

    # Caso 2: vários carros do mesmo modelo -> NÃO envia foto; devolve as
    # opções para o Léo perguntar qual o cliente quer.
    if len(carros) > 1:
        opcoes = [f"ID {c['id']}: {c['marca']} {c['modelo']} {c['ano']} ({c['cor']})"
                  for c in carros]
        texto = ("Há mais de um carro desse modelo. NÃO envie fotos ainda. "
                 "Pergunte ao cliente, de forma natural, qual deles ele quer ver. "
                 "Opções disponíveis: " + " | ".join(opcoes))
        return (texto, [])

    # Caso 3: exatamente um carro -> envia as fotos.
    carro = carros[0]
    nome_carro = f"{carro['marca']} {carro['modelo']} {carro['ano']}"
    campo_fotos = carro["fotos"] or ""
    urls = [u.strip() for u in campo_fotos.split(",") if u.strip()]

    if not urls:
        return (f"O {nome_carro} ainda não tem fotos cadastradas no sistema.",
                [])

    content = f"Enviando {len(urls)} foto(s) do {nome_carro} ao cliente."
    artifact = {"tipo": "fotos", "urls": urls, "carro": nome_carro}
    return (content, artifact)

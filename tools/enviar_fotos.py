from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg
from banco import conectar

_SELECT = "SELECT id, marca, modelo, ano, cor, fotos FROM estoque"


def _nome(carro) -> str:
    return f"{carro['marca']} {carro['modelo']} {carro['ano']}"


def _urls(carro) -> list:
    return [u.strip() for u in (carro["fotos"] or "").split(",") if u.strip()]


def _enviar(carro):
    urls = _urls(carro)
    if not urls:
        return (f"O {_nome(carro)} ainda não tem fotos cadastradas no sistema. "
                "Diga isso ao cliente com honestidade (não é falha do sistema) e "
                "ofereça a ficha do carro, uma visita ou fotos de outro carro que tenha.",
                [])
    return (f"Enviando {len(urls)} foto(s) do {_nome(carro)} ao cliente.",
            {"tipo": "fotos", "urls": urls, "carro": _nome(carro)})


@tool(response_format="content_and_artifact")
def enviar_fotos(id_veiculo: int = 0, marca: str = "", modelo: str = "",
                 loja_id: Annotated[int, InjectedToolArg] = 1):
    """Envia as fotos de um carro para o cliente.

    Formas de chamar:
    - Por id_veiculo, quando você já sabe o ID exato do carro.
    - Por marca e/ou modelo (ex.: modelo="Corolla"), quando o cliente pede
      fotos de um modelo pelo nome.
    - SEM nenhum filtro, quando o cliente pede fotos sem dizer o carro
      (ex.: "me manda o que tiver"): a ferramenta descobre quais carros têm foto.

    Se houver mais de um carro possível, esta ferramenta NÃO envia fotos:
    devolve as opções para você perguntar ao cliente qual ele quer ver.
    """
    base = f"{_SELECT} WHERE loja_id = ? AND status = 'disponivel'"
    sem_filtro = False
    conexao = conectar()
    try:
        if id_veiculo:
            carros = conexao.execute(base + " AND id = ?", (loja_id, id_veiculo)).fetchall()
        elif marca or modelo:
            sql, parametros = base, [loja_id]
            if marca:
                sql += " AND sem_acento(marca) LIKE sem_acento(?)"
                parametros.append(f"%{marca}%")
            if modelo:
                sql += " AND sem_acento(modelo) LIKE sem_acento(?)"
                parametros.append(f"%{modelo}%")
            carros = conexao.execute(sql, parametros).fetchall()
        else:
            sem_filtro = True
            carros = conexao.execute(
                base + " AND TRIM(COALESCE(fotos, '')) <> ''", (loja_id,)
            ).fetchall()
    finally:
        conexao.close()

    if sem_filtro:
        if not carros:
            return ("Nenhum carro do estoque tem fotos cadastradas no momento. Diga isso "
                    "ao cliente com honestidade (não é falha do sistema) e ofereça a "
                    "ficha de um carro ou uma visita.", [])
        if len(carros) == 1:
            return _enviar(carros[0])
        opcoes = [f"ID {c['id']}: {_nome(c)} ({c['cor']})" for c in carros]
        return ("Estes carros têm fotos. NÃO envie ainda: pergunte ao cliente, de forma "
                "natural, de qual deles ele quer ver. Opções: " + " | ".join(opcoes), [])

    if not carros:
        return ("Nenhum carro disponível encontrado para enviar fotos.", [])

    if len(carros) > 1:
        opcoes = [f"ID {c['id']}: {_nome(c)} ({c['cor']})" for c in carros]
        return ("Há mais de um carro desse modelo. NÃO envie fotos ainda. "
                "Pergunte ao cliente, de forma natural, qual deles ele quer ver. "
                "Opções disponíveis: " + " | ".join(opcoes), [])

    return _enviar(carros[0])

"""Ferramenta do Léo: fotos do item para o cliente.
SG2 (Maratona 4): pergunta ao CATÁLOGO do ramo da loja (app/catalogo.py), não à tabela de estoque.
Para lojas de carro o catálogo é o estoque, com as mesmas consultas de antes."""
from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg
from app.catalogo import catalogo_da_loja


def _nome(carro) -> str:
    return carro.nome


def _urls(carro, loja_id: int) -> list:
    """Maratona Fotos: só fotos do depósito desta loja (nunca endereço de terceiros)."""
    return catalogo_da_loja(loja_id).fotos(loja_id, carro)


def _enviar(carro, loja_id: int):
    urls = _urls(carro, loja_id)
    if not urls:
        return (f"O {_nome(carro)} ainda não tem fotos cadastradas no sistema. "
                "Diga isso ao cliente com honestidade (não é falha do sistema) e "
                "ofereça a ficha do carro, uma visita ou fotos de outro carro que tenha.",
                [])
    return (f"Enviando {len(urls)} foto(s) do {_nome(carro)} ao cliente.",
            {"tipo": "fotos", "urls": urls, "carro": _nome(carro)})


@tool(response_format="content_and_artifact")
def enviar_fotos(id_veiculo: int = 0, marca: str = "", modelo: str = "",
                 *, loja_id: Annotated[int, InjectedToolArg]):
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
    catalogo = catalogo_da_loja(loja_id)
    sem_filtro = False
    if id_veiculo:
        carros = catalogo.buscar(loja_id, item_id=id_veiculo)
    elif marca or modelo:
        carros = catalogo.buscar(loja_id, marca=marca, modelo=modelo)
    else:
        sem_filtro = True
        carros = catalogo.buscar(loja_id, so_com_fotos=True)

    if sem_filtro:
        if not carros:
            return ("Nenhum carro do estoque tem fotos cadastradas no momento. Diga isso "
                    "ao cliente com honestidade (não é falha do sistema) e ofereça a "
                    "ficha de um carro ou uma visita.", [])
        carros = [c for c in carros if _urls(c, loja_id)]
        if not carros:
            return ("Nenhum carro do estoque tem fotos cadastradas no momento. Diga isso "
                    "ao cliente com honestidade (não é falha do sistema) e ofereça a "
                    "ficha de um carro ou uma visita.", [])
        if len(carros) == 1:
            return _enviar(carros[0], loja_id)
        opcoes = [f"ID {c['id']}: {_nome(c)} ({c.detalhe})" for c in carros]
        return ("Estes carros têm fotos. NÃO envie ainda: pergunte ao cliente, de forma "
                "natural, de qual deles ele quer ver. Opções: " + " | ".join(opcoes), [])

    if not carros:
        return ("Nenhum carro disponível encontrado para enviar fotos.", [])

    if len(carros) > 1:
        opcoes = [f"ID {c['id']}: {_nome(c)} ({c.detalhe})" for c in carros]
        return ("Há mais de um carro desse modelo. NÃO envie fotos ainda. "
                "Pergunte ao cliente, de forma natural, qual deles ele quer ver. "
                "Opções disponíveis: " + " | ".join(opcoes), [])

    return _enviar(carros[0], loja_id)

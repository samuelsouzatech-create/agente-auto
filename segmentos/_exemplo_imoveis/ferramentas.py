"""Ferramentas do ramo de teste (imóveis). Sem nenhum código de carro."""
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from segmentos._exemplo_imoveis.catalogo import CATALOGO
from tools.utils import formatar_brl


@tool
def consultar_imoveis(bairro: str = "", *, loja_id: Annotated[int, InjectedToolArg]) -> str:
    """Consulta os imóveis disponíveis da imobiliária. Nunca invente imóvel nem preço."""
    itens = CATALOGO.buscar(loja_id, texto=bairro)
    if not itens:
        return "Nenhum imóvel disponível com esse filtro."
    return "\n".join(f"ID {i.id}: {i.nome} - {formatar_brl(i.preco)}" for i in itens)


FERRAMENTAS = [consultar_imoveis]
FERRAMENTAS_DE_MODULO: dict = {}
DESCRICOES = {"consultar_imoveis": "o cliente pergunta sobre imóveis, bairros, preços ou disponibilidade."}
FERRAMENTAS_DE_FICHA = ("consultar_imoveis",)

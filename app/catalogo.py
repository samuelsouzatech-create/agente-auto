"""
Catálogo: o que a loja oferece, visto pelo MOTOR (SG2, Maratona 4).

Cada ramo implementa o seu em segmentos/<ramo>/catalogo.py (constante CATALOGO), seguindo a
interface abaixo. O motor (ferramentas, guardas, jobs) pergunta ao catálogo; nunca à tabela de um
ramo. Veículos: o catálogo é o estoque (a tabela estoque, a API /estoque e o painel não mudaram).

Interface (todos recebem a loja; o código carimba a loja, nunca o modelo de IA):
  buscar(loja_id, *, item_id=0, marca="", modelo="", texto="", so_com_fotos=False,
         so_disponiveis=True)                       -> list[Item]
  detalhar(loja_id, item_id)                        -> Item | None (qualquer situação)
  disponivel(loja_id, item_id)                      -> bool
  fotos(loja_id, item_id)                           -> list[str] (referências do depósito)
  parecido(loja_id, item)                           -> Item | None (o que oferecer no lugar)
  citados_no_texto(loja_id, texto)                  -> list[Item] (itens cujo nome aparece no
                                                       texto, inclusive vendidos; IG2: legenda)
Ramo sem catálogo: catalogo_da_loja devolve o CATALOGO_VAZIO (não acha nada).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.chaves import exigir_loja


@dataclass
class Item:
    id: int
    nome: str                      # como o cliente lê: "Honda Civic 2019", "Apartamento Boa Viagem"
    disponivel: bool = True
    preco: float | None = None
    detalhe: str = ""              # uma característica curta (cor, bairro)
    fotos_ref: str = ""            # referências das fotos (como o ramo guarda)
    situacao: str = "disponivel"   # o status do ramo (disponivel, reservado, vendido...)
    dados: dict = field(default_factory=dict)   # o resto, do jeito do ramo


class CatalogoVazio:
    """Ramo sem catálogo: nada a buscar, nada a mostrar."""

    def buscar(self, loja_id, **_filtros) -> list[Item]:
        exigir_loja(loja_id)
        return []

    def detalhar(self, loja_id, item_id) -> Item | None:
        exigir_loja(loja_id)
        return None

    def disponivel(self, loja_id, item_id) -> bool:
        return False

    def fotos(self, loja_id, item_id) -> list[str]:
        return []

    def parecido(self, loja_id, item) -> Item | None:
        return None

    def citados_no_texto(self, loja_id, texto) -> list[Item]:
        return []

    def precos(self, loja_id, ids) -> set:
        return set()


CATALOGO_VAZIO = CatalogoVazio()


def catalogo_da_loja(loja_id):
    """O catálogo do ramo desta loja (segmentos/<ramo>/catalogo.py: CATALOGO)."""
    from app.segmentos import gancho, ramo_da_loja_id
    catalogo = gancho(ramo_da_loja_id(exigir_loja(loja_id)), "catalogo", "CATALOGO")
    return catalogo if catalogo is not None else CATALOGO_VAZIO


def catalogo_do_ramo(ramo: str):
    from app.segmentos import gancho
    catalogo = gancho(ramo, "catalogo", "CATALOGO")
    return catalogo if catalogo is not None else CATALOGO_VAZIO

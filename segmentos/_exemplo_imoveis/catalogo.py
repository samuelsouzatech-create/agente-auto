"""Catálogo do ramo de teste: 3 imóveis fictícios num JSON (iguais para toda loja deste ramo)."""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from app.catalogo import Item
from app.chaves import exigir_loja

ARQUIVO = Path(__file__).resolve().parent / "imoveis.json"


def _sem_acento(texto: str) -> str:
    t = unicodedata.normalize("NFD", str(texto or "")).lower()
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _itens() -> list[Item]:
    dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    return [Item(id=d["id"], nome=d["nome"], disponivel=d["situacao"] == "disponivel",
                 preco=float(d["preco"]), detalhe=d["bairro"], situacao=d["situacao"], dados=d)
            for d in dados]


class CatalogoDeImoveis:
    def buscar(self, loja_id, *, item_id=0, texto="", so_disponiveis=True, **_outros) -> list[Item]:
        exigir_loja(loja_id)
        itens = _itens()
        if so_disponiveis:
            itens = [i for i in itens if i.disponivel]
        if item_id:
            itens = [i for i in itens if i.id == item_id]
        if texto:
            alvo = _sem_acento(texto)
            itens = [i for i in itens if alvo in _sem_acento(i.nome) or alvo in _sem_acento(i.detalhe)]
        return itens

    def detalhar(self, loja_id, item_id) -> Item | None:
        exigir_loja(loja_id)
        return next((i for i in _itens() if i.id == item_id), None)

    def disponivel(self, loja_id, item_id) -> bool:
        item = self.detalhar(loja_id, item_id)
        return bool(item and item.disponivel)

    def fotos(self, loja_id, item_id) -> list[str]:
        return []

    def parecido(self, loja_id, item) -> Item | None:
        if item is None:
            return None
        outros = [i for i in self.buscar(loja_id) if i.id != item.id]
        return min(outros, key=lambda i: abs((i.preco or 0) - (item.preco or 0)), default=None)

    def precos(self, loja_id, ids) -> set:
        return {int(i.preco * 100) for i in _itens() if i.id in set(ids)}

    def citados_no_texto(self, loja_id, texto) -> list[Item]:
        normal = _sem_acento(texto)
        return [i for i in _itens() if _sem_acento(i.detalhe) in normal]


CATALOGO = CatalogoDeImoveis()

"""Conta da paginação (S10b, decisão 5A). Sem Streamlit e sem banco.

As listas do painel já chegam limitadas pela camada app/ (ex.: o Registro
traz no máximo 200 linhas); aqui só se escolhe o pedaço de cada página.
"""
from __future__ import annotations

from math import ceil

TAMANHO_PAGINA = 50


def pagina_de(itens, pagina, tamanho: int = TAMANHO_PAGINA) -> dict:
    """Pedaço da lista para a página pedida. Página fora do intervalo é ajustada."""
    tamanho = max(1, int(tamanho))
    lista = list(itens)
    total = len(lista)
    paginas = max(1, ceil(total / tamanho))
    try:
        pagina = int(pagina)
    except (TypeError, ValueError):
        pagina = 1
    pagina = min(max(1, pagina), paginas)
    inicio = (pagina - 1) * tamanho
    fatia = lista[inicio:inicio + tamanho]
    return {"itens": fatia, "pagina": pagina, "paginas": paginas, "total": total,
            "de": inicio + 1 if total else 0, "ate": inicio + len(fatia)}


def texto_da_pagina(p: dict) -> str:
    """Ex.: 'página 2 de 7 · 51 a 100 de 320'."""
    return f"página {p['pagina']} de {p['paginas']} · {p['de']} a {p['ate']} de {p['total']}"

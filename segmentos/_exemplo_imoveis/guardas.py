"""A guarda própria do ramo de teste (imóveis): documentação/estado do imóvel não se afirma.

Usa o gancho `cortar_estado_inventado` do contrato (passo 8 da lista N4): a frase que garante
documentação ou estado do imóvel, sem vir da ficha, vira a frase do corretor.
"""
from __future__ import annotations

import re
import unicodedata

FRASE_DO_CORRETOR = "A documentação e o estado do imóvel o corretor confirma com você."
_GARANTIA = re.compile(r"\b(documentacao\s+(ok|em\s+dia|100%|perfeita)|sem\s+infiltrac\w*|escritura\s+garantid\w*)")


def _sem_acento(texto: str) -> str:
    t = unicodedata.normalize("NFD", str(texto or "")).lower()
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def cortar_estado_inventado(resposta: str, ficha: str = "", substituir: bool = True) -> tuple[str, bool]:
    frases = [f for f in re.split(r"(?<=[.!?])\s+", str(resposta or "")) if f.strip()]
    saida, trocou = [], False
    for frase in frases:
        achado = _GARANTIA.search(_sem_acento(frase))
        if achado and achado.group(0) not in _sem_acento(ficha):
            if not trocou and substituir:
                saida.append(FRASE_DO_CORRETOR)
            trocou = True
        else:
            saida.append(frase)
    return (" ".join(saida) if trocou else resposta), trocou

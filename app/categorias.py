"""
Categoria do carro (SUV, sedã, hatch, picape) pelo modelo (Bloco L2).

O estoque não tem coluna de categoria: o cliente pergunta "tem SUV?" e a
busca por marca/modelo não acha nada. Aqui fica a lista dos modelos mais
comuns no Brasil por categoria. Modelo fora da lista fica sem categoria
(a busca avisa que existem carros fora da lista, para o Léo nunca dizer
"não temos" por causa disso).
"""
from __future__ import annotations

import re
import unicodedata

SUV, SEDA, HATCH, PICAPE = "SUV", "sedã", "hatch", "picape"

# Nome que o cliente usa -> categoria.
_SINONIMOS = {
    "suv": SUV, "suvs": SUV, "utilitario esportivo": SUV, "crossover": SUV,
    "seda": SEDA, "sedan": SEDA, "sedas": SEDA, "sedans": SEDA,
    "hatch": HATCH, "hatchs": HATCH, "hatchback": HATCH, "hatches": HATCH,
    "picape": PICAPE, "picapes": PICAPE, "pickup": PICAPE, "pick-up": PICAPE,
    "pick up": PICAPE, "caminhonete": PICAPE, "caminhonetes": PICAPE,
}

# Modelos por categoria. Nomes compostos vêm antes dos simples
# ("corolla cross" é SUV, "corolla" é sedã; "hb20s" é sedã, "hb20" é hatch).
_MODELOS = {
    SUV: ["corolla cross", "renegade", "compass", "commander", "hr-v", "hrv", "wr-v", "wrv",
          "creta", "tucson", "ix35", "t-cross", "tcross", "taos", "tiguan", "nivus", "kicks",
          "tracker", "equinox", "trailblazer", "ecosport", "territory", "duster", "captur",
          "pulse", "fastback", "2008", "3008", "c4 cactus", "aircross", "sportage", "sorento",
          "rav4", "sw4", "outlander", "asx", "eclipse cross", "pajero", "tiggo", "haval",
          "song", "yuan", "x1", "x3", "q3", "q5", "gla", "glc", "xc40", "xc60", "evoque"],
    PICAPE: ["strada", "toro", "titano", "hilux", "s10", "ranger", "maverick", "amarok",
             "saveiro", "montana", "oroch", "frontier", "l200", "triton", "rampage", "ram"],
    SEDA: ["onix plus", "hb20s", "civic", "corolla", "cruze", "prisma", "cobalt", "virtus",
           "jetta", "voyage", "versa", "sentra", "city", "cronos", "siena", "grand siena",
           "logan", "yaris sedan", "fluence", "a3 sedan", "a4", "serie 3", "320i", "c180",
           "c200", "fusion"],
    HATCH: ["onix", "hb20", "gol", "polo", "fox", "up", "argo", "mobi", "uno", "palio",
            "kwid", "sandero", "ka", "fiesta", "208", "c3", "march", "fit", "yaris", "etios",
            "celta", "agile", "golf", "i30", "punto", "clio", "picanto", "a1"],
}

_POR_MODELO = sorted(((m, cat) for cat, ms in _MODELOS.items() for m in ms),
                     key=lambda par: len(par[0]), reverse=True)


def _normalizar(texto) -> str:
    sem = unicodedata.normalize("NFD", str(texto or ""))
    sem = "".join(c for c in sem if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"\s+", " ", sem).strip()


def categoria_pedida(texto) -> str | None:
    """'SUV', 'sedan', 'pick-up'... -> categoria oficial. Outra palavra -> None."""
    return _SINONIMOS.get(_normalizar(texto))


def categoria_do_modelo(modelo) -> str | None:
    """Categoria de um modelo do estoque ('Renegade' -> 'SUV'). Fora da lista -> None."""
    nome = _normalizar(modelo)
    for chave, categoria in _POR_MODELO:
        if re.search(r"(?<![a-z0-9])" + re.escape(chave) + r"(?![a-z0-9])", nome):
            return categoria
    return None

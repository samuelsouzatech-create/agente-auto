"""
Segmentos descobertos pelas PASTAS (Etapa 2, Bloco 1).

Antes era uma lista fixa (SEGMENTOS = {"veiculos"}). Agora um segmento existe
quando há uma pasta segmentos/<nome>/ com um prompt.md. O pacote do segmento:

  prompt.md        persona e objetivo do ramo (obrigatório)
  ferramentas.py   FERRAMENTAS do ramo e FERRAMENTAS_DE_MODULO (opcional)
  modelos.json     modelos de mensagem da Meta (opcional)
  reguas.json      réguas-modelo de pós-venda (Bloco 5)

O motor fala com o segmento só por aqui. Ele não conhece carro.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PASTA_SEGMENTOS = RAIZ / "segmentos"
_NOME_VALIDO = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


class SegmentoInexistente(ValueError):
    """A loja aponta para um segmento sem pasta (ou sem prompt.md)."""


def segmentos_disponiveis() -> list[str]:
    pasta = Path(PASTA_SEGMENTOS)
    if not pasta.is_dir():
        return []
    return sorted(
        p.name for p in pasta.iterdir()
        if p.is_dir() and _NOME_VALIDO.match(p.name) and (p / "prompt.md").is_file()
    )


def segmento_existe(nome) -> bool:
    return isinstance(nome, str) and nome in segmentos_disponiveis()


def pasta_do_segmento(nome) -> Path:
    if not segmento_existe(nome):
        disponiveis = ", ".join(segmentos_disponiveis()) or "nenhum"
        raise SegmentoInexistente(
            f"O segmento '{nome}' não existe (disponíveis: {disponiveis}). "
            "Cada segmento é uma pasta em segmentos/ com um prompt.md.")
    return Path(PASTA_SEGMENTOS) / nome


# Cache por data de modificação: editou o arquivo, vale na próxima mensagem.
_cache_modulos: dict[str, tuple[int, object]] = {}


def modulo_do_segmento(nome: str, arquivo: str):
    """Carrega segmentos/<nome>/<arquivo>.py, ou None se não existir."""
    caminho = pasta_do_segmento(nome) / f"{arquivo}.py"
    if not caminho.is_file():
        return None
    chave = str(caminho.resolve())
    modificado = caminho.stat().st_mtime_ns
    guardado = _cache_modulos.get(chave)
    if guardado and guardado[0] == modificado:
        return guardado[1]
    nome_modulo = f"_segmento_{nome}_{arquivo}_{abs(hash((chave, modificado)))}"
    spec = importlib.util.spec_from_file_location(nome_modulo, caminho)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nome_modulo] = modulo
    try:
        spec.loader.exec_module(modulo)
    except Exception:
        sys.modules.pop(nome_modulo, None)
        raise
    _cache_modulos[chave] = (modificado, modulo)
    return modulo


def ferramentas_do_segmento(nome: str) -> list:
    modulo = modulo_do_segmento(nome, "ferramentas")
    return list(getattr(modulo, "FERRAMENTAS", []) or []) if modulo else []


def ferramentas_de_modulo_do_segmento(nome: str) -> dict[str, list]:
    modulo = modulo_do_segmento(nome, "ferramentas")
    if modulo is None:
        return {}
    return {k: list(v) for k, v in (getattr(modulo, "FERRAMENTAS_DE_MODULO", {}) or {}).items()}

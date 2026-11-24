"""
Segmentos (ramos) descobertos pelas PASTAS (Etapa 2, Bloco 1) e o ENCAIXE do motor com o ramo (SG1).

Um ramo existe quando há uma pasta segmentos/<nome>/ com um prompt.md. O contrato completo do
pacote de ramo (o que cada ramo entrega e onde o motor chama) está em docs/pacote_de_ramo.md.

O motor fala com o ramo SÓ por aqui. Ele não conhece carro e não escreve o nome de nenhum ramo
(a catraca de ramo, tests/test_catraca_ramo.py, reprova importar um ramo em app/ e tools/).
A única exceção é RAMO_PADRAO: o ramo de quem não tem ramo gravado (lojas antigas).

SG1: os arquivos .py do ramo são importados como PACOTE Python (segmentos.<ramo>.<arquivo>), por
nome montado na hora, a partir do ramo da loja. Assim o motor, os testes e o próprio ramo usam o
MESMO módulo (trocar uma função num teste vale para o motor). Editou o arquivo: vale na próxima
mensagem (o módulo é recarregado). Pasta de ramo fora da pasta oficial (testes): carga pelo caminho.

SG2: ramo cujo nome começa com "_" é OCULTO (ramo de teste): não aparece como opção nem pode ser
usado por loja real; só quando os testes ligam RAMOS_OCULTOS_LIGADOS.
"""
from __future__ import annotations

import importlib
import importlib.util
import re
import sys
from collections.abc import Set
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PASTA_SEGMENTOS = RAIZ / "segmentos"
_PASTA_OFICIAL = PASTA_SEGMENTOS
_NOME_VALIDO = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_NOME_OCULTO = re.compile(r"^_[a-z][a-z0-9_]{1,38}$")

# Lojas sem ramo gravado (antigas) são deste ramo: o único real hoje.
RAMO_PADRAO = "veiculos"

# SG2: ramos de teste (pasta começando com "_") só valem quando os testes ligam isto.
RAMOS_OCULTOS_LIGADOS = False


class SegmentoInexistente(ValueError):
    """A loja aponta para um segmento sem pasta (ou sem prompt.md)."""


def _pastas_validas(incluir_ocultos: bool) -> list[str]:
    pasta = Path(PASTA_SEGMENTOS)
    if not pasta.is_dir():
        return []
    nomes = []
    for p in pasta.iterdir():
        if not (p.is_dir() and (p / "prompt.md").is_file()):
            continue
        if _NOME_VALIDO.match(p.name) or (incluir_ocultos and _NOME_OCULTO.match(p.name)):
            nomes.append(p.name)
    return sorted(nomes)


def segmentos_disponiveis() -> list[str]:
    """Os ramos que uma loja pode usar (os ocultos, de teste, só com RAMOS_OCULTOS_LIGADOS)."""
    return _pastas_validas(RAMOS_OCULTOS_LIGADOS)


def segmento_existe(nome) -> bool:
    return isinstance(nome, str) and nome in segmentos_disponiveis()


def pasta_do_segmento(nome) -> Path:
    if not segmento_existe(nome):
        disponiveis = ", ".join(segmentos_disponiveis()) or "nenhum"
        raise SegmentoInexistente(
            f"O segmento '{nome}' não existe (disponíveis: {disponiveis}). "
            "Cada segmento é uma pasta em segmentos/ com um prompt.md.")
    return Path(PASTA_SEGMENTOS) / nome


def ramo_da_loja(loja) -> str:
    """O ramo de uma loja (objeto Loja). Sem ramo gravado: RAMO_PADRAO."""
    return getattr(loja, "segmento", None) or RAMO_PADRAO


def ramo_da_loja_id(loja_id) -> str:
    """O ramo pelo número da loja. Se não der para ler a loja: RAMO_PADRAO (como era antes do SG1)."""
    try:
        from app.lojas import carregar_loja
        return ramo_da_loja(carregar_loja(loja_id))
    except Exception:
        return RAMO_PADRAO


# Cache por data de modificação: editou o arquivo, vale na próxima mensagem.
_cache_modulos: dict[str, tuple[int, object]] = {}


def _e_pacote_oficial(nome: str) -> bool:
    pasta = Path(PASTA_SEGMENTOS)
    return (pasta.resolve() == _PASTA_OFICIAL.resolve() and (pasta / "__init__.py").is_file()
            and (pasta / nome / "__init__.py").is_file())


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
    if _e_pacote_oficial(nome):
        # SG1: o mesmo módulo que os testes e o próprio ramo importam (nome montado na hora).
        nome_modulo = ".".join(("segmentos", nome, arquivo))
        ja = sys.modules.get(nome_modulo)
        modulo = importlib.reload(ja) if (ja is not None and guardado) else importlib.import_module(nome_modulo)
        _cache_modulos[chave] = (modificado, modulo)
        return modulo
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


# ----------------------------------------------------------------------------------------------
# SG1: ganchos do contrato (docs/pacote_de_ramo.md)
# ----------------------------------------------------------------------------------------------
def gancho(ramo: str, arquivo: str, nome: str):
    """A função (ou constante) `nome` de segmentos/<ramo>/<arquivo>.py, ou None.
    Lida na HORA da chamada: um teste que troca a função no módulo do ramo vale para o motor."""
    try:
        modulo = modulo_do_segmento(ramo, arquivo)
    except SegmentoInexistente:
        return None
    return getattr(modulo, nome, None) if modulo is not None else None


def valor_do_ramo(ramo: str, arquivo: str, nome: str, padrao=None):
    valor = gancho(ramo, arquivo, nome)
    return padrao if valor is None else valor


def _ramos_carregados() -> list[str]:
    """Ramos cujo pacote já foi importado neste processo (o motor nunca carrega um ramo à toa)."""
    return [n for n in _pastas_validas(True) if ".".join(("segmentos", n)) in sys.modules]


def _nomes_do_ramo(ramo: str, atributo: str) -> set[str]:
    try:
        modulo = modulo_do_segmento(ramo, "ferramentas") if segmento_existe(ramo) or \
            _NOME_OCULTO.match(ramo) else None
    except SegmentoInexistente:
        return set()
    if modulo is None:
        return set()
    if atributo == "TODAS":
        todas = list(getattr(modulo, "FERRAMENTAS", []) or [])
        for lista in (getattr(modulo, "FERRAMENTAS_DE_MODULO", {}) or {}).values():
            todas += list(lista)
        return {f.name for f in todas}
    return set(getattr(modulo, atributo, ()) or ())


class NomesDoMotorEDosRamos(Set):
    """Conjunto de nomes de ferramenta: os do motor + os que cada ramo JÁ CARREGADO declara.
    Uma ferramenta de ramo só pode ser chamada depois que o ramo foi carregado; então olhar só os
    carregados dá o mesmo resultado sem carregar ramo nenhum à toa (SG2: loja de imóveis nunca
    carrega o pacote de veículos)."""

    def __init__(self, base, atributo: str):
        self._base = frozenset(base)
        self._atributo = atributo

    def _todos(self) -> frozenset:
        nomes = set(self._base)
        for ramo in _ramos_carregados():
            nomes |= _nomes_do_ramo(ramo, self._atributo)
        return frozenset(nomes)

    def __contains__(self, nome) -> bool:
        return nome in self._base or nome in self._todos()

    def __iter__(self):
        return iter(self._todos())

    def __len__(self) -> int:
        return len(self._todos())

    def __repr__(self) -> str:
        return f"NomesDoMotorEDosRamos({sorted(self._todos())!r})"

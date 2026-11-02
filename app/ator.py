"""
Quem está fazendo a ação (P6 do Plano Mestre).

Quem CHAMA define o ator: a tela, a API ou o job. As funções de app/ leem
o ator daqui e NÃO mudam de assinatura. Assim o campo livre "Seu nome"
deixa de existir: o nome vem da sessão.

O ator fica num contextvar: vale só para a execução atual (cada sessão do
painel, cada requisição, cada rodada de job tem o seu).

Papéis por enquanto: 'cliente' (painel da loja), 'operador' e 'sistema'
(robôs: relógio, webhook). O P8 traz os papéis de verdade (vendedor,
gestor, dono, suporte).
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass

from app.chaves import exigir_loja

PAPEIS = ("cliente", "operador", "sistema")
ORIGENS = ("painel", "api", "job", "webhook")
MAX_PESSOA = 80


class SemAtor(RuntimeError):
    """Escrita relevante sem saber quem fez: quem chamou esqueceu de definir o ator."""


class AtorInvalido(ValueError):
    pass


@dataclass(frozen=True)
class Ator:
    pessoa: str
    papel: str
    origem: str
    loja_id: int | None     # None = enxerga todas as lojas (operador, sistema)


_ATOR: contextvars.ContextVar = contextvars.ContextVar("ator_do_leo", default=None)


def _criar(pessoa, papel, origem, loja_id) -> Ator:
    nome = " ".join(str(pessoa or "").split())
    if not nome:
        raise AtorInvalido("Falta o nome de quem está agindo.")
    if len(nome) > MAX_PESSOA:
        raise AtorInvalido(f"Nome com mais de {MAX_PESSOA} caracteres.")
    if papel not in PAPEIS:
        raise AtorInvalido(f"Papel '{papel}' não existe (válidos: {', '.join(PAPEIS)}).")
    if origem not in ORIGENS:
        raise AtorInvalido(f"Origem '{origem}' não existe (válidas: {', '.join(ORIGENS)}).")
    loja = None if loja_id is None else exigir_loja(loja_id)
    if papel == "cliente" and loja is None:
        raise AtorInvalido("Quem age pelo painel da loja precisa ter a loja.")
    return Ator(nome, papel, origem, loja)


def definir_ator(pessoa, papel, origem, loja_id=None) -> Ator:
    """Define quem age daqui em diante, nesta execução."""
    ator = _criar(pessoa, papel, origem, loja_id)
    _ATOR.set(ator)
    return ator


def ator_atual() -> Ator | None:
    return _ATOR.get()


def exigir_ator() -> Ator:
    ator = _ATOR.get()
    if ator is None:
        raise SemAtor("Ação sem autor: defina o ator antes (tela, API ou job).")
    return ator


@contextmanager
def como(pessoa, papel, origem, loja_id=None):
    """Age como alguém só dentro do bloco 'with'. Ao sair, volta o anterior."""
    marca = _ATOR.set(_criar(pessoa, papel, origem, loja_id))
    try:
        yield _ATOR.get()
    finally:
        _ATOR.reset(marca)


@contextmanager
def como_sistema(nome, origem):
    """Para os robôs (relógio, webhook): ator explícito de sistema, sem loja fixa."""
    with como(nome, "sistema", origem, None) as ator:
        yield ator


@contextmanager
def sem_ator():
    """Tira o ator dentro do bloco (usado nos testes de 'sem ator falha')."""
    marca = _ATOR.set(None)
    try:
        yield
    finally:
        _ATOR.reset(marca)

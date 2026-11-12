"""
Quem entra nas áreas de gestão (C2d): só dono e gerente, e só com o módulo ligado.

- Papel errado (vendedor, vendedor do link): 403 sem_permissao.
- Módulo não contratado: 403 modulo_desligado (contrato, item 18).
- Leitura não pede CSRF; escrita pede (exigir_csrf vem antes de tudo).
A loja vem só da sessão.
"""
from __future__ import annotations

from fastapi import Depends

from app.api_painel.dependencias import exigir_csrf, usuario_logado
from app.api_painel.erros import ErroApi
from app.api_painel.eu import modulos_da_loja
from app.lojas import carregar_loja

GESTAO = ("dono", "gestor")
ACOMPANHAMENTO, ESTOQUE = "acompanhamento", "estoque"


def conferir(sessao: dict, modulo: str) -> dict:
    if sessao["papel"] not in GESTAO:
        raise ErroApi("sem_permissao")
    if not modulos_da_loja(carregar_loja(sessao["loja_id"]))[modulo]:
        raise ErroApi("modulo_desligado")
    return sessao


def leitura(modulo: str):
    def _dependencia(sessao: dict = Depends(usuario_logado)) -> dict:
        return conferir(sessao, modulo)
    return _dependencia


def escrita(modulo: str):
    def _dependencia(sessao: dict = Depends(exigir_csrf)) -> dict:
        return conferir(sessao, modulo)
    return _dependencia

"""
Dependências comuns da API do painel (C2a).

- usuario_logado: a sessão do cookie leo_sessao. Sem sessão válida, 401.
  Sessão em dia de quem não usa este painel (operador, suporte), 403.
- exigir_papel(...): só os papéis listados passam (403 para os outros).
- loja_da_sessao: a ÚNICA fonte da loja. Nenhuma rota lê loja_id do pedido.
- exigir_csrf: toda rota que escreve exige X-CSRF-Token igual ao csrf da sessão.
"""
from __future__ import annotations

from fastapi import Depends, Request

from app import sessoes
from app.api_painel.erros import ErroApi

COOKIE = "leo_sessao"
CABECALHO_CSRF = "X-CSRF-Token"


def token_do_pedido(request: Request):
    return request.cookies.get(COOKIE) or None


def usuario_logado(request: Request) -> dict:
    token = token_do_pedido(request)
    sessao = sessoes.ler_sessao(token)
    if sessao is None:
        if sessoes.sessao_sem_acesso(token):
            raise ErroApi("sem_permissao")
        raise ErroApi("nao_autenticado")
    return sessao


def exigir_papel(*papeis: str):
    permitidos = frozenset(papeis)

    def _dependencia(sessao: dict = Depends(usuario_logado)) -> dict:
        if sessao["papel"] not in permitidos:
            raise ErroApi("sem_permissao")
        return sessao

    return _dependencia


def loja_da_sessao(sessao: dict = Depends(usuario_logado)) -> int:
    return sessao["loja_id"]


def exigir_csrf(request: Request, sessao: dict = Depends(usuario_logado)) -> dict:
    if not sessoes.conferir_csrf(token_do_pedido(request), request.headers.get(CABECALHO_CSRF)):
        raise ErroApi("csrf_invalido")
    return sessao

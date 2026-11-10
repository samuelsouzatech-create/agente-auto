"""
Rotas de acesso (C2a): login, logout, eu e trocar-senha.

- login responde SEMPRE igual para qualquer falha (e-mail desconhecido, senha
  errada, operador, suporte, loja desligada). Erros demais: 429.
- O cookie leo_sessao é HttpOnly, Secure e SameSite=Lax, e vale 7 dias.
- Nenhuma rota lê loja_id do pedido: a loja vem só da sessão.
- trocar-senha define o ator a partir da sessão antes de chamar app/.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from banco import conectar
from app import autenticacao, sessoes
from app.ator import como
from app.api_painel.dependencias import COOKIE, exigir_csrf, exigir_papel, token_do_pedido
from app.api_painel.erros import ErroApi
from app.api_painel.eu import montar_eu

MAX_EMAIL = 254
router = APIRouter(prefix="/auth", tags=["Acesso"])


class LoginEntrada(BaseModel):
    email: str = ""
    senha: str = ""


class TrocarSenhaEntrada(BaseModel):
    senha_atual: str = ""
    senha_nova: str = ""


def _gravar_cookie(resposta: Response, token: str) -> None:
    resposta.set_cookie(COOKIE, token, max_age=int(sessoes.DURACAO.total_seconds()), path="/",
                        secure=True, httponly=True, samesite="lax")


def _apagar_cookie(resposta: Response) -> None:
    resposta.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")


def _pessoa(usuario_id):
    conexao = conectar()
    try:
        return conexao.execute("SELECT id, loja_id, papel, ativo FROM usuarios WHERE id = ?",
                               (usuario_id,)).fetchone()
    finally:
        conexao.close()


@router.post("/login")
def login(entrada: LoginEntrada, resposta: Response):
    email = entrada.email.strip().lower()[:MAX_EMAIL]
    achado = autenticacao.autenticar(email, entrada.senha)
    if achado is None:
        if autenticacao.bloqueado_por_tentativas(email):
            raise ErroApi("muitas_tentativas")
        raise ErroApi("credenciais_invalidas")
    pessoa = _pessoa(achado["id"])
    if pessoa is None or pessoa["papel"] not in sessoes.PAPEIS_COM_LOGIN or not pessoa["loja_id"]:
        raise ErroApi("credenciais_invalidas")
    try:
        token = sessoes.criar_sessao(pessoa["id"], pessoa["loja_id"], pessoa["papel"])
    except ValueError:
        raise ErroApi("credenciais_invalidas") from None
    sessao = sessoes.ler_sessao(token)
    if sessao is None:                      # loja desligada, por exemplo
        sessoes.revogar(token)
        raise ErroApi("credenciais_invalidas")
    _gravar_cookie(resposta, token)
    return montar_eu(sessao, token)


@router.post("/logout", status_code=204)
def logout(request: Request, sessao: dict = Depends(exigir_csrf)):
    sessoes.revogar(token_do_pedido(request))
    resposta = Response(status_code=204)
    _apagar_cookie(resposta)
    return resposta


@router.get("/eu")
def eu(request: Request, sessao: dict = Depends(exigir_papel(*sessoes.PAPEIS_DA_SESSAO))):
    return montar_eu(sessao, token_do_pedido(request))


@router.post("/trocar-senha", status_code=204)
def trocar_senha(entrada: TrocarSenhaEntrada, request: Request,
                 sessao: dict = Depends(exigir_csrf)):
    if sessao["papel"] not in sessoes.PAPEIS_COM_LOGIN:      # o link não tem senha
        raise ErroApi("sem_permissao")
    with como(sessao["nome"], "cliente", "api", sessao["loja_id"]):
        try:
            autenticacao.trocar_senha(sessao["usuario_id"], entrada.senha_atual, entrada.senha_nova,
                                      manter_sessao=token_do_pedido(request))
        except autenticacao.SenhaAtualErrada:
            raise ErroApi("invalido", {"senha_atual": "Senha atual incorreta."}) from None
        except autenticacao.MuitasTentativas:
            raise ErroApi("muitas_tentativas") from None
        except autenticacao.SenhaFraca as erro:
            raise ErroApi("senha_fraca", {"senha_nova": str(erro)}) from None
        except autenticacao.DadosInvalidos:
            raise ErroApi("invalido") from None
    return Response(status_code=204)

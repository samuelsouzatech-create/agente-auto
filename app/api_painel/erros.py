"""
Formato único de erro da API do painel: {codigo, mensagem, campos?}.

Toda falha sai neste formato: as nossas (ErroApi), entrada inválida, rota
que não existe e erro inesperado. A mensagem é para gente, sem texto técnico.
Nunca devolve o que a pessoa digitou (pode ser uma senha).
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# código -> (status HTTP, mensagem padrão)
CODIGOS = {
    "nao_autenticado": (401, "Entre para continuar."),
    "credenciais_invalidas": (401, "E-mail ou senha incorretos."),
    "sem_permissao": (403, "Você não tem permissão para esta ação."),
    "csrf_invalido": (403, "Sua sessão precisa ser confirmada. Recarregue a página e tente de novo."),
    "senha_fraca": (422, "A senha é fraca demais. Use pelo menos 10 caracteres e evite senhas comuns."),
    "invalido": (422, "Confira os campos destacados."),
    "muitas_tentativas": (429, "Muitas tentativas. Espere alguns minutos ou fale com o suporte."),
    "nao_encontrado": (404, "Não encontrado."),
    "erro_interno": (500, "Algo deu errado. Tente de novo em instantes."),
}

# Os que as rotas do C2a podem devolver (o teste confere que existem no contrato).
CODIGOS_DO_C2A = ("nao_autenticado", "credenciais_invalidas", "sem_permissao", "csrf_invalido",
                  "senha_fraca", "invalido", "muitas_tentativas")

_PARTES_TECNICAS = {"body", "query", "path", "header", "cookie"}


class ErroApi(Exception):
    def __init__(self, codigo: str, campos: dict | None = None, mensagem: str | None = None):
        status, padrao = CODIGOS[codigo]
        super().__init__(codigo)
        self.status = status
        self.codigo = codigo
        self.mensagem = mensagem or padrao
        self.campos = dict(campos) if campos else None

    def corpo(self) -> dict:
        corpo = {"codigo": self.codigo, "mensagem": self.mensagem}
        if self.campos:
            corpo["campos"] = self.campos
        return corpo


def _json(codigo: str, status: int | None = None, campos: dict | None = None) -> JSONResponse:
    erro = ErroApi(codigo, campos)
    return JSONResponse(erro.corpo(), status_code=status or erro.status)


def instalar(app: FastAPI) -> None:
    @app.exception_handler(ErroApi)
    async def _erro_api(request: Request, erro: ErroApi):
        return JSONResponse(erro.corpo(), status_code=erro.status)

    @app.exception_handler(RequestValidationError)
    async def _entrada_invalida(request: Request, erro: RequestValidationError):
        campos = {}
        for item in erro.errors():
            nome = ".".join(str(p) for p in item.get("loc", ()) if p not in _PARTES_TECNICAS)
            campos[nome or "corpo"] = "Valor inválido."
        return _json("invalido", campos=campos)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, erro: StarletteHTTPException):
        if erro.status_code in (404, 405):
            return _json("nao_encontrado", status=erro.status_code)
        return _json("invalido", status=erro.status_code)

    @app.exception_handler(Exception)
    async def _inesperado(request: Request, erro: Exception):
        return _json("erro_interno")

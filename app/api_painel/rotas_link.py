"""
Rota do C3: o link do vendedor que vem no aviso.

- Pública (sem sessão e sem CSRF), como o login. É GET porque é um link clicado.
- Link certo: cria a sessão de escopo "link" (só aquela conversa), grava o
  cookie e leva à conversa no front, sem o token no endereço.
- Link usado, vencido ou anulado: leva a /link-invalido?motivo=... no front.
- Links errados demais da mesma origem: 429, no formato de erro de sempre.
- O log de acesso mostra /v/*** (logs.py), nunca o token.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app import links_vendedor
from app.api_painel.erros import ErroApi
from app.api_painel.rotas_auth import _gravar_cookie

router = APIRouter(tags=["Link"])


@router.get("/v/{token}", status_code=302)
def abrir_link(token: str, request: Request):
    origem = request.client.host if request.client else "desconhecida"
    if links_vendedor.link_errado_demais(origem):
        raise ErroApi("muitas_tentativas")
    try:
        feito = links_vendedor.usar_link(token)
    except links_vendedor.LinkRecusado as erro:
        links_vendedor.anotar_link_errado(origem)
        return RedirectResponse(links_vendedor.url_link_invalido(erro.motivo), status_code=302)
    resposta = RedirectResponse(links_vendedor.url_da_conversa(feito["lead_id"]), status_code=302)
    _gravar_cookie(resposta, feito["sessao"])
    return resposta

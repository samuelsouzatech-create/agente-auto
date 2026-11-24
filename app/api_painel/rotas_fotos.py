"""
Maratona Fotos (F1): entrega uma foto do ESTOQUE que está no depósito.

GET /fotos/{nome}
- Dono e gerente (quem vê o Estoque). A loja vem só da sessão: a foto procurada é sempre
  "loja-<da sessão>/<nome>"; foto de outra loja simplesmente não existe (404).
- Nome só no formato do depósito (aleatório, .jpg); qualquer outro nome: 404.
- Com a tomada nuvem, o painel já recebe o endereço https público; esta rota continua valendo.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app import deposito as _deposito, fotos as _fotos
from app.api_painel.dependencias import exigir_papel
from app.api_painel.erros import ErroApi

router = APIRouter(tags=["Estoque"])
NAO_ENCONTRADA = "Não encontramos essa foto."


@router.get("/fotos/{nome}", response_class=Response,
            responses={200: {"content": {"image/jpeg": {}}, "description": "A foto."}})
def foto(nome: str, sessao: dict = Depends(exigir_papel("dono", "gestor"))):
    if not _fotos.NOME.match(str(nome or "")):
        raise ErroApi("nao_encontrado", mensagem=NAO_ENCONTRADA)
    try:
        dados = _fotos.ler(sessao["loja_id"], _fotos.ref_de(sessao["loja_id"], nome))
    except (_deposito.FotoNaoEncontrada, _deposito.FalhaNoDeposito, _deposito.DepositoMalConfigurado):
        raise ErroApi("nao_encontrado", mensagem=NAO_ENCONTRADA) from None
    return Response(dados, media_type=_deposito.TIPO, headers={"Cache-Control": "private, max-age=86400"})

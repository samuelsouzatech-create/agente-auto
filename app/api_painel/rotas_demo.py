"""
GET /demo/fotos/{arquivo} — DESATIVADA na Maratona Fotos (F1).

Era o remendo do Q2 (arquivo no banco, endereço na API). Agora a demo grava as fotos no
depósito, como qualquer loja, e o painel usa GET /fotos/{nome}. A rota continua no contrato
(v1 só cresce; marcada como deprecated) e responde sempre 404, no formato de erro de sempre.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api_painel.dependencias import exigir_papel
from app.api_painel.erros import ErroApi

router = APIRouter(prefix="/demo", tags=["Estoque"])
NAO_ENCONTRADA = "Não encontramos essa foto."


@router.get("/fotos/{arquivo}", responses={200: {"content": {"image/png": {}}, "description": "A foto."}})
def foto_da_demo(arquivo: str, sessao: dict = Depends(exigir_papel("dono", "gestor"))):
    raise ErroApi("nao_encontrado", mensagem=NAO_ENCONTRADA)

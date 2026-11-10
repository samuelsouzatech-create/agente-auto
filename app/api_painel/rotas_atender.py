"""
Rotas do C2b: a luz "Léo atendendo" e a lista da tela Atender.

- GET /saude e GET /atender: dono, gestor e vendedor (x-papeis do contrato).
  O vendedor do link recebe 403: ele só vê a conversa do link (C2c).
- A loja vem só da sessão (loja_da_sessao). loja_id no pedido é ignorado.
- Só leitura: nenhuma das duas escreve, então não pedem X-CSRF-Token.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api_painel.atender import montar_atender
from app.api_painel.dependencias import exigir_papel, loja_da_sessao
from app.api_painel.saude import montar_saude

QUEM_VE_SAUDE = ("dono", "gestor", "vendedor")
QUEM_VE_ATENDER = ("dono", "gestor", "vendedor")

router = APIRouter()


@router.get("/saude", tags=["Estado"])
def saude(_sessao: dict = Depends(exigir_papel(*QUEM_VE_SAUDE)),
          loja_id: int = Depends(loja_da_sessao)):
    return montar_saude(loja_id)


@router.get("/atender", tags=["Atender"])
def atender(_sessao: dict = Depends(exigir_papel(*QUEM_VE_ATENDER)),
            loja_id: int = Depends(loja_da_sessao)):
    return montar_atender(loja_id)

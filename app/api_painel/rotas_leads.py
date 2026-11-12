"""
Rotas de leitura do C2: GET /leads e GET /resultado.

- /leads: dono, gestor e vendedor (x-papeis). O vendedor do link recebe 403.
- /resultado: só dono e gestor. Vendedor e vendedor do link recebem 403.
- A loja vem só da sessão (loja_da_sessao). loja_id no pedido é ignorado.
- Só leitura: não pedem X-CSRF-Token e não definem ator.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from app.api_painel.dependencias import exigir_papel, loja_da_sessao
from app.api_painel.leads import PERIODO_PADRAO, TAMANHO_PADRAO, montar_leads
from app.api_painel.resultado import SEMANA, montar_resultado

QUEM_VE_LEADS = ("dono", "gestor", "vendedor")
QUEM_VE_RESULTADO = ("dono", "gestor")

router = APIRouter()


@router.get("/leads", tags=["Leads"])
def leads(periodo: int = PERIODO_PADRAO, busca: Optional[str] = None,
          etapa: Optional[str] = None, pagina: int = 1, tamanho: int = TAMANHO_PADRAO,
          _sessao: dict = Depends(exigir_papel(*QUEM_VE_LEADS)),
          loja_id: int = Depends(loja_da_sessao)):
    return montar_leads(loja_id, periodo, busca, etapa, pagina, tamanho)


@router.get("/resultado", tags=["Resultado"])
def resultado(visao: str = SEMANA, data: Optional[str] = None,
              _sessao: dict = Depends(exigir_papel(*QUEM_VE_RESULTADO)),
              loja_id: int = Depends(loja_da_sessao)):
    return montar_resultado(loja_id, visao, data)

"""
Q2 (Maratona Painel 2): as fotos ilustrativas da loja de demonstração, pelo painel.

GET /demo/fotos/{arquivo}
- Só dono e gerente (quem vê o Estoque), logados numa loja de demonstração (outra loja: 404).
- Só arquivos da pasta de fotos da demo (app/demo.PASTA_FOTOS), com nome simples
  ("hyundai-hb20-2021-prata.png"). Qualquer outra coisa, inclusive "..", barra ou caminho
  completo, dá 404 sem dizer por quê.
- Não grava nada.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api_painel.dependencias import exigir_papel
from app.api_painel.erros import ErroApi
from app.demo import arquivo_da_foto, e_demo

router = APIRouter(prefix="/demo", tags=["Estoque"])
NAO_ENCONTRADA = "Não encontramos essa foto."


@router.get("/fotos/{arquivo}", response_class=FileResponse,
            responses={200: {"content": {"image/png": {}}, "description": "A foto."}})
def foto_da_demo(arquivo: str, sessao: dict = Depends(exigir_papel("dono", "gestor"))):
    if not e_demo(sessao["loja_id"]):
        raise ErroApi("nao_encontrado", mensagem=NAO_ENCONTRADA)
    caminho = arquivo_da_foto(arquivo)
    if caminho is None:
        raise ErroApi("nao_encontrado", mensagem=NAO_ENCONTRADA)
    return FileResponse(caminho, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

"""
Aplicação FastAPI do painel do cliente (C2 do Plano Mestre).

Separada do webhook (app/api/webhook.py não muda). Roda só no seu computador:
    uvicorn app.api_painel.main:app --host 127.0.0.1 --port 8001
- Prefixo /api/v1.
- /docs, /redoc e /openapi.json desligados: nada fica aberto sem login.
  O C2e exporta o contrato por script (app.openapi()).
- CORS só para a origem do front, na variável PAINEL_ORIGEM (pode ter mais de
  uma, separadas por vírgula). Sem a variável, nenhuma origem é liberada.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api_painel import rotas_acompanhamento, rotas_estoque, rotas_leads
from app.api_painel import erros, logs, rotas_atender, rotas_auth, rotas_conversas
from app.api_painel.dependencias import CABECALHO_CSRF

PREFIXO = "/api/v1"


def origens_do_painel() -> list:
    texto = os.environ.get("PAINEL_ORIGEM", "")
    return [o.strip() for o in texto.split(",") if o.strip() and o.strip() != "*"]


def criar_app() -> FastAPI:
    app = FastAPI(title="Léo — API do painel do cliente", version="1.0.0",
                  docs_url=None, redoc_url=None, openapi_url=None)
    origens = origens_do_painel()
    if origens:
        app.add_middleware(CORSMiddleware, allow_origins=origens, allow_credentials=True,
                           allow_methods=["GET", "POST", "PUT", "DELETE"],
                           allow_headers=["Content-Type", CABECALHO_CSRF])
    erros.instalar(app)
    app.include_router(rotas_auth.router, prefix=PREFIXO)
    app.include_router(rotas_atender.router, prefix=PREFIXO)   # C2b
    app.include_router(rotas_conversas.router, prefix=PREFIXO)   # C2c
    app.include_router(rotas_acompanhamento.router, prefix=PREFIXO)
    app.include_router(rotas_estoque.router, prefix=PREFIXO)
    app.include_router(rotas_leads.router, prefix=PREFIXO)     # C2: Leads e Resultado
    logs.instalar()                                  # D3: log sem o número do cliente
    return app


load_dotenv()
app = criar_app()

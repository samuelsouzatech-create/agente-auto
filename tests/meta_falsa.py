"""
Servidor FALSO da Meta para os testes (I7 do plano mestre; IG3 da Maratona 4).

Um servidor HTTP de verdade (FastAPI + uvicorn numa linha separada, em 127.0.0.1 e porta livre),
com as rotas do Instagram que o Léo usa (formato do IG0):
  POST /<versão>/<id da conta>/messages     direct e resposta privada a comentário
  POST /<versão>/<id do comentário>/replies resposta pública
  GET  /<versão>/<id do post>?fields=caption legenda do post
O Léo fala com ele pelo endereço INSTAGRAM_API_URL. Guarda tudo o que recebeu (pedidos) e confere
o token (Bearer). Nunca sai do computador. O documento 4.0 (seção 6) citado no plano não está no
repositório: este é novo.
"""
from __future__ import annotations

import socket
import threading
import time
from contextlib import contextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class MetaFalsa:
    def __init__(self, legendas: dict | None = None, tokens: set | None = None):
        self.legendas = dict(legendas or {})
        self.tokens = set(tokens or ())
        self.pedidos: list[dict] = []
        self.app = self._montar()

    def _token_ok(self, request: Request) -> bool:
        cab = request.headers.get("authorization", "")
        return not self.tokens or cab.removeprefix("Bearer ") in self.tokens

    def _montar(self) -> FastAPI:
        app = FastAPI()

        @app.post("/{versao}/{alvo}/messages")
        async def mensagens(versao: str, alvo: str, request: Request):
            if not self._token_ok(request):
                return JSONResponse({"error": {"message": "Invalid OAuth access token", "code": 190}}, 400)
            corpo = await request.json()
            mid = f"mid-falso-{len(self.pedidos) + 1}"
            self.pedidos.append({"tipo": "messages", "conta": alvo, "corpo": corpo, "message_id": mid})
            para = corpo.get("recipient", {})
            return {"recipient_id": para.get("id") or f"de-comentario-{para.get('comment_id')}",
                    "message_id": mid}

        @app.post("/{versao}/{comentario}/replies")
        async def respostas(versao: str, comentario: str, request: Request):
            corpo = await request.json()
            self.pedidos.append({"tipo": "replies", "comentario": comentario, "corpo": corpo})
            return {"id": f"resposta-{comentario}"}

        @app.get("/{versao}/{post}")
        async def post(versao: str, post: str, fields: str = ""):
            self.pedidos.append({"tipo": "legenda", "post": post, "fields": fields})
            if post not in self.legendas:
                return JSONResponse({"error": {"message": "Unsupported get request", "code": 100}}, 400)
            return {"id": post, "caption": self.legendas[post]}

        return app

    # o que chegou, por tipo
    def textos_enviados(self) -> list[str]:
        return [p["corpo"]["message"].get("text", "") for p in self.pedidos if p["tipo"] == "messages"]

    def privadas(self) -> list[dict]:
        return [p for p in self.pedidos if p["tipo"] == "messages" and "comment_id" in p["corpo"]["recipient"]]


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def servidor_meta_falsa(legendas: dict | None = None, tokens: set | None = None):
    meta = MetaFalsa(legendas, tokens)
    porta = _porta_livre()
    servidor = uvicorn.Server(uvicorn.Config(meta.app, host="127.0.0.1", port=porta, log_level="warning"))
    linha = threading.Thread(target=servidor.run, daemon=True)
    linha.start()
    for _ in range(100):
        if servidor.started:
            break
        time.sleep(0.05)
    meta.url = f"http://127.0.0.1:{porta}"
    try:
        yield meta
    finally:
        servidor.should_exit = True
        linha.join(timeout=5)

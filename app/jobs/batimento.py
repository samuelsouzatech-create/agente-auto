"""
Sinal de vida do relógio (S9 da Fase 3).

O runner (app/jobs/runner.py) grava no Redis, a cada giro, a hora (UTC) em que
girou. Ao parar (Ctrl+C ou fim do --uma-vez), grava "parado" (decisão 1A):
assim a Visão geral fica vermelha na hora, sem esperar 2 minutos.
Com --sem-trava o runner não grava nada (a Visão geral fica vermelha).

Gravar nunca derruba o runner: erro vira só um aviso no terminal.
Ler pode dar erro (Redis fora): quem lê decide o que mostrar.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

CHAVE = "saude:relogio"
GIRANDO = "girando"
PARADO = "parado"
FORMATO = "%Y-%m-%d %H:%M:%S"


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _gravar(cliente, estado: str, agora: datetime | None = None) -> bool:
    quando = _utc(agora or datetime.now(timezone.utc)).strftime(FORMATO)
    try:
        cliente.set(CHAVE, json.dumps({"estado": estado, "quando": quando}))
        return True
    except Exception as erro:
        print(f"[Runner] Aviso: não consegui gravar o sinal do relógio ({type(erro).__name__}).")
        return False


def marcar_giro(cliente, agora: datetime | None = None) -> bool:
    return _gravar(cliente, GIRANDO, agora)


def marcar_parado(cliente, agora: datetime | None = None) -> bool:
    return _gravar(cliente, PARADO, agora)


def ler(cliente) -> dict | None:
    """{"estado": "girando"/"parado", "quando": datetime UTC} ou None (nunca gravado).
    Erro do Redis sobe para quem chamou."""
    texto = cliente.get(CHAVE)
    if not texto:
        return None
    try:
        dados = json.loads(texto)
        quando = datetime.strptime(dados["quando"], FORMATO).replace(tzinfo=timezone.utc)
        return {"estado": dados.get("estado"), "quando": quando}
    except (TypeError, ValueError, KeyError):
        return None

"""
Verificação de saúde das peças no Docker (DK1). O docker-compose.yml chama:

    python docker/saude.py http <endereço>     a peça responde no endereço (qualquer código < 500)
    python docker/saude.py relogio             o relógio girou nos últimos 3 minutos (sinal no Redis)
    python docker/saude.py redis               o Redis responde (bot do Telegram, que não tem porta)

Sai com 0 (saudável) ou 1 (doente). Nunca mostra senha nem endereço com senha.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

LIMITE_RELOGIO_S = 180


def http(endereco: str) -> bool:
    try:
        with urllib.request.urlopen(endereco, timeout=4) as resposta:
            return resposta.status < 500
    except urllib.error.HTTPError as erro:       # 401/404 = a peça está de pé e respondeu
        return erro.code < 500
    except Exception:
        return False


def _redis():
    import redis
    return redis.Redis.from_url(os.environ.get("REDIS_URL", ""), decode_responses=True,
                                socket_timeout=3, socket_connect_timeout=3)


def redis_responde() -> bool:
    try:
        return bool(_redis().ping())
    except Exception:
        return False


def relogio() -> bool:
    try:
        texto = _redis().get("saude:relogio")
    except Exception:
        return False
    if not texto:
        return False
    sinal = json.loads(texto)
    if sinal.get("estado") != "girando":
        return False
    quando = datetime.strptime(sinal["quando"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - quando).total_seconds() <= LIMITE_RELOGIO_S


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "http":
        return 0 if http(argv[1]) else 1
    if argv[:1] == ["relogio"]:
        return 0 if relogio() else 1
    if argv[:1] == ["redis"]:
        return 0 if redis_responde() else 1
    print("uso: saude.py http <endereço> | relogio | redis")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

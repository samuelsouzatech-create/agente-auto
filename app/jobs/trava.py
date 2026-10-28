"""
Trava do runner no Redis (revisão da Etapa 1).

Só UM runner por vez em todo o sistema, mesmo que alguém abra dois
terminais ou dois servidores. A trava expira sozinha (TTL) se o runner
morrer, e é renovada a cada ciclo. Só o dono renova ou libera (Lua).
"""
from __future__ import annotations

import uuid

CHAVE = "trava:runner"
TTL_S = 90

_RENOVAR = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("expire", KEYS[1], ARGV[2])
else
    return 0
end
"""
_LIBERAR = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


def cliente_redis_sincrono():
    import redis
    from app.redis_cliente import REDIS_URL
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


class TravaRunner:
    def __init__(self, cliente, chave: str = CHAVE, ttl: int = TTL_S):
        self.cliente, self.chave, self.ttl = cliente, chave, int(ttl)
        self.token = uuid.uuid4().hex

    def adquirir(self) -> bool:
        return bool(self.cliente.set(self.chave, self.token, nx=True, ex=self.ttl))

    def renovar(self) -> bool:
        return bool(self.cliente.eval(_RENOVAR, 1, self.chave, self.token, self.ttl))

    def liberar(self) -> None:
        try:
            self.cliente.eval(_LIBERAR, 1, self.chave, self.token)
        except Exception as erro:
            print(f"[Runner] Aviso: não consegui liberar a trava ({type(erro).__name__}).")

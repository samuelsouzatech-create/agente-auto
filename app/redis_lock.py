"""
Lock por lead E por loja (Fase 2, Bloco 5 + Etapa 1, Bloco 3).

Uma execução por vez para o mesmo cliente NA MESMA LOJA. Chave: lock:{loja}:{lead}.
SET NX EX + token único; liberação atômica via Lua (só o dono apaga).
"""
import uuid
import asyncio

from app.redis_cliente import redis_cliente
from app.chaves import chave_redis, LOJA_PADRAO

TTL_LOCK = 60

_LIBERAR_SE_DONO = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


async def adquirir_lock(lead_id: str, *, loja_id: int = LOJA_PADRAO) -> str | None:
    """Tenta UMA vez. Devolve o token se conseguiu, senão None."""
    token = uuid.uuid4().hex
    criou = await redis_cliente.set(chave_redis("lock", loja_id, lead_id), token, nx=True, ex=TTL_LOCK)
    return token if criou else None


async def adquirir_lock_esperando(lead_id: str, espera_max: float = 90,
                                  intervalo: float = 0.5, *,
                                  loja_id: int = LOJA_PADRAO) -> str | None:
    """Espera a vez em vez de desistir (não perde a 2ª mensagem do cliente)."""
    chave = chave_redis("lock", loja_id, lead_id)
    token = uuid.uuid4().hex
    tempo_gasto = 0.0
    while True:
        if await redis_cliente.set(chave, token, nx=True, ex=TTL_LOCK):
            return token
        if tempo_gasto >= espera_max:
            return None
        await asyncio.sleep(intervalo)
        tempo_gasto += intervalo


async def liberar_lock(lead_id: str, token: str | None = None, *,
                       loja_id: int = LOJA_PADRAO) -> None:
    """Com token, só apaga se o lock ainda for nosso. Nunca engole erro em silêncio."""
    chave = chave_redis("lock", loja_id, lead_id)
    if token is None:
        await redis_cliente.delete(chave)
        return
    try:
        await redis_cliente.eval(_LIBERAR_SE_DONO, 1, chave, token)
    except Exception as erro:
        print(f"[Lock] ERRO ao liberar o lock de {chave}: {erro!r}")

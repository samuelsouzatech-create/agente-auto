"""
Atraso adaptativo por lead E por loja (humanização). Chave: visto:{loja}:{lead}.
Cliente ativo (falou há pouco) -> 1-3 s. Sumiu e voltou -> 10-30 s.
A loja é obrigatória.
"""
import time
import random

from app.redis_cliente import redis_cliente
from app.chaves import chave_redis

LIMITE_ATIVO_S = 120
ATRASO_ATIVO = (1, 3)
ATRASO_AUSENTE = (10, 30)
TTL_VISTO = 6 * 60 * 60


async def calcular_atraso(lead_id: str, *, loja_id: int | None = None) -> float:
    chave_visto = chave_redis("visto", loja_id, lead_id)
    agora = time.time()
    visto_antes = await redis_cliente.get(chave_visto)
    await redis_cliente.set(chave_visto, agora, ex=TTL_VISTO)

    if visto_antes is None or agora - float(visto_antes) <= LIMITE_ATIVO_S:
        return random.uniform(*ATRASO_ATIVO)
    return random.uniform(*ATRASO_AUSENTE)

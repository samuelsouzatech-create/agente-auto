"""
Debounce por lead E por loja (Fase 2, Bloco 5 + Etapa 1, Bloco 3).

Acumula a rajada de mensagens do cliente num buffer no Redis e só processa
depois de alguns segundos de silêncio. Chaves: buffer:{loja}:{lead} e
ultima_hora:{loja}:{lead}. A loja é obrigatória.
"""
import time
import asyncio

from app.redis_cliente import redis_cliente
from app.chaves import chave_redis

DEBOUNCE_SEGUNDOS = 8
TTL_BUFFER = 120


async def acumular_e_esperar(lead_id: str, texto: str, loja_id: int | None = None) -> str | None:
    """Devolve o texto juntado se ESTA execução for a dona da rajada;
    None se chegou mensagem mais nova (ela cuidará)."""
    chave_buffer = chave_redis("buffer", loja_id, lead_id)   # sem loja: erro
    chave_hora = chave_redis("ultima_hora", loja_id, lead_id)
    hora_desta = time.time()

    await redis_cliente.rpush(chave_buffer, texto)
    await redis_cliente.expire(chave_buffer, TTL_BUFFER)
    await redis_cliente.set(chave_hora, hora_desta, ex=TTL_BUFFER)

    await asyncio.sleep(DEBOUNCE_SEGUNDOS)

    hora_atual = await redis_cliente.get(chave_hora)
    if hora_atual is None or float(hora_atual) != hora_desta:
        return None

    partes = await redis_cliente.lrange(chave_buffer, 0, -1)
    await redis_cliente.delete(chave_buffer)
    await redis_cliente.delete(chave_hora)
    return " ".join(partes)

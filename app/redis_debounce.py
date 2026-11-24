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

    # PG3 (teste de carga): ler e esvaziar o buffer num passo só (transação do Redis). Antes eram
    # passos separados e, sob carga, a mensagem que chegava no meio deles se perdia. A hora NÃO
    # é apagada: ela expira sozinha (TTL) e a mensagem seguinte sempre escreve a dela por cima.
    # Apagar a hora aqui apagava a hora da mensagem que acabou de chegar, e ela era esquecida.
    async with redis_cliente.pipeline(transaction=True) as passo:
        passo.lrange(chave_buffer, 0, -1)
        passo.delete(chave_buffer)
        partes, _ = await passo.execute()
    texto_juntado = " ".join(p for p in partes if p and p.strip())
    # PG3: buffer vazio (ele expirou ou se perdeu) não vira um turno com mensagem vazia.
    return texto_juntado or None

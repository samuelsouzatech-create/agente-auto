"""
Conexão com o Redis (Bloco 5).

O Redis é usado para:
- debounce: esperar o cliente terminar a rajada de mensagens antes de responder;
- lock por lead: impedir duas execuções do agente para o mesmo cliente ao mesmo tempo;
- (futuro) deduplicação persistente, no lugar da lista em memória do Bloco 4.

A URL vem do .env. No desenvolvimento local, aponta para o container Docker.
"""
import os
import redis.asyncio as redis

# URL de conexão. Local (Docker) por padrão; em produção vem do .env.
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Cliente assíncrono, compartilhado pela aplicação.
# decode_responses=True faz o Redis devolver str em vez de bytes (mais simples).
redis_cliente = redis.from_url(REDIS_URL, decode_responses=True)


async def testar_conexao() -> bool:
    """Faz um PING no Redis. Retorna True se respondeu, False se falhou."""
    try:
        return await redis_cliente.ping()
    except Exception as erro:
        print(f"[Redis] Falha na conexão: {erro}")
        return False

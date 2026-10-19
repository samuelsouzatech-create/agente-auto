"""
Lock por lead (Bloco 5).

Garante que só UMA execução do agente rode por vez para o mesmo lead.
Leads diferentes continuam em paralelo (o lock é por lead, não global).

Usa o padrão SET NX EX do Redis:
- NX: só cria a chave se ela ainda não existir (quem criar "ganha" o lock);
- EX: a chave expira sozinha depois de N segundos (trava de segurança, para
  o lock nunca ficar preso se algo travar no meio).
"""
from app.redis_cliente import redis_cliente

# Tempo máximo que um lock pode durar (segundos). Se a execução travar,
# o lock some sozinho depois disso e não deixa o lead preso para sempre.
TTL_LOCK = 60


async def adquirir_lock(lead_id: str) -> bool:
    """Tenta pegar o lock do lead. Retorna True se conseguiu, False se já
    existe um lock ativo (outra execução está rodando para esse lead)."""
    chave = f"lock:{lead_id}"
    # set(..., nx=True, ex=TTL_LOCK) devolve True só se a chave foi criada agora.
    criou = await redis_cliente.set(chave, "1", nx=True, ex=TTL_LOCK)
    return bool(criou)


async def liberar_lock(lead_id: str) -> None:
    """Libera o lock do lead ao terminar a execução."""
    chave = f"lock:{lead_id}"
    await redis_cliente.delete(chave)

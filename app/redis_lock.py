"""
Lock por lead (Bloco 5).

Garante que só UMA execução do agente rode por vez para o mesmo lead.
Leads diferentes continuam em paralelo (o lock é por lead, não global).

Usa o padrão SET NX EX do Redis:
- NX: só cria a chave se ela ainda não existir (quem criar "ganha" o lock);
- EX: a chave expira sozinha depois de N segundos (trava de segurança, para
  o lock nunca ficar preso se algo travar no meio).

Cada execução grava um TOKEN único no lock. Na hora de liberar, só apaga se
o token for o seu — assim uma execução nunca apaga o lock de outra (que pode
ter pego a vez depois que o TTL da primeira expirou).
"""
import uuid
import asyncio

from app.redis_cliente import redis_cliente

# Tempo máximo que um lock pode durar (segundos). Se a execução travar,
# o lock some sozinho depois disso e não deixa o lead preso para sempre.
TTL_LOCK = 60

# Script Lua: só apaga a chave se o valor dela for o token esperado.
# Roda no Redis de forma atômica (ninguém mexe no meio).
_LIBERAR_SE_DONO = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


async def adquirir_lock(lead_id: str) -> str | None:
    """Tenta pegar o lock do lead UMA vez. Retorna o token (str) se conseguiu,
    ou None se já existe um lock ativo. (Mantido para compatibilidade; o
    caminho normal agora é adquirir_lock_esperando.)"""
    chave = f"lock:{lead_id}"
    token = uuid.uuid4().hex
    criou = await redis_cliente.set(chave, token, nx=True, ex=TTL_LOCK)
    return token if criou else None


async def adquirir_lock_esperando(lead_id: str, espera_max: float = 90,
                                  intervalo: float = 0.5) -> str | None:
    """Tenta pegar o lock e, se estiver ocupado, ESPERA a vez em vez de
    desistir. Isso garante que uma segunda mensagem do mesmo cliente
    (que chegou enquanto a primeira ainda respondia) seja processada em
    seguida, sem ser descartada.

    Retorna o token se conseguiu dentro de espera_max segundos, senão None.
    """
    chave = f"lock:{lead_id}"
    token = uuid.uuid4().hex
    tempo_gasto = 0.0
    while True:
        criou = await redis_cliente.set(chave, token, nx=True, ex=TTL_LOCK)
        if criou:
            return token
        if tempo_gasto >= espera_max:
            return None
        await asyncio.sleep(intervalo)
        tempo_gasto += intervalo


async def liberar_lock(lead_id: str, token: str | None = None) -> None:
    """Libera o lock do lead ao terminar a execução.

    Se vier o token, só apaga o lock se ele ainda for o nosso (não apaga
    lock de outra execução que possa ter pego a vez). Sem token, apaga
    direto (comportamento antigo, para não quebrar chamadas existentes)."""
    chave = f"lock:{lead_id}"
    if token is None:
        await redis_cliente.delete(chave)
        return
    try:
        await redis_cliente.eval(_LIBERAR_SE_DONO, 1, chave, token)
    except Exception:
        # Se o eval falhar por qualquer motivo, não derruba o fluxo.
        pass

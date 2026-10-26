"""Deduplicação de mensagens no Redis (SET NX EX), por canal + id da mensagem.

Sobrevive a reinícios do servidor. Se o Redis estiver fora do ar, cai para
uma memória local (não para o atendimento, só perde a proteção entre reinícios).
"""
import time

import app.redis_cliente as rc   # lido na hora da chamada (os testes trocam por um falso)
from app.chaves import chave_dedup

TTL_DEDUP = 24 * 60 * 60   # a Meta reenvia por algumas horas; 24h cobre com folga
_LIMITE_LOCAL = 5000
_vistos_local: dict[str, float] = {}


def _ja_vista_local(chave: str) -> bool:
    agora = time.time()
    visto = _vistos_local.get(chave)
    if visto is not None and agora - visto < TTL_DEDUP:
        return True
    _vistos_local[chave] = agora
    if len(_vistos_local) > _LIMITE_LOCAL:
        for antiga in sorted(_vistos_local, key=_vistos_local.get)[: _LIMITE_LOCAL // 2]:
            _vistos_local.pop(antiga, None)
    return False


async def ja_processada(canal: str, id_mensagem: str) -> bool:
    """True se esta mensagem já foi vista (duplicata). Se for nova, registra."""
    if not id_mensagem:
        return False
    chave = chave_dedup(canal, id_mensagem)
    try:
        criou = await rc.redis_cliente.set(chave, "1", nx=True, ex=TTL_DEDUP)
        return not criou
    except Exception as erro:
        print(f"[Dedup] Redis indisponível ({erro!r}). Usando memória local.")
        return _ja_vista_local(chave)

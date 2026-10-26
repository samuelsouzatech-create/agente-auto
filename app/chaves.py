"""Nomes padronizados de chaves do Redis e da memória (item 1.5).

Tudo que é "por cliente" leva também a loja no nome, para o mesmo número
falando com duas lojas nunca misturar trava, buffer ou memória.
"""
LOJA_PADRAO = 1


def _loja(loja_id) -> int:
    return int(loja_id or LOJA_PADRAO)


def chave_redis(prefixo: str, loja_id, lead_id: str) -> str:
    """Ex.: chave_redis("lock", 2, "5581") -> "lock:2:5581"."""
    return f"{prefixo}:{_loja(loja_id)}:{lead_id}"


def thread_id(loja_id, canal: str, lead_id: str) -> str:
    """Gaveta de memória do LangGraph. Ex.: "2:whatsapp:5581"."""
    return f"{_loja(loja_id)}:{canal}:{lead_id}"


def chave_dedup(canal: str, id_mensagem: str) -> str:
    return f"dedup:{canal}:{id_mensagem}"

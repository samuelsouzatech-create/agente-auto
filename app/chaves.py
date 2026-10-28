"""Nomes padronizados de chaves do Redis e da memória (item 1.5).

Tudo que é "por cliente" leva a loja no nome. Revisão da Etapa 1: a loja é
OBRIGATÓRIA. Se algum caminho esquecer de passar, dá erro em vez de cair
na loja 1 em silêncio.
"""
LOJA_PADRAO = 1   # SÓ para o modo de transição do resolver_loja (app/canais.py)


class LojaNaoInformada(ValueError):
    """Algum caminho do código não disse de qual loja é a conversa."""


def exigir_loja(loja_id) -> int:
    if loja_id is None or isinstance(loja_id, bool):
        raise LojaNaoInformada("loja_id não informado (nada vai para a loja 1 por engano).")
    try:
        numero = int(loja_id)
    except (TypeError, ValueError):
        raise LojaNaoInformada(f"loja_id inválido: {loja_id!r}") from None
    if numero <= 0:
        raise LojaNaoInformada(f"loja_id inválido: {loja_id!r}")
    return numero


def chave_redis(prefixo: str, loja_id, lead_id: str) -> str:
    """Ex.: chave_redis("lock", 2, "5581") -> "lock:2:5581"."""
    return f"{prefixo}:{exigir_loja(loja_id)}:{lead_id}"


def thread_id(loja_id, canal: str, lead_id: str) -> str:
    """Gaveta de memória do LangGraph. Ex.: "2:whatsapp:5581"."""
    return f"{exigir_loja(loja_id)}:{canal}:{lead_id}"


def chave_dedup(canal: str, id_mensagem: str) -> str:
    return f"dedup:{canal}:{id_mensagem}"

"""
Log do servidor sem o número do cliente (decisão D3).

O endereço da conversa tem o lead (ex.: /conversas/5581999990001). O log de
acesso do uvicorn mostra /conversas/***. Só muda o texto do log; a rota
continua recebendo o lead normalmente.
"""
from __future__ import annotations

import logging
import re

_CONVERSA = re.compile(r"(/conversas/)[^/?#\s]+")
LOGGERS = ("uvicorn.access",)


def esconder(texto: str) -> str:
    return _CONVERSA.sub(r"\1***", texto)


class EsconderConversa(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and record.args:
            record.args = tuple(esconder(a) if isinstance(a, str) else a for a in record.args)
        if isinstance(record.msg, str):
            record.msg = esconder(record.msg)
        return True


_FILTRO = EsconderConversa()


def instalar() -> None:
    for nome in LOGGERS:
        logger = logging.getLogger(nome)
        if _FILTRO not in logger.filters:
            logger.addFilter(_FILTRO)

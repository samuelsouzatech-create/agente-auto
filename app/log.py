"""
Registro técnico do servidor (Maratona 3, N3 / revisão #20, parte 1).

    from app.log import logger
    log = logger("webhook")
    log.info("...")            # tela + logs/leo.log
    log.exception("...")       # dentro de um except: guarda o erro com o rastro

Arquivo: logs/leo.log (pasta de app.logs.PASTA_LOGS), girando em 5 arquivos de 5 MB.
A tela continua mostrando as mesmas linhas de antes (o que era print). Texto do cliente nunca:
quem chama já passa id_no_console/texto_no_console (app/console.py).
O simulador e a bancada continuam com print (a saída deles não muda).
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

ARQUIVO = "leo.log"
TAMANHO_MAXIMO = 5 * 1024 * 1024
COPIAS = 5
FORMATO_ARQUIVO = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


class _Tela(logging.StreamHandler):
    """Escreve no sys.stdout ATUAL (o pytest troca o stdout; o print fazia o mesmo)."""

    def __init__(self):
        super().__init__(sys.stdout)

    def emit(self, registro):
        self.stream = sys.stdout
        super().emit(registro)


class _ArquivoGirando(logging.Handler):
    """Abre logs/leo.log só na primeira linha e segue a pasta atual de app.logs.PASTA_LOGS."""

    def __init__(self):
        super().__init__()
        self._interno: RotatingFileHandler | None = None
        self._caminho = ""

    def _arquivo(self) -> RotatingFileHandler | None:
        from app import logs
        caminho = os.path.join(logs.PASTA_LOGS, ARQUIVO)
        if self._interno is None or caminho != self._caminho:
            if self._interno is not None:
                self._interno.close()
            try:
                os.makedirs(logs.PASTA_LOGS, exist_ok=True)
                self._interno = RotatingFileHandler(caminho, maxBytes=TAMANHO_MAXIMO, backupCount=COPIAS,
                                                    encoding="utf-8")
                self._interno.setFormatter(logging.Formatter(FORMATO_ARQUIVO))
                self._caminho = caminho
            except OSError:
                self._interno = None
        return self._interno

    def emit(self, registro):
        arquivo = self._arquivo()
        if arquivo is not None:
            arquivo.emit(registro)

    def close(self):
        if self._interno is not None:
            self._interno.close()
        super().close()


def _configurar() -> logging.Logger:
    raiz = logging.getLogger("leo")
    if not getattr(raiz, "_leo_pronto", False):
        tela = _Tela()
        tela.setFormatter(logging.Formatter("%(message)s"))      # na tela, igual ao print de antes
        raiz.addHandler(tela)
        raiz.addHandler(_ArquivoGirando())
        raiz.setLevel(logging.INFO)
        raiz.propagate = False
        raiz._leo_pronto = True
    return raiz


def logger(nome: str) -> logging.Logger:
    _configurar()
    return logging.getLogger(f"leo.{nome}")

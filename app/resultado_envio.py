"""Resultado de um envio (Etapa 2, Bloco 1).

Fica fora de app/channels para não criar import circular com app/api.
O job precisa saber POR QUE a Meta recusou, e não só que recusou.
"""
from dataclasses import dataclass

# 131047: "re-engagement message", janela de 24h vencida.
# Fonte: terceiros. Conferir na documentação oficial antes do envio real.
CODIGOS_JANELA_FECHADA = frozenset({131047})


@dataclass(frozen=True)
class ResultadoEnvio:
    ok: bool
    id_externo: str = ""
    codigo_erro: int | None = None
    detalhe: str = ""

    @property
    def janela_fechada(self) -> bool:
        return self.codigo_erro in CODIGOS_JANELA_FECHADA

"""
Modo de envio por loja (Etapa 2, Bloco 9 - item 2.7 "botão de modo de teste").

Envio real precisa de DUAS chaves ligadas:
  1. a geral do servidor (.env): REMARKETING_ENVIO_REAL, POS_VENDA_ENVIO_REAL, REATIVACAO_ENVIO_REAL
  2. a da loja (Plano e limites > Envios): envio_real.remarketing / .pos_venda / .reativacao
Loja nova começa em teste. Só o operador muda (fica no histórico).

'forcado' (True/False) passa por cima das duas: usado pelos testes e pela
linha de comando, que sempre simula. O runner nunca força.
"""
from __future__ import annotations

import os

from app.lojas import TIPOS_ENVIO, Loja

VARIAVEIS = {"remarketing": "REMARKETING_ENVIO_REAL",
             "pos_venda": "POS_VENDA_ENVIO_REAL",
             "reativacao": "REATIVACAO_ENVIO_REAL"}
_SIM = ("1", "true", "sim", "yes")


def _conferir(tipo: str) -> None:
    if tipo not in TIPOS_ENVIO:
        raise ValueError(f"tipo de envio '{tipo}' não existe (válidos: {', '.join(TIPOS_ENVIO)})")


def chave_geral_ligada(tipo: str) -> bool:
    _conferir(tipo)
    return (os.getenv(VARIAVEIS[tipo]) or "").strip().lower() in _SIM


def loja_em_real(loja: Loja, tipo: str) -> bool:
    _conferir(tipo)
    return bool(loja.get(f"envio_real.{tipo}", False))


def real_para(loja: Loja, tipo: str, forcado: bool | None = None) -> bool:
    """Esta loja manda de verdade este tipo de mensagem agora?"""
    _conferir(tipo)
    if forcado is not None:
        return bool(forcado)
    return chave_geral_ligada(tipo) and loja_em_real(loja, tipo)


def situacao(loja: Loja, tipo: str) -> str:
    """'real', 'teste_loja' (servidor liberado, loja em teste),
    'teste_servidor' (loja liberada, servidor em teste) ou 'teste'."""
    geral, da_loja = chave_geral_ligada(tipo), loja_em_real(loja, tipo)
    if geral and da_loja:
        return "real"
    if geral:
        return "teste_loja"
    if da_loja:
        return "teste_servidor"
    return "teste"

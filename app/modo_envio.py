"""
Modo de envio por loja (Etapa 2, Bloco 9 - item 2.7; P7 do Plano Mestre).

Envio real precisa de TRÊS travas abertas:
  1. a geral do servidor (.env): REMARKETING_ENVIO_REAL, POS_VENDA_ENVIO_REAL, REATIVACAO_ENVIO_REAL
  2. a da loja (Plano e limites > Envios): envio_real.remarketing / .pos_venda / .reativacao
  3. P7: a loja está 'no_ar' (app/estado_loja.py). Loja em teste nunca manda
     nada proativo de verdade, mesmo com as duas chaves ligadas.
Loja nova começa em teste. Só o operador muda (fica no histórico).

'forcado' (True/False) passa por cima das DUAS chaves: usado pelos testes e
pela linha de comando, que sempre simula. O runner nunca força.
P7: 'forcado' NÃO passa por cima da loja em teste (forcado=True numa loja
em teste continua simulando).
"""
from __future__ import annotations

import os

from app.estado_loja import esta_no_ar
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
    if not esta_no_ar(loja.id):
        return False
    if forcado is not None:
        return bool(forcado)
    return chave_geral_ligada(tipo) and loja_em_real(loja, tipo)


def situacao(loja: Loja, tipo: str) -> str:
    """'real', 'loja_em_teste' (as duas chaves ligadas, mas a loja ainda está
    em teste: P7), 'teste_loja' (servidor liberado, chave da loja desligada),
    'teste_servidor' (loja liberada, servidor em teste) ou 'teste'."""
    geral, da_loja = chave_geral_ligada(tipo), loja_em_real(loja, tipo)
    if geral and da_loja:
        return "real" if esta_no_ar(loja.id) else "loja_em_teste"
    if geral:
        return "teste_loja"
    if da_loja:
        return "teste_servidor"
    return "teste"

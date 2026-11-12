"""
Pedaços prontos que várias rotas usam (C2b).

- horario(loja, valor): o objeto {iso, texto} do contrato, no fuso da loja.
  Vazio ou inválido: None. Quem converte é app/apresentacao.py (P3).
"""
from __future__ import annotations

from app.apresentacao import horario_iso_local, horario_para_tela


def horario(loja, valor, agora=None):
    iso = horario_iso_local(loja, valor)
    if iso is None:
        return None
    return {"iso": iso, "texto": horario_para_tela(loja, valor, agora=agora)}

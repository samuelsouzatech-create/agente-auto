"""
Registro das ações relevantes (P6 do Plano Mestre): quem fez o quê, quando,
antes e depois.

registrar() grava UMA linha em registro_acoes. Quem fez vem do ator
(app/ator.py), nunca de um parâmetro: sem ator, a escrita falha.

Atomicidade: a função que faz a ação passa a PRÓPRIA conexão em 'conexao'
e só dá commit depois do registrar(). Erro no meio = nem a ação nem o
registro ficam. Sem 'conexao', o registro abre e fecha a dele (para eventos
soltos, como mensagem de canal sem cadastro).

loja_id vazio (None) só para eventos sem loja. Ator de uma loja não grava
na outra. Horário em UTC, como todo o banco; a tela converte para o fuso.
"""
from __future__ import annotations

import json
import re

from banco import conectar
from app.ator import AtorInvalido, exigir_ator
from app.chaves import exigir_loja
from app.relogio import agora_utc, para_banco

MAX_ALVO = 120
_ACAO_VALIDA = re.compile(r"^[a-z][a-z0-9_]{1,59}$")
_SQL = ("INSERT INTO registro_acoes (quando, loja_id, pessoa, papel, acao, alvo, "
        "antes, depois, origem) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")


class RegistroInvalido(ValueError):
    pass


def _json(valor):
    if valor is None:
        return None
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, default=str)


def registrar(acao, loja_id, antes, depois, conexao=None, alvo=None, agora=None) -> int:
    """Grava a ação. Devolve o id da linha. Com 'conexao', NÃO dá commit."""
    if not isinstance(acao, str) or not _ACAO_VALIDA.match(acao):
        raise RegistroInvalido(f"Nome de ação inválido: {acao!r} (use minúsculas e '_').")
    loja = None if loja_id is None else exigir_loja(loja_id)
    ator = exigir_ator()
    if ator.loja_id is not None and ator.loja_id != loja:
        raise AtorInvalido("Quem está agindo é de outra loja.")
    texto_alvo = None if alvo is None else (str(alvo).strip()[:MAX_ALVO] or None)
    dados = (para_banco(agora or agora_utc()), loja, ator.pessoa, ator.papel, acao,
             texto_alvo, _json(antes), _json(depois), ator.origem)
    if conexao is not None:
        return conexao.execute(_SQL, dados).lastrowid
    propria = conectar()
    try:
        novo_id = propria.execute(_SQL, dados).lastrowid
        propria.commit()
    finally:
        propria.close()
    return novo_id

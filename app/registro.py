"""
Registro das ações relevantes (P6 do Plano Mestre): quem fez o quê, quando,
antes e depois.

registrar() grava UMA linha em registro_acoes. Quem fez vem do ator
(app/ator.py), nunca de um parâmetro: sem ator, a escrita falha.

Atomicidade: a função que faz a ação passa a PRÓPRIA conexão em 'conexao'
e só dá commit depois do registrar(). Erro no meio = nem a ação nem o
registro ficam. Sem 'conexao', o registro abre e fecha a dele (para eventos
soltos, como mensagem de canal sem cadastro).

loja_id vazio (None) só para eventos sem loja. Ator de uma loja não age na
outra. Horário em UTC, como todo o banco; a tela converte para o fuso.
"""
from __future__ import annotations

import json
import re

from banco import conectar
from app.ator import Ator, AtorInvalido, exigir_ator
from app.chaves import exigir_loja
from app.relogio import agora_utc, para_banco

MAX_ALVO = 120
_ACAO_VALIDA = re.compile(r"^[a-z][a-z0-9_]{1,59}$")
_SQL = ("INSERT INTO registro_acoes (quando, loja_id, pessoa, papel, acao, alvo, "
        "antes, depois, origem) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")

# Ações relevantes (P6): chave = ação, valor = função que a faz.
# tests/test_p6b_acoes.py percorre esta lista: toda ação aqui precisa deixar
# rastro com quem e quando. Ação nova entra aqui E ganha cenário no teste.
ACOES_RELEVANTES = {
    "pausar_envios": "app.pausa.pausar",
    "retomar_envios": "app.pausa.retomar",
    "bloquear_envio": "app.bloqueios.bloquear",
    "desfazer_bloqueio": "app.bloqueios.desfazer",
    "registrar_venda": "app.vendas.registrar_venda",
    "importar_base": "app.importacao.importar",
    "desfazer_importacao": "app.importacao.desfazer_importacao",
    "montar_fila_reativacao": "app.reativacao.montar_fila",
    "cancelar_fila_reativacao": "app.reativacao.cancelar_fila",
    # P6c
    "assumir_atendimento": "app.handoff.assumir_handoff",
    "assumir_conversa": "app.handoff.assumir_conversa",
    "devolver_ao_agente": "app.handoff.devolver_ao_agente",
    "salvar_configuracao": "app.lojas.salvar_config", "colocar_no_ar": "app.estado_loja.colocar_no_ar",
}

# Ações que já tinham histórico próprio (quem, quando, na mesma transação).
# NÃO gravam de novo em registro_acoes, para não aparecer duas vezes.
# A leitura unificada (P6d) junta essas tabelas com registro_acoes.
HISTORICO_PROPRIO = {
    "pausar_envios": "pausas_envio",
    "retomar_envios": "pausas_envio",
    "salvar_configuracao": "config_historico",
}

# Eventos de SISTEMA (sem pessoa): gravam com ator de sistema e nunca
# derrubam quem chamou. Não entram em ACOES_RELEVANTES (lá, sem ator falha).
EVENTOS_DE_SISTEMA = {
    "mensagem_canal_sem_cadastro": "app.logs.registrar_canal_desconhecido", "mensagem_recusada_loja_em_teste": "app.core.turno.porta_fechada",
}


class RegistroInvalido(ValueError):
    pass


def _json(valor):
    if valor is None:
        return None
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, default=str)


def conferir_ator(loja_id) -> Ator:
    """Quem está agindo, já conferido: existe (senão SemAtor) e, se é de uma
    loja, só age nela (senão AtorInvalido). loja_id None = evento sem loja."""
    loja = None if loja_id is None else exigir_loja(loja_id)
    ator = exigir_ator()
    if ator.loja_id is not None and ator.loja_id != loja:
        raise AtorInvalido("Quem está agindo é de outra loja.")
    return ator


def registrar(acao, loja_id, antes, depois, conexao=None, alvo=None, agora=None) -> int:
    """Grava a ação. Devolve o id da linha. Com 'conexao', NÃO dá commit."""
    if not isinstance(acao, str) or not _ACAO_VALIDA.match(acao):
        raise RegistroInvalido(f"Nome de ação inválido: {acao!r} (use minúsculas e '_').")
    loja = None if loja_id is None else exigir_loja(loja_id)
    ator = conferir_ator(loja)
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

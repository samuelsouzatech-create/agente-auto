"""
Envio das fotos do estoque ao cliente, com a TRAVA da foto falhada (Maratona Fotos, F1).

Ordem: primeiro as fotos, depois o texto. Assim o código sabe, antes de mandar o texto, se
alguma foto não chegou. Se QUALQUER foto falhar:
  - o texto não pode dizer que enviou: toda frase que fala de foto/imagem sai e entra
    FRASE_FOTO_FALHOU ("Vou pedir para a equipe te mandar as fotos.");
  - abre (ou completa) o chamado com o motivo, para a equipe mandar as fotos;
  - a mensagem do Léo gravada no histórico é corrigida para o texto que realmente saiu.
A promessa de contato só sai junto com o chamado aberto (regra do CLAUDE.md).

Quem chama passa duas funções: enviar_foto(ref) -> bool e enviar_texto(texto) -> None.
Cada canal decide COMO manda a foto (Telegram: os bytes do depósito; WhatsApp: só endereço
https público, que só a tomada nuvem tem). Exceção ao enviar conta como falha.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Awaitable, Callable

from banco import conectar

FRASE_FOTO_FALHOU = "Vou pedir para a equipe te mandar as fotos."
MOTIVO_CHAMADO = "As fotos do carro não chegaram ao cliente ({falhas} de {total}). Mande as fotos por aqui."
RESUMO_CHAMADO = "O envio automático das fotos do estoque falhou. O cliente pediu as fotos."
_FALA_DE_FOTO = re.compile(r"\b(fotos?|imagens?|foto\w*)\b")
_log = logging.getLogger("leo.envio_fotos")


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


def corrigir_texto(texto: str) -> str:
    """Tira toda frase que fala de foto (mantendo as linhas e a formatação do resto) e termina
    com FRASE_FOTO_FALHOU num parágrafo próprio."""
    linhas = []
    for linha in str(texto or "").split("\n"):
        if not linha.strip():
            linhas.append("")
            continue
        frases = re.split(r"(?<=[.!?])\s+", linha.strip())
        ficam = [f for f in frases if f and not _FALA_DE_FOTO.search(_sem_acento(f))]
        if ficam:
            linhas.append(" ".join(ficam))
    corpo = re.sub(r"\n{3,}", "\n\n", "\n".join(linhas)).strip()
    return f"{corpo}\n\n{FRASE_FOTO_FALHOU}" if corpo else FRASE_FOTO_FALHOU


def _abrir_chamado(loja_id: int, lead_id: str, falhas: int, total: int) -> None:
    from tools.acionar_handoff import acionar_handoff
    acionar_handoff.func(motivo=MOTIVO_CHAMADO.format(falhas=falhas, total=total),
                         resumo=RESUMO_CHAMADO, lead_id=lead_id, loja_id=loja_id)


def _corrigir_gravada(loja_id: int, lead_id: str, texto: str) -> None:
    conexao = conectar()
    try:
        conexao.execute(
            "UPDATE mensagens SET conteudo = ? WHERE id = (SELECT MAX(id) FROM mensagens "
            "WHERE loja_id = ? AND lead_id = ? AND direcao = 'leo')", (texto, loja_id, lead_id))
        conexao.commit()
    finally:
        conexao.close()


async def enviar_fotos_e_texto(*, loja_id: int, lead_id: str, texto: str | None, refs: list[str],
                               enviar_foto: Callable[[str], Awaitable[bool]],
                               enviar_texto: Callable[[str], Awaitable[None]]) -> list[str]:
    """Manda as fotos e depois o texto (corrigido se alguma foto falhou). Devolve as que falharam."""
    falhas: list[str] = []
    for ref in refs or []:
        try:
            ok = bool(await enviar_foto(ref))
        except Exception as erro:                       # canal fora do ar, depósito sem a foto...
            _log.warning(f"[Fotos][loja {loja_id}] envio da foto falhou: {type(erro).__name__}")
            ok = False
        if not ok:
            falhas.append(ref)
    if falhas:
        texto = corrigir_texto(texto or "")
        _log.warning(f"[Fotos][loja {loja_id}] {len(falhas)} de {len(refs)} foto(s) não chegaram; "
                     "texto corrigido e chamado aberto.")
        _abrir_chamado(loja_id, lead_id, len(falhas), len(refs))
        _corrigir_gravada(loja_id, lead_id, texto)
    if texto:
        await enviar_texto(texto)
    return falhas

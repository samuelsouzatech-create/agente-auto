"""
Checagem FIXA de pedido de parada (revisão da Etapa 1).

Rede de segurança do registrar_interesse: o código lê a mensagem do cliente,
sem depender da IA. Pedido CLARO de não ser mais procurado -> grava
'nao_contatar' (e optout) em silêncio. O cliente não vê comando nenhum, e o
assistente continua respondendo normalmente.

Só frases inequívocas. "Agora não" ou "não tenho interesse" ficam com o
assistente, que entende o contexto. Errar para o lado de bloquear custa um
remarketing; errar para o outro lado manda mensagem a quem pediu para parar.
"""
from __future__ import annotations

import re
import unicodedata

from app.interesse import registrar_situacao

_OBJ = r"(mensage(m|ns)|msgs?|propaganda\w*|promoc\w*|oferta\w*|nada)\b"

PADROES = [re.compile(p) for p in (
    rf"\bpar(a|e|ar|em)\s+de\s+me\s+(mandar|enviar)\s+(\w+\s+)?{_OBJ}",
    r"\bpar(a|e|ar|em)\s+de\s+me\s+(chamar|ligar|procurar|incomodar|perturbar)\b",
    rf"\bnao\s+(me\s+)?(mand\w*|envi\w*)\s+mais\s+(\w+\s+)?{_OBJ}",
    r"\bnao\s+me\s+(procur\w*|cham\w*|lig\w*|incomod\w*|perturb\w*)\s+mais\b",
    r"\b(tir\w*|remov\w*|exclu\w*)\s+(me\s+)?(da|dessa|desta|da\s+sua|de\s+sua)\s+lista\b",
    rf"\bnao\s+quero\s+(mais\s+)?receber\s+(\w+\s+)?{_OBJ}",
    r"\bnao\s+(entre|entrem|entra)\s+mais\s+em\s+contato\b",
    r"\bdescadastr\w*",
)]


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", str(texto or "").lower())
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sem_acento)


def pediu_para_parar(texto: str) -> str | None:
    """O trecho do pedido claro, ou None."""
    normal = _normalizar(texto)
    for padrao in PADROES:
        achado = padrao.search(normal)
        if achado:
            return achado.group(0)
    return None


def registrar_se_pediu_parada(loja_id: int, lead_id: str, texto: str, canal: str = "") -> bool:
    """Grava 'nao_contatar' se houver pedido claro. Nunca derruba a conversa."""
    trecho = pediu_para_parar(texto)
    if not trecho:
        return False
    try:
        registrar_situacao(loja_id, lead_id, "nao_contatar",
                           motivo=f'Pedido claro na conversa: "{trecho}" (checagem fixa)',
                           canal=canal)
        print(f"[Parada][loja {loja_id}] Lead {lead_id} pediu para não ser procurado ({trecho}). Registrado.")
        return True
    except Exception as erro:
        print(f"[Parada][loja {loja_id}] ERRO ao registrar pedido de parada: {erro!r}")
        return False

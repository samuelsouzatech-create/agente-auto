"""
Checagem FIXA de pedido de parada (revisão da Etapa 1; Bloco S2, furo 7).

Rede de segurança do registrar_interesse: o código lê a mensagem do cliente,
sem depender da IA. Pedido CLARO de não ser mais procurado -> grava
'nao_contatar' (e optout) em silêncio. O cliente não vê comando nenhum, e o
assistente continua respondendo normalmente.

Errar para o lado de parar custa um remarketing; errar para o outro lado
manda mensagem a quem pediu para parar. Na dúvida pequena, para.

Mas recusar um CARRO não é pedir para parar: "esquece o Civic", "não quero
mais esse", "sai fora do meu orçamento", "não me manda esse modelo" e
"tira da lista o Gol" continuam sendo atendimento.

S2: também "me esquece", "sai fora", "bloqueia meu número", "vou te
bloquear", "n manda mais nada", "não quero mais receber", "me deixa em paz",
"não me escreva mais" e a mensagem só com "pare" / "chega" / "stop" / "sair".
"""
from __future__ import annotations

import re
import unicodedata

from app.interesse import registrar_situacao

_NAO = r"\b(?:nao|n|naum)"
_OBJ = r"(mensage(m|ns)|msgs?|propaganda\w*|promoc\w*|oferta\w*|nada)\b"
_FIM = r"(?=\s*($|[.,!?;]))"
_LISTA_QUE_NAO_E_CONTATO = r"(?!\s+de\s+(espera|carros?|veiculos?|estoque))"
_CONTATO = r"(numero|contato|telefone|celular|whats\w*|zap)\b"

PADROES = [re.compile(p) for p in (
    # "para de me mandar mensagem", "para de me chamar"
    rf"\bpar(a|e|ar|em)\s+de\s+me\s+(mandar|enviar)\s+(\w+\s+)?{_OBJ}",
    r"\bpar(a|e|ar|em)\s+de\s+me\s+(chamar|ligar|procurar|incomodar|perturbar|escrever)\b",
    # "não me manda mais mensagem", "n manda mais nada", "não manda mais"
    rf"{_NAO}\s+(me\s+)?(mand\w*|envi\w*|escrev\w*)\s+mais\s+(\w+\s+)?{_OBJ}",
    rf"{_NAO}\s+(me\s+)?(mand\w*|envi\w*|escrev\w*)\s+mais{_FIM}",
    # "não me chama mais", "não me escreva mais" (mas não "não me chama mais de senhor")
    rf"{_NAO}\s+me\s+(procur\w*|cham\w*|lig\w*|incomod\w*|perturb\w*|escrev\w*)\s+mais\b(?!\s+de\b)",
    # "me tira da lista" (o "me" é obrigatório: "tira da lista o Gol" não é pedido)
    rf"\b(tir\w*|remov\w*|exclu\w*)[\s-]+me\s+(da|dessa|desta|da\s+sua|de\s+sua)\s+lista\b{_LISTA_QUE_NAO_E_CONTATO}",
    rf"\bme\s+(tir\w*|remov\w*|exclu\w*)\s+(da|dessa|desta|da\s+sua|de\s+sua)\s+lista\b{_LISTA_QUE_NAO_E_CONTATO}",
    r"\bchega\s+de\s+(mensage(m|ns)|msgs?|propaganda\w*|promoc\w*|oferta\w*|me\s+\w+)\b",
    r"\bnao\s+quero\s+que\s+(voces|vcs|a\s+loja|ninguem)\s+(me\s+)?(cham\w*|procur\w*|lig\w*|mand\w*|envi\w*)\s+mais(?=\s*($|[.,!?]))",
    # "não quero mais receber (mensagem)", "não quero receber mais nada"
    rf"{_NAO}\s+quero\s+(mais\s+)?receber\s+(mais\s+)?(\w+\s+)?{_OBJ}",
    rf"{_NAO}\s+quero\s+mais\s+receber{_FIM}",
    r"\bnao\s+(entre|entrem|entra)\s+mais\s+em\s+contato\b",
    r"\bdescadastr\w*",
    # "me esquece" (não "me esqueci"; não "esquece o Civic"), "esquece meu número"
    r"\bme\s+esquec(e|a|am|em)\b",
    rf"\besquec(e|a|am|em)\s+(de\s+mim|(o\s+)?meu\s+{_CONTATO})",
    r"\bme\s+deix\w*\s+em\s+paz\b",
    # "sai fora" (não "sai fora do meu orçamento")
    r"\b(sai|cai|vaza)\s+fora\b(?!\s+(d[oa]s?|de)\b)",
    # "bloqueia meu número", "vou te bloquear", "vou bloquear esse número"
    rf"\bbloque\w*\s+(o\s+)?(meu|esse|este)\s+{_CONTATO}",
    r"\bvou\s+(te|lhe|vcs?|voces?)\s+bloque\w*",
    rf"\bvou\s+bloque\w*\s+(voces?|vcs?|a\s+loja|(esse|este|seu|o\s+seu)\s+{_CONTATO})",
    # a mensagem inteira é só "pare", "chega", "stop", "sair"
    r"^\s*(por\s+favor,?\s+)?(pare|parem|para|chega|stop|sair)(\s+(por\s+favor|pf|pfv|pfvr|ja|agora))?\s*[.!]*\s*$",
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

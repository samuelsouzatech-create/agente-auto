"""
Checagem FIXA de pedido de parada (revisão da Etapa 1; Blocos S2 e S4).

Rede de segurança do registrar_interesse: o código lê a mensagem do CLIENTE,
sem depender da IA. Pedido CLARO de não ser mais procurado -> grava
'nao_contatar' (e optout) em silêncio. O cliente não vê comando nenhum, e o
assistente continua respondendo normalmente.

Errar para o lado de parar custa um remarketing; errar para o outro lado
manda mensagem a quem pediu para parar. Na dúvida pequena, para.

Mas recusar um CARRO não é pedir para parar: "esquece o Civic", "não quero
mais esse", "sai fora do meu orçamento", "não me manda esse modelo",
"tira da lista o Gol", "quero cancelar a visita", "apaga o meu cadastro do
Gol" e "me bloqueia o Onix até sábado" continuam sendo atendimento.
Pergunta sobre a própria pessoa ("posso parar de mandar mensagem?",
"devo parar...?") também não conta. "PODE parar de mandar?" conta.

S4: também "para de mandar mensagem" (sem "me"), "pare de me mandar isso",
"me bloqueia", "quero cancelar", "remove meu número", "apaga meu contato",
"chega de spam", "isso é spam", "não quero ser contatado", "deixa eu em paz",
"para de insistir", "parar" sozinha, "não manda mais não" e LGPD /
"apague meus dados".
"""
from __future__ import annotations

import re
import unicodedata

from app.interesse import registrar_situacao

_NAO = r"\b(?:nao|n|naum)"
_OBJ = r"(mensage(m|ns)|msgs?|propaganda\w*|promoc\w*|oferta\w*|nada|spam)\b"
_FIM = r"(?=\s*($|[.,!?;]))"
_LISTA_QUE_NAO_E_CONTATO = r"(?!\s+de\s+(espera|carros?|veiculos?|estoque))"
_CONTATO = r"(numero|contato|telefone|celular|whats\w*|zap)\b"
_ARTIGO = r"(o|a|os|as|esse|essa|este|esta|aquele|aquela|um|uma)\b"

PADROES = [re.compile(p) for p in (
    # "para de (me) mandar mensagem", "pare de me mandar isso", "para de me chamar"
    rf"\bpar(a|e|ar|em)\s+de\s+(me\s+)?(mandar|enviar)\s+(\w+\s+)?{_OBJ}",
    r"\bpar(a|e|ar|em)\s+de\s+(me\s+)?(mandar|enviar)\s+isso\b",
    r"\bpar(a|e|ar|em)\s+de\s+me\s+(chamar|ligar|procurar|incomodar|perturbar|escrever)\b",
    r"\bpar(a|e|ar|em)\s+de\s+(me\s+)?(insistir|encher|amolar|torrar)\b",
    # "não me manda mais mensagem", "n manda mais nada", "não manda mais (não)"
    rf"{_NAO}\s+(me\s+)?(mand\w*|envi\w*|escrev\w*)\s+mais\s+(\w+\s+)?{_OBJ}",
    rf"{_NAO}\s+(me\s+)?(mand\w*|envi\w*|escrev\w*)\s+mais(\s+nao)?{_FIM}",
    # "não me chama mais", "não me escreva mais" (mas não "não me chama mais de senhor")
    rf"{_NAO}\s+me\s+(procur\w*|cham\w*|lig\w*|incomod\w*|perturb\w*|escrev\w*)\s+mais\b(?!\s+de\b)",
    # "me tira da lista" (o "me" é obrigatório: "tira da lista o Gol" não é pedido)
    rf"\b(tir\w*|remov\w*|exclu\w*)[\s-]+me\s+(da|dessa|desta|da\s+sua|de\s+sua)\s+lista\b{_LISTA_QUE_NAO_E_CONTATO}",
    rf"\bme\s+(tir\w*|remov\w*|exclu\w*)\s+(da|dessa|desta|da\s+sua|de\s+sua)\s+lista\b{_LISTA_QUE_NAO_E_CONTATO}",
    r"\bchega\s+de\s+(mensage(m|ns)|msgs?|propaganda\w*|promoc\w*|oferta\w*|spam|me\s+\w+)\b",
    r"\bnao\s+quero\s+que\s+(voces|vcs|a\s+loja|ninguem)\s+(me\s+)?(cham\w*|procur\w*|lig\w*|mand\w*|envi\w*)\s+mais(?=\s*($|[.,!?]))",
    # "não quero mais receber", "não quero ser contatado" (não "ser chamado de senhor")
    rf"{_NAO}\s+quero\s+(mais\s+)?receber\s+(mais\s+)?(\w+\s+)?{_OBJ}",
    rf"{_NAO}\s+quero\s+mais\s+receber{_FIM}",
    rf"{_NAO}\s+quero\s+(mais\s+)?ser\s+(mais\s+)?(contatad|contactad|procurad|chamad|incomodad|perturbad)\w*\b(?!\s+de\b)",
    r"\bnao\s+(entre|entrem|entra)\s+mais\s+em\s+contato\b",
    r"\bdescadastr\w*",
    # "quero cancelar" (sozinho; não "quero cancelar a visita")
    rf"\bquero\s+(me\s+)?(cancelar|descadastrar|sair)(\s+(tudo|isso|as\s+mensagens|o\s+contato|daqui|da\s+lista))?{_FIM}",
    # "remove meu número", "apaga meu contato", "apague meus dados", LGPD
    rf"\b(remov|apag|exclu|delet|tir)\w*\s+(o\s+)?meu\s+{_CONTATO}",
    r"\b(remov|apag|exclu|delet)\w*\s+(todos\s+)?(os\s+)?meus\s+dados\b",
    r"\blgpd\b",
    # "me esquece" (não "me esqueci"; não "esquece o Civic"), "esquece meu número"
    r"\bme\s+esquec(e|a|am|em)\b",
    rf"\besquec(e|a|am|em)\s+(de\s+mim|(o\s+)?meu\s+{_CONTATO})",
    # "me deixa em paz", "deixa eu em paz", "deixa-me em paz"
    r"\b(me\s+deix\w*|deix\w*[\s-]+(eu|me|mim))\s+em\s+paz\b",
    # "sai fora" (não "sai fora do meu orçamento")
    r"\b(sai|cai|vaza)\s+fora\b(?!\s+(d[oa]s?|de)\b)",
    # "isso é spam", "mandando spam" (não "isso não é spam")
    r"(?<!nao )\b(e|eh|sao|virou)\s+(um\s+|puro\s+|so\s+)?spam\b",
    r"\b(mand|envi)\w*\s+(\w+\s+)?spam\b",
    # "me bloqueia" (não "me bloqueia o Onix"), "bloqueia meu número", "vou te bloquear"
    rf"\bme\s+bloque(ia|ie|ar|a)\b(?!\s+{_ARTIGO})",
    rf"\bbloque\w*\s+(o\s+)?(meu|esse|este)\s+{_CONTATO}",
    r"\bvou\s+(te|lhe|vcs?|voces?)\s+bloque\w*",
    rf"\bvou\s+bloque\w*\s+(voces?|vcs?|a\s+loja|(esse|este|seu|o\s+seu)\s+{_CONTATO})",
    # a mensagem inteira é só "pare", "parar", "chega", "stop", "sair", "spam"
    r"^\s*(por\s+favor,?\s+)?(pare|parem|para|parar|chega|stop|sair|spam)(\s+(por\s+favor|pf|pfv|pfvr|ja|agora))?\s*[.!]*\s*$",
)]

# "posso parar de mandar...?", "devo parar...?": a pessoa fala dela mesma, não pede.
_PRIMEIRA_PESSOA = re.compile(
    r"\b(posso|podemos|devo|devemos|quer\s+que\s+eu|quer\s+que\s+a\s+gente|a\s+gente\s+pode)\s+$")


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", str(texto or "").lower())
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sem_acento)


def pediu_para_parar(texto: str) -> str | None:
    """O trecho do pedido claro, ou None."""
    normal = _normalizar(texto)
    for padrao in PADROES:
        for achado in padrao.finditer(normal):
            if _PRIMEIRA_PESSOA.search(normal[max(0, achado.start() - 25):achado.start()]):
                continue
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

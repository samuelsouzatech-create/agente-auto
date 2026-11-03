"""
Guarda de preço: barra valor em R$ que nem uma ferramenta devolveu nem o
cliente falou (preço inventado) e chama o vendedor.

Formatos entendidos: R$ 98.000,00 | R$ 98.000 | R$98000 | R$ 98 mil | R$ 10k
e, no que o cliente escreve: 10 mil | 10k | 10 K | 1,5 mil | 1,5k | 10.000 | 10000.
"90km" NÃO vira 90 mil: o "k" só conta quando vem sozinho.
"""
import re
from langchain_core.messages import ToolMessage, HumanMessage

# Mensagem neutra que o cliente recebe quando a guarda barra a resposta.
# Nada de preço, nada de promessa: só avisa que um vendedor vai continuar.
MENSAGEM_SEGURA = (
    "Deixa eu confirmar esse valor certinho com um vendedor pra não te passar "
    "nada errado. Já já alguém da equipe continua com você por aqui. 👍"
)

# "mil" ou "k" depois do número (10 mil, 10k, 10 K). "km" não conta.
_MIL = r"(\s*(?:mil\b|k\b))?"
# Valor em R$ em qualquer formato: R$ 98.000,00 | R$ 98.000 | R$98000 | R$ 98 mil | R$ 10k
_PADRAO_REAIS = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?" + _MIL, re.I)
# Número solto que o cliente escreveu: 20 mil | 10k | 90.000 | 90000
_PADRAO_NUMERO = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?" + _MIL, re.I)


def _em_centavos(inteiro, centavos, mil) -> int:
    """Normaliza qualquer formato para centavos (int), para comparar com segurança.
    'R$ 98.000,00', 'R$ 98.000', 'R$98000' e 'R$ 98 mil' viram todos 9800000.
    '1,5 mil' e '1,5k' viram 150000 (R$ 1.500), não R$ 1.000,50."""
    reais = int(inteiro.replace(".", ""))
    valor = reais * 100 + int((centavos or "0").ljust(2, "0"))
    if mil:
        valor *= 1000
    return valor


def valores_em_reais(texto: str) -> set:
    """Valores em R$ citados num texto (resposta do Léo ou retorno de tool)."""
    if not texto:
        return set()
    return {_em_centavos(*m) for m in _PADRAO_REAIS.findall(texto)}


def numeros_do_cliente(texto: str) -> set:
    """Números que o cliente escreveu, com ou sem R$. Repetir um número que o
    cliente falou não é inventar preço."""
    if not texto:
        return set()
    return {_em_centavos(*m) for m in _PADRAO_NUMERO.findall(texto)}


def resposta_tem_preco_inventado(resposta: str, mensagens) -> bool:
    """True se a resposta cita um valor em R$ que nem uma tool devolveu
    nem o cliente falou — ou seja, um preço inventado."""
    citados = valores_em_reais(resposta)
    if not citados:
        return False
    permitidos = set()
    for m in mensagens:
        if isinstance(m, ToolMessage):
            permitidos |= valores_em_reais(str(m.content))
        elif isinstance(m, HumanMessage):
            permitidos |= numeros_do_cliente(str(m.content))
    return bool(citados - permitidos)

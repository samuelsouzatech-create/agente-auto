import re
from langchain_core.messages import ToolMessage, HumanMessage

# Mensagem neutra que o cliente recebe quando a guarda barra a resposta.
# Nada de preço, nada de promessa: só avisa que um vendedor vai continuar.
MENSAGEM_SEGURA = (
    "Deixa eu confirmar esse valor certinho com um vendedor pra não te passar "
    "nada errado. Já já alguém da equipe continua com você por aqui. 👍"
)

# Valor em R$ em qualquer formato: R$ 98.000,00 | R$ 98.000 | R$98000 | R$ 98 mil
_PADRAO_REAIS = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?(\s*mil\b)?", re.I)
# Número solto que o cliente escreveu: 20 mil | 90.000 | 90000
_PADRAO_NUMERO = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?(\s*mil\b)?", re.I)


def _em_centavos(inteiro, centavos, mil) -> int:
    """Normaliza qualquer formato para centavos (int), para comparar com segurança.
    'R$ 98.000,00', 'R$ 98.000', 'R$98000' e 'R$ 98 mil' viram todos 9800000."""
    reais = int(inteiro.replace(".", ""))
    if mil:
        reais *= 1000
    return reais * 100 + int((centavos or "0").ljust(2, "0"))


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
"""
Guarda de preço: barra valor em dinheiro que nem uma ferramenta devolveu nem o
cliente falou (preço inventado) e chama o vendedor.

Bloco S1 (furos 1 e 2):
- A resposta é lida com e sem "R$": R$ 98.000,00 | R$ 98 mil | 75 mil |
  75 mil reais | 75k | 1.800 reais | 48x de 1.800 | parcela de 1.800 |
  entrada de 15.000 | sai por 75.000.
- NÃO é preço: ano (2020), km (90 mil km, 90.000 km, 90 mil quilômetros,
  rodou 42 mil), telefone, "48x" sozinho, horário, endereço, número solto.
- O que o cliente escreveu como km não libera preço. Dinheiro que ele falou
  (entrada, orçamento) continua liberado.
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

_INTEIRO = r"(\d{1,3}(?:\.\d{3})+|\d+)"
_CENTAVOS = r"(?:,(\d{1,2}))?"
# "mil" ou "k" depois do número (10 mil, 10k, 10 K). "km" não conta.
_MIL = r"(\s*(?:mil\b|k\b))?"

# Valor com R$ em qualquer formato: sempre é dinheiro.
_PADRAO_REAIS = re.compile(r"R\$\s*" + _INTEIRO + _CENTAVOS + _MIL, re.I)
# Número inteiro solto (não começa no meio de outro número).
_PADRAO_NUMERO = re.compile(r"(?<![\d.,])" + _INTEIRO + _CENTAVOS + _MIL, re.I)

# Quilometragem: depois do número ("90 mil km") ou antes ("km 90.000", "rodou 42 mil").
_KM_DEPOIS = re.compile(r"\s*(?:de\s+)?(?:km\b|kms\b|quil[oô]metr|rodad)", re.I)
_KM_ANTES = re.compile(
    r"(?:\bkm|quilometragem|rodagem|\brod(?:ou|ado|ando))\s*(?:de\s+|:\s*)?"
    r"(?:uns\s+|s[oó]\s+|apenas\s+)?$", re.I)
# Outras coisas que não são dinheiro.
_NAO_DINHEIRO_DEPOIS = re.compile(
    r"\s*(?:anos?\b|meses\b|dias\b|horas?\b|h(?=\d|\b)|min\b|minutos?\b|metros?\b|m2\b"
    r"|portas\b|clientes?\b|carros?\b|ve[ií]culos?\b|unidades?\b|pessoas?\b"
    r"|seguidores?\b|cv\b|cilindradas\b|litros\b)", re.I)
_NAO_DINHEIRO_ANTES = re.compile(
    r"(?:\bano|\bmodelo|\bplaca|\bcep|\bn[úu]mero|\btel(?:efone)?|\bwhats(?:app)?"
    r"|\bcelular|\brua|\bav(?:enida)?\.?)\s*[:-]?\s*(?:de\s+)?$", re.I)
_REAIS_DEPOIS = re.compile(r"\s*reais\b", re.I)
# Contexto de dinheiro sem R$: "parcela de 1.800", "48x de 1.800", "entrada de 15.000".
_CONTEXTO_PARCELA = re.compile(
    r"(?:\b(?:parcelas?|presta[çc]\w*|entrada|sinal|mensalidades?)(?:\s+\w+)?"
    r"|\b\d{1,3}\s*x)\s*(?:de\s+|:\s*)?$", re.I)
# "sai por 75.000", "valor de 75.000" (só com ponto de milhar ou 5+ dígitos: ano não entra).
_CONTEXTO_VALOR = re.compile(
    r"\b(?:por|valor|pre[çc]o|custa|custando|sai\s+a|vale)\s*(?:de\s+|:\s*|é\s+|e\s+)?"
    r"(?:uns\s+|umas\s+|apenas\s+|s[oó]\s+)?$", re.I)
_OLHAR = 30   # quantos caracteres antes do número olhamos


def _em_centavos(inteiro, centavos, mil) -> int:
    """Normaliza qualquer formato para centavos (int), para comparar com segurança.
    'R$ 98.000,00', 'R$ 98.000', 'R$98000' e 'R$ 98 mil' viram todos 9800000.
    '1,5 mil' e '1,5k' viram 150000 (R$ 1.500), não R$ 1.000,50."""
    reais = int(inteiro.replace(".", ""))
    valor = reais * 100 + int((centavos or "0").ljust(2, "0"))
    if mil:
        valor *= 1000
    return valor


def _antes(texto, m) -> str:
    return texto[max(0, m.start() - _OLHAR):m.start()]


def _e_km(texto, m) -> bool:
    return bool(_KM_DEPOIS.match(texto, m.end()) or _KM_ANTES.search(_antes(texto, m)))


def _grande(inteiro, minimo_digitos) -> bool:
    return "." in inteiro or len(inteiro) >= minimo_digitos


def _dinheiro_sem_cifrao(texto, m) -> bool:
    inteiro, _centavos, mil = m.groups()
    antes = _antes(texto, m)
    if _e_km(texto, m) or _NAO_DINHEIRO_DEPOIS.match(texto, m.end()) or _NAO_DINHEIRO_ANTES.search(antes):
        return False
    if mil or _REAIS_DEPOIS.match(texto, m.end()):
        return True
    if _CONTEXTO_PARCELA.search(antes):
        return _grande(inteiro, 3)
    if _CONTEXTO_VALOR.search(antes):
        return _grande(inteiro, 5)
    return False


def valores_em_reais(texto: str) -> set:
    """Valores em dinheiro citados num texto (resposta do Léo ou retorno de tool), em centavos."""
    if not texto:
        return set()
    achados = {_em_centavos(*m) for m in _PADRAO_REAIS.findall(texto)}
    for m in _PADRAO_NUMERO.finditer(texto):
        if _dinheiro_sem_cifrao(texto, m):
            achados.add(_em_centavos(*m.groups()))
    return achados


def numeros_do_cliente(texto: str) -> set:
    """Números que o cliente escreveu, com ou sem R$. Repetir um número que o
    cliente falou não é inventar preço. Furo 2: quilometragem não conta."""
    if not texto:
        return set()
    return {_em_centavos(*m.groups()) for m in _PADRAO_NUMERO.finditer(texto)
            if not _e_km(texto, m)}


def resposta_tem_preco_inventado(resposta: str, mensagens) -> bool:
    """True se a resposta cita um valor em dinheiro que nem uma tool devolveu
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

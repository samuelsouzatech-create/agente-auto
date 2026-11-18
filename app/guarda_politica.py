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

Bloco S4 (ajustes do analista):
- Por extenso: "setenta mil", "dez mil de entrada", "um milhão",
  "quinhentos reais", "entrada de mil e quinhentos".
  NÃO: "mil desculpas", "cem por cento", "dois mil e vinte" (ano),
  "noventa mil km", "rodou noventa mil".
- Espaço de milhar: "75 000 reais" = 75.000 (antes virava 0).
- "milhão" depois de número: "R$ 1,2 milhão".
"""
import re
import unicodedata

from langchain_core.messages import ToolMessage, HumanMessage

# Mensagem neutra que o cliente recebe quando a guarda barra a resposta.
# Nada de preço, nada de promessa: só avisa que um vendedor vai continuar.
MENSAGEM_SEGURA = (
    "Deixa eu confirmar esse valor certinho com um vendedor pra não te passar "
    "nada errado. Já já alguém da equipe continua com você por aqui. 👍"
)

# 98.000 | 75 000 (espaço de milhar) | 98000
_INTEIRO = r"(\d{1,3}(?:\.\d{3})+|\d{1,3}(?: \d{3}(?!\d))+|\d+)"
_CENTAVOS = r"(?:,(\d{1,2}))?"
# "mil", "k" ou "milhão" depois do número. "km" não conta.
_MIL = r"(\s*(?:mil\b|k\b|milh(?:ao|ão|oes|ões)\b))?"

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
    r"|seguidores?\b|cv\b|cilindradas\b|litros\b|%|por\s+cento\b)", re.I)
_NAO_DINHEIRO_ANTES = re.compile(
    r"(?:\bano|\bmodelo|\bplaca|\bcep|\bn[úu]mero|\btel(?:efone)?|\bwhats(?:app)?"
    r"|\bcelular|\brua|\bav(?:enida)?\.?)\s*[:-]?\s*(?:de\s+)?$", re.I)
_REAIS_DEPOIS = re.compile(r"\s*reais\b", re.I)
_CIFRAO_ANTES = re.compile(r"R\$\s*$")
_DIGITO_ANTES = re.compile(r"\d\s*$")
# Contexto de dinheiro sem R$: "parcela de 1.800", "48x de 1.800", "entrada de 15.000".
_CONTEXTO_PARCELA = re.compile(
    r"(?:\b(?:parcelas?|presta[çc]\w*|entrada|sinal|mensalidades?)(?:\s+\w+)?"
    r"|\b\d{1,3}\s*x)\s*(?:de\s+|:\s*)?$", re.I)
# "sai por 75.000", "valor de 75.000" (só com separador de milhar ou 5+ dígitos: ano não entra).
_CONTEXTO_VALOR = re.compile(
    r"\b(?:por|valor|pre[çc]o|custa|custando|sai\s+a|vale)\s*(?:de\s+|:\s*|é\s+|e\s+)?"
    r"(?:uns\s+|umas\s+|apenas\s+|s[oó]\s+)?$", re.I)
_OLHAR = 30   # quantos caracteres antes do número olhamos

# Número por extenso (sem acento: o texto é comparado numa cópia sem acento).
_PALAVRAS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
    "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12,
    "treze": 13, "quatorze": 14, "catorze": 14, "quinze": 15, "dezesseis": 16,
    "dezessete": 17, "dezoito": 18, "dezenove": 19, "vinte": 20, "trinta": 30,
    "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70, "oitenta": 80,
    "noventa": 90, "cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200,
    "trezentos": 300, "trezentas": 300, "quatrocentos": 400, "quatrocentas": 400,
    "quinhentos": 500, "quinhentas": 500, "seiscentos": 600, "seiscentas": 600,
    "setecentos": 700, "setecentas": 700, "oitocentos": 800, "oitocentas": 800,
    "novecentos": 900, "novecentas": 900,
}
_ESCALAS = {"mil": 1000, "milhao": 1000000, "milhoes": 1000000}
_PALAVRA = r"(?:" + "|".join(sorted(list(_PALAVRAS) + list(_ESCALAS), key=len, reverse=True)) + r")\b"
_PADRAO_EXTENSO = re.compile(r"\b" + _PALAVRA + r"(?:\s+(?:e\s+)?" + _PALAVRA + r")*", re.I)


def _em_centavos(inteiro, centavos, mil) -> int:
    """Normaliza qualquer formato para centavos (int), para comparar com segurança.
    'R$ 98.000,00', 'R$ 98.000', 'R$98000', '98 000' e 'R$ 98 mil' viram 9800000.
    '1,5 mil' e '1,5k' viram 150000 (R$ 1.500), não R$ 1.000,50."""
    reais = int(re.sub(r"\D", "", inteiro))
    valor = reais * 100 + int((centavos or "0").ljust(2, "0"))
    escala = (mil or "").strip().lower()
    if escala.startswith("milh"):
        valor *= 1000000
    elif escala:
        valor *= 1000
    return valor


def _antes(texto, m) -> str:
    return texto[max(0, m.start() - _OLHAR):m.start()]


def _e_km(texto, m) -> bool:
    return bool(_KM_DEPOIS.match(texto, m.end()) or _KM_ANTES.search(_antes(texto, m)))


def _grande(inteiro, minimo_digitos) -> bool:
    return not inteiro.isdigit() or len(inteiro) >= minimo_digitos


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


def _sem_acento_mesmo_tamanho(texto) -> str:
    """Tira o acento letra por letra: as posições continuam as mesmas do original."""
    return "".join(unicodedata.normalize("NFD", c)[0] for c in texto)


def _valor_extenso(trecho):
    palavras = [p for p in trecho.lower().split() if p != "e"]
    total = atual = 0
    for p in palavras:
        if p in _PALAVRAS:
            atual += _PALAVRAS[p]
        else:
            total += (atual or 1) * _ESCALAS[p]
            atual = 0
    return total + atual, palavras


def _extensos(texto):
    """Cada número por extenso: (trecho achado, valor em reais, palavras)."""
    for m in _PADRAO_EXTENSO.finditer(_sem_acento_mesmo_tamanho(texto)):
        valor, palavras = _valor_extenso(m.group(0))
        yield m, valor, palavras


def _depois_de_digito(texto, m, palavras) -> bool:
    """'75 mil': o 'mil' já foi lido junto com o 75."""
    return palavras[0] in _ESCALAS and bool(_DIGITO_ANTES.search(_antes(texto, m)))


def _dinheiro_por_extenso(texto, m, valor, palavras) -> bool:
    if not valor or _depois_de_digito(texto, m, palavras):
        return False
    antes = _antes(texto, m)
    if _e_km(texto, m) or _NAO_DINHEIRO_DEPOIS.match(texto, m.end()) or _NAO_DINHEIRO_ANTES.search(antes):
        return False
    if _REAIS_DEPOIS.match(texto, m.end()) or _CIFRAO_ANTES.search(antes):
        return True
    contexto = bool(_CONTEXTO_PARCELA.search(antes) or _CONTEXTO_VALOR.search(antes))
    if palavras == ["cento"]:
        return False                          # "cento" sozinho é "por cento"
    if palavras == ["mil"]:
        return contexto                       # "mil desculpas" não; "entrada de mil" sim
    if not any(p in _ESCALAS for p in palavras):
        return contexto and valor >= 100      # "cem por cento" não; "parcela de quinhentos" sim
    if 1900 <= valor <= 2099 and valor % 1000 and not contexto:
        return False                          # "dois mil e vinte" é ano
    return True


def valores_em_reais(texto: str) -> set:
    """Valores em dinheiro citados num texto (resposta do Léo ou retorno de tool), em centavos."""
    if not texto:
        return set()
    achados = {_em_centavos(*m) for m in _PADRAO_REAIS.findall(texto)}
    for m in _PADRAO_NUMERO.finditer(texto):
        if _dinheiro_sem_cifrao(texto, m):
            achados.add(_em_centavos(*m.groups()))
    for m, valor, palavras in _extensos(texto):
        if _dinheiro_por_extenso(texto, m, valor, palavras):
            achados.add(valor * 100)
    return achados


def numeros_do_cliente(texto: str) -> set:
    """Números que o cliente escreveu (com ou sem R$, também por extenso).
    Repetir um número que o cliente falou não é inventar preço.
    Furo 2: quilometragem não conta."""
    if not texto:
        return set()
    numeros = {_em_centavos(*m.groups()) for m in _PADRAO_NUMERO.finditer(texto)
               if not _e_km(texto, m)}
    for m, valor, palavras in _extensos(texto):
        if valor and not _e_km(texto, m) and not _depois_de_digito(texto, m, palavras):
            numeros.add(valor * 100)
    return numeros


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


# ----------------------------------------------------------------------
# Bloco L2: promessa de contato da equipe sem chamado aberto.
# Se o Léo diz que a equipe vai confirmar ou falar com o cliente, o chamado
# tem que existir no MESMO turno. A guarda não muda a resposta: só abre o
# chamado que faltou (errar para o lado de abrir é melhor que prometer à toa).
# ----------------------------------------------------------------------
_QUEM_DA_EQUIPE = r"\b(equipe|vendedor|vendedora|vendedores|pessoal|consultor|consultora|gerente|time|alguem)\b"
_PADROES_CONTATO = [
    # "o pessoal da equipe vai falar com você", "um vendedor vai te chamar"
    re.compile(_QUEM_DA_EQUIPE + r"[^.!?]{0,40}\b(vai|vao|ira|irao)\s+(te\s+|lhe\s+)?"
               r"(falar|chamar|entrar em contato|retornar|responder|confirmar|verificar|ligar|"
               r"mandar|passar|atender|continuar|dar retorno|te responder)"),
    # "vou confirmar com a equipe", "vou verificar com o vendedor"
    re.compile(r"\b(vou|vamos|irei)\s+(confirmar|verificar|checar|consultar|ver isso|ver)\b"
               r"[^.!?]{0,30}\b(com|junto)\b[^.!?]{0,12}" + _QUEM_DA_EQUIPE),
    # "vou passar para a equipe", "vou encaminhar ao vendedor"
    re.compile(r"\b(vou|vamos|irei)\s+(passar|encaminhar|repassar|levar)\b[^.!?]{0,40}" + _QUEM_DA_EQUIPE),
    # L2b: "vou chamar alguém da equipe", "vou pedir para um vendedor", "vou passar para o pessoal"
    re.compile(r"\b(vou|vamos|irei)\s+(te\s+)?(chamar|pedir\s+(para|pra|que|ao|a)|passar\s+(para|pra|ao|a))\b"
               r"[^.!?]{0,15}" + _QUEM_DA_EQUIPE),
    # L3b: verbo de promessa e alguém da equipe na MESMA frase, com qualquer coisa no meio
    # ("vou verificar essa informação específica sobre o laudo com o pessoal da equipe")
    re.compile(r"\b(vou|vamos|irei)\s+(te\s+)?(verificar|confirmar|checar|ver|chamar|passar)\b"
               r"[^.!?]*" + _QUEM_DA_EQUIPE),
]
_NEGACAO_CONTATO = re.compile(r"\b(nao|nunca|nem)\b")
# L2b: oferta em pergunta ("quer que eu chame um vendedor?") não é promessa.
_OFERTA = re.compile(r"\b(quer que|queira que|gostaria que|prefere que|deseja que|posso|se quiser)\b")


def _sem_acento(texto: str) -> str:
    sem = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in sem if unicodedata.category(c) != "Mn").lower()


def promete_contato_da_equipe(resposta: str) -> bool:
    """True se a resposta diz que a equipe vai confirmar/falar com o cliente."""
    for frase in re.split(r"(?<=[.!?])\s+|\n+", _sem_acento(resposta)):
        if _NEGACAO_CONTATO.search(frase) or _OFERTA.search(frase):
            continue
        if any(p.search(frase) for p in _PADROES_CONTATO):
            return True
    return False


# L3b: cliente (número fora da equipe) dizendo ser dono, gestor ou da loja.
# "sou o dono do carro" não conta: dono DE alguma coisa que não é a loja.
PREFIXO_FALSO_DONO = "ATENÇÃO: diz ser da equipe, mas o número não está cadastrado"
_CARGO = r"(dono|dona|gestor|gestora|gerente|socio|socia|proprietario|proprietaria)"
_FALSO_DONO = [
    re.compile(r"\b(sou|aqui e|quem fala e)\b[^.!?]{0,30}\b" + _CARGO + r"\b"
               r"(?!\s+d[oae]s?\s+(?!loja\b))"),
    re.compile(r"\b(sou|aqui e)\s+(da loja|da equipe|funcionari[oa]|vendedor[a]? da loja)\b"),
]


def diz_ser_da_equipe(texto: str) -> bool:
    frase = _sem_acento(texto)
    return any(p.search(frase) for p in _FALSO_DONO)

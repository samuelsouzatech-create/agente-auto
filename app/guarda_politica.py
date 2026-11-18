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
    # L5b: "o pessoal da equipe pode te passar / vai confirmar / vão informar"
    re.compile(_QUEM_DA_EQUIPE + r"[^.!?]{0,40}\b(pode|podem|vai|vao)\s+(te\s+|lhe\s+)?"
               r"(passar|confirmar|informar)\b"),
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


# L5b: assunto do CLIENTE que só a equipe responde -> chamado na mesma fala (código).
_ASSUNTOS_DA_EQUIPE = [
    ("laudo", r"\blaudos?\b"), ("cautelar", r"\bcautelar\b"), ("leilão", r"\bleiloes?\b|\bleilao\b"),
    ("sinistro", r"\bsinistr\w*"), ("IPVA", r"\bipva\b"), ("multa", r"\bmultas?\b"),
    ("documentação do carro", r"\bdocumentacao\b|\bdocumentos?\s+do\s+(carro|veiculo)\b"),
    ("procedência", r"\bprocedencia\b"), ("dono anterior", r"\bdonos?\s+anterior(es)?\b"),
    ("revisão", r"\brevis(ao|oes|ado|ada|adas|ados)\b"),
]
_ASSUNTOS_COMPILADOS = [(nome, re.compile(p)) for nome, p in _ASSUNTOS_DA_EQUIPE]


def assunto_da_equipe(texto: str) -> str | None:
    """Nome do primeiro assunto que só a equipe responde, ou None."""
    frase = _sem_acento(texto)
    return next((nome for nome, p in _ASSUNTOS_COMPILADOS if p.search(frase)), None)


# L5b: cliente pedindo valor do carro DELE ("quanto vocês pagam no meu", "quanto vale o meu").
_VALOR_DA_TROCA = [
    re.compile(r"\bquanto\s+(voces\s+|vcs\s+|vc\s+|voce\s+|a loja\s+)?"
               r"(pagam|paga|dao|da|avaliam|avalia|oferecem|oferece)\s+(no|na|pelo|pela|pro|pra|por)\s+"
               r"(meu|minha|o meu|a minha)\b"),
    re.compile(r"\bquanto\s+(vale|valeria|sai)\s+(o\s+|a\s+)?(meu|minha)\b"),
]


def pediu_valor_da_troca(texto: str) -> bool:
    frase = _sem_acento(texto)
    return any(p.search(frase) for p in _VALOR_DA_TROCA)


def pergunta_curta(texto: str, limite: int = 120) -> str:
    """L5b: a pergunta do cliente que vai no motivo do chamado (máx. 120 letras)."""
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= limite else texto[:limite - 1].rstrip() + "…"


# ======================================================================
# L5c: frases trocadas pelo CÓDIGO antes de a resposta sair
# ======================================================================
FRASE_CONTATO = "O pessoal da equipe vai falar com você por aqui."
FRASE_ENTRADA = "O valor da entrada depende da análise de crédito, feita por um vendedor."

# "já está acompanhando", "acompanhando a conversa", "já passei": falsos (ninguém lê a
# conversa até ser chamado) e com palavra de tempo.
FRASES_PROIBIDAS = re.compile(r"\bja\s+(esta|estao)\s+acompanhando\b|\bacompanhando\s+(a|nossa|essa|esta)\s+conversa\b"
                              r"|\bja\s+passei\b")

# Entrada do financiamento: o Léo não afirma regra ("flexível", "você define", "sem entrada").
_ENTRADA = re.compile(r"\bentrada\b")
_REGRA_ENTRADA = re.compile(r"\bflexive\w*|\bvoce\s+(define|escolhe|decide)\b|\bsem\s+entrada\b|\bentrada\s+zero\b"
                            r"|\bnao\s+(precisa|e\s+necessari\w*|exige)\w*\b[^.!?]{0,20}\bentrada\b"
                            r"|\bqualquer\s+valor\b|\bentrada\s+minima\s+(e|de)\b")
_RESSALVA_ENTRADA = re.compile(r"\b(depende|analise|aprovacao)\b")

# Foto do carro do cliente: o Léo não avalia nem elogia o estado.
ELOGIO_DO_ESTADO = re.compile(
    r"\bbem\s+(conservad\w*|cuidad\w*)|\b(otimo|excelente|bom|perfeito|lindo|belo)\s+estado\b"
    r"|\bestado\s+(impecavel|otimo|excelente|perfeito)\b|\bimpecave\w*|\bmuito\s+conservad\w*"
    r"|\bparece\s+(estar\s+)?(muito\s+)?(bem|otimo|novo|novinho|conservad\w*)\b|\bnovinho\b")
FRASE_FOTO_CARRO = "Obrigado pela foto!"

# Pergunta sobre a loja aceitar troca (quando o cadastro não diz).
_PERGUNTA_TROCA = re.compile(r"\b(aceita\w*|pega\w*|recebe\w*|trabalha\w*\s+com)\b[^.!?]{0,30}\btroca\b"
                             r"|\bdar\b[^.!?]{0,30}\bna\s+troca\b|\b(da|daria)\s+pra\s+trocar\b|\btroca\s+(o|a|meu|minha)\b")


def _frases_originais(texto: str) -> list[str]:
    return [f for f in re.split(r"(?<=[.!?])\s+|\n+", str(texto or "")) if f.strip()]


def trocar_frases_proibidas(resposta: str) -> tuple[str, bool]:
    """Frase com "já está acompanhando", "acompanhando a conversa" ou "já passei"
    vira "O pessoal da equipe vai falar com você por aqui." (uma vez só)."""
    saida, trocou = [], False
    for frase in _frases_originais(resposta):
        if FRASES_PROIBIDAS.search(_sem_acento(frase)):
            if not trocou:
                saida.append(FRASE_CONTATO)
            trocou = True
        else:
            saida.append(frase)
    return (" ".join(saida) if trocou else resposta), trocou


def corrigir_regra_de_entrada(resposta: str) -> tuple[str, bool]:
    """Frase que fala de entrada e afirma regra (sem dizer que depende da análise)
    vira "O valor da entrada depende da análise de crédito, feita por um vendedor." """
    saida, trocou = [], False
    for frase in _frases_originais(resposta):
        f = _sem_acento(frase)
        if _ENTRADA.search(f) and _REGRA_ENTRADA.search(f) and not _RESSALVA_ENTRADA.search(f):
            if not trocou:
                saida.append(FRASE_ENTRADA)
            trocou = True
        else:
            saida.append(frase)
    return (" ".join(saida) if trocou else resposta), trocou


def tirar_elogio_do_estado(resposta: str) -> tuple[str, bool]:
    """Foto do carro do cliente: tira as frases que avaliam/elogiam o estado.
    Se não sobrar nada, fica só "Obrigado pela foto!"."""
    frases = _frases_originais(resposta)
    ficam = [f for f in frases if not ELOGIO_DO_ESTADO.search(_sem_acento(f))]
    if len(ficam) == len(frases):
        return resposta, False
    return (" ".join(ficam) if ficam else FRASE_FOTO_CARRO), True


def tirar_elogio_da_descricao(descricao: str) -> str:
    """Descrição da foto do carro sem julgamento de estado ("bom estado", "bem conservado")."""
    texto = str(descricao or "")
    sem = _sem_acento(texto)
    partes = [p.strip() for p in re.split(r",|\be\b", texto)]
    if not ELOGIO_DO_ESTADO.search(sem) and not re.search(r"\bconservacao\b", sem):
        return texto
    limpas = [p for p in partes if p and not ELOGIO_DO_ESTADO.search(_sem_acento(p))
              and not re.search(r"\bconservacao\b", _sem_acento(p))]
    return ", ".join(limpas).strip(" ,.")


def pergunta_se_aceita_troca(texto: str) -> bool:
    return bool(_PERGUNTA_TROCA.search(_sem_acento(texto)))


# ======================================================================
# L6: pós-venda e cliente irritado (chamado pelo CÓDIGO na mesma fala)
# ======================================================================
PREFIXO_POS_VENDA = "PÓS-VENDA: "     # o job de pós-venda cancela os passos futuros com este início
MARCA_URGENTE = "URGENTE"

_AMEACA = re.compile(r"\bprocon\b|\badvogad\w*|\bprocess(ar|o|ando)\b|\breclame\s*aqui\b|\bjustica\b"
                     r"|\bconsumidor\.gov|\bdenunci\w*|\babsurd\w*|\bpalhacada\b|\bvergonha\b"
                     r"|\bpessimo\s+atendimento\b|\bnunca\s+mais\s+compro\b")
_PROBLEMA_DA_COMPRA = re.compile(
    r"\bbarulh\w*|\bdefeit\w*|\bproblem\w*|\bquebr\w*|\bvazament\w*|\bvazando\b|\bfalh\w*|\bluz\b[^.!?]{0,20}\bacesa\b"
    r"|\bnao\s+(liga|pega|funciona)\b|\bsuperaquec\w*|\bfumac\w*|\btransferencia\b|\bdocument\w*|\bdut\b|\bcrlv\b"
    r"|\bpagamento\b|\bboleto\b|\bparcela\w*\s+(atrasad\w*|errad\w*)|\bcobranca\b")


# L7: o Léo diz que mandou/vai mandar fotos, mas nenhuma foto saiu neste turno.
PROMESSA_DE_FOTO = re.compile(
    r"\b(segue|seguem|estou\s+enviando|enviando|te\s+envio|te\s+mando|vou\s+(te\s+)?(mandar|enviar)"
    r"|ja\s+(te\s+)?(mandei|enviei)|mandei|enviei|aqui\s+estao|olha\s+so)\b[^.!?]{0,30}\bfotos?\b"
    r"|\bfotos?\b[^.!?]{0,20}\b(a\s+caminho|logo\s+abaixo|acima|enviadas?|seguem)\b")
FRASE_SEM_FOTO = "Por aqui não tenho fotos desse carro para mandar."


def tirar_promessa_de_foto(resposta: str) -> tuple[str, bool]:
    """L7: só vale quando nenhuma foto saiu no turno. Frase que promete/diz que mandou
    foto vira "Por aqui não tenho fotos desse carro para mandar." (uma vez só)."""
    saida, trocou = [], False
    for frase in _frases_originais(resposta):
        f = _sem_acento(frase)
        if PROMESSA_DE_FOTO.search(f) and not re.search(r"\b(quer|gostaria|posso|prefere)\b", f):
            if not trocou:
                saida.append(FRASE_SEM_FOTO)
            trocou = True
        else:
            saida.append(frase)
    return (" ".join(saida) if trocou else resposta), trocou


def cliente_ameacou(texto: str) -> bool:
    """Cliente irritado ou ameaçando (Procon, advogado, Reclame Aqui...)."""
    return bool(_AMEACA.search(_sem_acento(texto)))


def relatou_problema_da_compra(texto: str) -> bool:
    """Problema com o carro comprado ou com a compra (só vale para quem comprou na loja)."""
    return bool(_PROBLEMA_DA_COMPRA.search(_sem_acento(texto)))


def motivo_com_marcas(motivo: str, *, pos_venda: bool, urgente: bool) -> str:
    """Põe "PÓS-VENDA: " no começo (o job de pós-venda lê isso) e "URGENTE — " logo depois.
    Não repete marca que já está lá."""
    motivo = str(motivo or "").strip()
    sem = _sem_acento(motivo).upper()
    corpo = motivo
    tem_pv = sem.startswith(("POS-VENDA", "POS VENDA", "POSVENDA"))
    if tem_pv:
        corpo = motivo.split(":", 1)[1].strip() if ":" in motivo else motivo
    if urgente and MARCA_URGENTE not in sem:
        corpo = f"{MARCA_URGENTE} — {corpo}"
    return f"{PREFIXO_POS_VENDA}{corpo}" if (pos_venda or tem_pv) else corpo

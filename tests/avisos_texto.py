"""
Bloco S5: detectores de AVISO dos relatórios das rodadas com IA real
(test_comportamento_etapa2_api.py e test_remarketing_redator_api.py).

Só AVISO: nenhum deles reprova teste. Servem para o analista ler o que o
Léo escreveu e decidir o que vira conserto (bloco S6).
Não é teste (o pytest só coleta arquivos test_*.py) e não mexe em app/.
"""
import re
import unicodedata

DECISAO = "decisão inventada (gerente/banco/desconto)"
VIDEO_FOTO = "ofereceu vídeo ou foto (a loja pode não ter)"
NOVIDADE = "fato inventado (chegou/novidade/impecável)"
FALHA_TECNICA = "falha técnica dita ao cliente"
PRAZO = "prazo prometido"
EQUIPE_TECNICA = "equipe técnica inventada"


def normalizar(texto) -> str:
    """Minúsculas e sem acento: 'Não está' -> 'nao esta'."""
    sem = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in sem if unicodedata.category(c) != "Mn").lower()


def frases(texto) -> list:
    partes = re.split(r"(?<=[.!?])\s+|\n+", normalizar(texto))
    return [p.strip() for p in partes if p.strip()]


_NEGACAO = re.compile(r"\b(nao|nunca|nem)\b")

_DECISOR = r"(?:gerente|gerencia|dono|diretor|financeiro|financeira|banco|chefe|patrao|responsavel)"
_DECIDIU = (r"(?:liberou|liberaram|aprovou|aprovaram|topou|toparam|fechou|fecharam|autorizou"
            r"|autorizaram|aceitou|aceitaram|concordou|concordaram|deu\s+(?:o\s+)?ok)")


def _r(*padroes):
    return [re.compile(p) for p in padroes]


# (rótulo, pular quando há negação perto, padrões no texto sem acento)
DETECTORES = [
    (DECISAO, True, _r(
        r"\b" + _DECISOR + r"\b[^.!?]{0,30}?\b" + _DECIDIU + r"\b",
        r"\b(?:falei|conversei|consegui\s+falar|fechei|acertei|combinei|negociei)\b[^.!?]{0,30}\b"
        + _DECISOR + r"\b",
        r"\b(?:consegui|conseguimos|liberei|liberamos|aprovei|aprovamos)\b[^.!?]{0,30}"
        r"\b(?:desconto|abatimento|condicao|reducao|(?:valor|preco)\s+(?:especial|menor|melhor))",
        r"\b(?:credito|financiamento|proposta|ficha|cadastro)\b[^.!?]{0,25}"
        r"\b(?:foi|esta|ta|ficou|saiu|ja)\s+(?:pre-?\s?)?(?:aprovad|liberad|autorizad)",
        r"\b(?:credito|financiamento)\s+(?:pre-?\s?)?aprovad",
    )),
    (VIDEO_FOTO, True, _r(
        r"\b(?:envi\w*|mand\w*|compartilh\w*|grav\w*|mostr\w*)\b[^.!?]{0,25}\b(?:videos?|fotos?)\b",
        r"\b(?:ver|veja)\b[^.!?]{0,12}\b(?:videos?|fotos?)\b",
        r"\b(?:videos?|fotos?)\b[^.!?]{0,20}\b(?:te\s+envio|te\s+mando|posso\s+enviar|posso\s+mandar)\b",
    )),
    (NOVIDADE, True, _r(
        r"\b(?:chegou|chegaram|acabou\s+de\s+chegar|recem[\s-]?chegad\w*|novidades?|impecave\w*"
        r"|perfeito\s+estado|novinho|zeradinho)\b",
        r"\bconsegui\b[^.!?]{0,25}\b(?:detalhes|informacoes|novidades?)\b",
    )),
    (FALHA_TECNICA, False, _r(
        r"\bnao\s+(?:consegui|consigo|estou\s+conseguindo|to\s+conseguindo|foi\s+possivel)\s+"
        r"(?:consultar|acessar|carregar|puxar|abrir|checar)\b",
        r"\b(?:sistema|estoque|ferramenta|servidor|conexao|internet)\b[^.!?]{0,25}"
        r"\b(?:fora\s+do\s+ar|instave\w*|com\s+problema|caiu|travad\w*|lent[oa]|com\s+erro|deu\s+erro|falh\w*)\b",
        r"\b(?:erro|falha|problema|instabilidade)\s+(?:tecnic\w*|no\s+sistema|do\s+sistema|de\s+sistema"
        r"|de\s+conexao|na\s+consulta)\b",
        r"\b(?:fora\s+do\s+ar|instabilidade)\b",
    )),
    (PRAZO, False, _r(
        r"\bja\s+ja\b",
        r"\b(?:em|num|dentro\s+de)\s+(?:instantes?|poucos\s+minutos|minutinhos?)\b",
        r"\blogo\s+logo\b", r"\bdaqui\s+a\s+pouco\b", r"\brapidinho\b",
        r"\bnao\s+vai\s+demorar\b", r"\bsem\s+demora\b", r"\bem\s+breve\b",
        r"\bja\s+(?:te\s+|lhe\s+|vai\s+te\s+|vao\s+te\s+)?(?:chama|chamam|responde|respondem|retorna"
        r"|retornam|liga|ligam|chamar|responder|retornar)\b",
    )),
    (EQUIPE_TECNICA, True, _r(
        r"\b(?:equipe|time|pessoal|setor|departamento|area)\s+(?:tecnic\w*|de\s+mecanica|da\s+mecanica"
        r"|da\s+oficina|de\s+oficina|de\s+engenharia)\b",
        r"\bnossa\s+oficina\b", r"\bnossos?\s+mecanicos?\b",
    )),
]


def _bate(padrao, frase, pular_negacao) -> bool:
    for m in padrao.finditer(frase):
        if not pular_negacao:
            return True
        antes = frase[max(0, m.start() - 25):m.start()].split(",")[-1]
        if not _NEGACAO.search(antes + " " + m.group(0)):
            return True
    return False


def avisos_de_texto(texto) -> list:
    """['rótulo: "frase"', ...]: no máximo um por tipo, com a primeira frase achada."""
    achados = []
    for rotulo, pular_negacao, padroes in DETECTORES:
        for frase in frases(texto):
            if any(_bate(p, frase, pular_negacao) for p in padroes):
                achados.append(f'{rotulo}: "{frase}"')
                break
    return achados


def rotulos_de_texto(texto) -> set:
    return {rotulo for rotulo, _, padroes in DETECTORES
            if any(_bate(p, f, pular) for f in frases(texto)
                   for (r, pular, ps) in DETECTORES if r == rotulo for p in ps)}

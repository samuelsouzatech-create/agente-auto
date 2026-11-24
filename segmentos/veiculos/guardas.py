"""
Guardas próprias do ramo de VEÍCULOS (SG1, Maratona 4).

Saíram de app/guarda_politica.py e de app/core/turno.py SEM mudar uma vírgula do que fazem: o
motor chama cada uma pelo gancho do contrato (docs/pacote_de_ramo.md), no MESMO lugar da lista
única do pós-processamento (N4, app/core/pos_processamento.py). A ordem não mudou.

Ganchos que este ramo entrega:
  tirar_elogio_do_estado     passo 7 (foto do carro do cliente): sem elogio ao estado
  cortar_estado_inventado    passo 8: estado/qualidade do carro só se veio da ficha
  depois_da_agenda           passo 9: test-drive agendado lembra a CNH
  motivo_do_chamado          passo 10: aceita troca? / valor da troca (antes das regras do motor)
  tirar_elogio_da_descricao  turno com foto do cliente: descrição sem julgamento de estado
  anotar_foto_do_cliente     turno com foto do cliente: a troca registrada ganha "foto recebida"
  motivo_do_chamado_pelo_codigo  a regra inteira (ramo + motor), como era no turno (testes e bancada)

As ferramentas cuja resposta é a "ficha" do carro estão em ferramentas.py (FERRAMENTAS_DE_FICHA).
"""
from __future__ import annotations

import re

from app.guarda_politica import (_NEGA, _PALAVRA_DE_CARRO, _frases_originais, _mantem_linhas,
                                 _sem_acento, assunto_da_frase)

# ======================================================================
# L5c: foto do carro do cliente (o Léo não avalia nem elogia o estado)
# ======================================================================
# Foto do carro do cliente: o Léo não avalia nem elogia o estado.
ELOGIO_DO_ESTADO = re.compile(
    r"\bbem\s+(conservad\w*|cuidad\w*)|\b(otimo|excelente|bom|perfeito|lindo|belo)\s+estado\b"
    r"|\bestado\s+(impecavel|otimo|excelente|perfeito)\b|\bimpecave\w*|\bmuito\s+conservad\w*"
    r"|\bparece\s+(estar\s+)?(muito\s+)?(bem|otimo|novo|novinho|conservad\w*)\b|\bnovinho\b")
FRASE_FOTO_CARRO = "Obrigado pela foto!"

# Pergunta sobre a loja aceitar troca (quando o cadastro não diz).
_PERGUNTA_TROCA = re.compile(r"\b(aceita\w*|pega\w*|recebe\w*|trabalha\w*\s+com)\b[^.!?]{0,30}\btroca\b"
                             r"|\bdar\b[^.!?]{0,30}\bna\s+troca\b|\b(da|daria)\s+pra\s+trocar\b|\btroca\s+(o|a|meu|minha)\b")

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


@_mantem_linhas
def tirar_elogio_do_estado(resposta: str) -> tuple[str, bool]:
    """Foto do carro do cliente: tira as frases que avaliam/elogiam o estado.
    Se não sobrar nada, fica só "Obrigado pela foto!"."""
    frases = _frases_originais(resposta)
    ficam = [f for f in frases if not ELOGIO_DO_ESTADO.search(_sem_acento(f))]
    if len(ficam) == len(frases):
        return resposta, False
    return (" ".join(ficam) if ficam else FRASE_FOTO_CARRO), True


# N5b (item 10): palavras de estado que também saem da descrição da foto.
_ESTADO_NA_DESCRICAO = re.compile(r"\bconservacao\b|\bboas?\s+condic\w*|\bconservad\w*|\bbrilhant\w*"
                                  r"|\bcuidad\w*|\bzerad\w*|\bimpecave\w*|\btinindo\b|\bnovinho\b")


def tirar_elogio_da_descricao(descricao: str) -> str:
    """Descrição da foto do carro sem julgamento de estado ("bom estado", "bem conservado",
    "boas condições", "brilhante"). Só as palavras de estado saem; modelo, cor e riscos ficam."""
    texto = str(descricao or "")
    sem = _sem_acento(texto)
    if not ELOGIO_DO_ESTADO.search(sem) and not _ESTADO_NA_DESCRICAO.search(sem):
        return texto
    trechos = [(m.start(), m.end()) for r in (ELOGIO_DO_ESTADO, _ESTADO_NA_DESCRICAO) for m in r.finditer(sem)]
    trechos.sort()
    saida, pos = [], 0
    for ini, fim_ in trechos:                  # sem acento e original têm o mesmo tamanho
        if ini >= pos:
            saida.append(texto[pos:ini])
            pos = fim_
    saida.append(texto[pos:])
    novo = "".join(saida)
    # sobras: "em ," / "e ," / "muito ," / "de conservação" sem nada
    anterior = None
    while anterior != novo:                    # "em excelente estado de conservação" -> "em  de " -> ""
        anterior = novo
        novo = re.sub(r"\s*\b(em|e|com|muito|bem|de|num|em um|em uma)\s*(?=[,;.]|$)", "", novo,
                      flags=re.IGNORECASE).rstrip()
    novo = re.sub(r"\s*,\s*(,\s*)+", ", ", novo)
    novo = re.sub(r"\s+([,;.])", r"\1", novo)
    novo = re.sub(r"\s{2,}", " ", novo).strip(" ,.;")
    return novo


def pergunta_se_aceita_troca(texto: str) -> bool:
    return bool(_PERGUNTA_TROCA.search(_sem_acento(texto)))


# ======================================================================
# L12: estado do carro
# ======================================================================
# Frase que afirma estado/qualidade de carro do estoque. Só fica se o fato vier da ficha
# (o que as ferramentas devolveram no turno); hoje a ficha não tem estado, então sai.
ESTADO_AFIRMADO = re.compile(
    r"\bbem\s+(conservad\w*|cuidad\w*)|\bconservadissim\w*|\bmuito\s+conservad\w*"
    r"|\b(otimo|excelente|bom|perfeito|impecavel)\s+estado\b|\bestado\s+(impecavel|otimo|excelente|perfeito)\b"
    r"|\bimpecave\w*|\brevisad[oa]s?\b|\b(unico|um\s+so)\s+dono\b|\bnunca\s+(bateu|foi\s+batid\w*)"
    r"|\bsem\s+(batida\w*|detalhe\w*|nenhum\s+detalhe|arranh\w*)|\btodo\s+original\b"
    r"|\b(excelente|otimo|belo|lindo)\s+carro\b|\bcarro\s+(excelente|impecavel|perfeito)\b|\bnovinho\b")
FRASE_ESTADO = "O estado do carro o pessoal da equipe confirma, e você pode ver pessoalmente aqui na loja."


def _estado_com_assunto(original: str) -> str:
    """N5: se a frase cortada falava de histórico/leilão/laudo/IPVA, a equipe confirma ESSE assunto."""
    assunto = assunto_da_frase(original)
    if not assunto or assunto == "a vistoria":
        return FRASE_ESTADO
    return f"O pessoal da equipe confirma {assunto} com você, e você pode ver o carro pessoalmente aqui na loja."
ESTADO_VERIFICADO = re.compile(r"\b(verificac\w*|vistori\w*|inspec\w*|revis(ao|oes|ad\w*)|garant(ir|o|imos)\s+que)")
ELOGIO_DE_CARRO = re.compile(r"\b(excelente|otimo|belo|lindo)\s+carro\b|\bcarro\s+(excelente|impecavel|perfeito)\b"
                             r"|\bnovinho\b|\bimpecave\w*|\bbem\s+(conservad\w*|cuidad\w*)|\bconservadissim\w*")


_VIRADA = re.compile(r"\b(mas|porem|contudo|entretanto|so\s+que)\b")


def _negacao_perto(frase_normal: str, inicio: int) -> bool:
    antes = frase_normal[max(0, inicio - 40):inicio]
    viradas = list(_VIRADA.finditer(antes))
    if viradas:
        antes = antes[viradas[-1].end():]
    return bool(_NEGA.search(antes))


@_mantem_linhas
def cortar_estado_inventado(resposta: str, ficha: str = "", substituir: bool = True) -> tuple[str, bool]:
    """Corta a frase que afirma estado/qualidade do carro sem estar na ficha do turno.
    A primeira vira FRASE_ESTADO; pergunta e negação ficam.
    M1 (L13): pega também verificação/vistoria/inspeção/revisão/"garanto que" ligados ao carro ou
    ao estoque. Elogio ("excelente carro", "bem conservado") ou conversa de pós-venda
    (substituir=False): a frase só sai, sem frase no lugar."""
    ficha_n = _sem_acento(ficha)
    saida, trocou = [], False
    for frase in _frases_originais(resposta):
        f = _sem_acento(frase)
        achado = ESTADO_AFIRMADO.search(f)
        if not achado and _PALAVRA_DE_CARRO.search(f):
            achado = ESTADO_VERIFICADO.search(f)
        # "nunca bateu" é a própria afirmação. L14: a negação só protege se estiver PERTO, antes do
        # trecho (até 40 letras) e sem "mas/porém" no meio ("não tenho acesso..., mas posso te
        # garantir que todos passam por verificação" é afirmação).
        if (not achado or f.rstrip().endswith("?") or _negacao_perto(f, achado.start())
                or achado.group(0) in ficha_n):
            saida.append(frase)
            continue
        if not trocou and substituir and not ELOGIO_DE_CARRO.search(f):
            saida.append(_estado_com_assunto(frase))                  # N5: mantém o assunto
        trocou = True
    if trocou and not saida:
        return "", True
    return (" ".join(saida) if trocou else resposta), trocou


# ======================================================================
# Agenda: test-drive lembra a CNH (saiu de app/core/pos_processamento.py, passo "agendamento")
# ======================================================================
FRASE_CNH = "Para o test-drive, traga sua CNH válida."


def depois_da_agenda(resposta: str, agenda: str) -> str:
    """A agenda gravou neste turno: test-drive sem a CNH na resposta ganha a frase da CNH."""
    if "test-drive" in agenda.lower() and "cnh" not in resposta.lower():
        return f"{resposta} {FRASE_CNH}"
    return resposta


# ======================================================================
# Chamado pelo código: troca (saiu de app/core/turno.py). A troca vem ANTES das regras do motor.
# ======================================================================
MOTIVO_ACEITA_TROCA = "Cliente perguntou se a loja aceita troca (não está no cadastro)."
MOTIVO_VALOR_TROCA = "Cliente pediu valor da troca."


def aceita_troca(loja_id: int) -> str:
    """O que o cadastro diz sobre aceitar carro na troca ("sim", "nao", "nao_informado")."""
    try:
        from app.lojas import carregar_loja
        return str(carregar_loja(loja_id).get("aceita_troca") or "nao_informado")
    except Exception:
        from app.log import logger
        logger("turno").exception("Não consegui ler 'aceita troca' da loja.")
        return "nao_informado"


def motivo_da_troca(texto: str, aceita: str) -> tuple[str, str] | None:
    if aceita == "nao_informado" and pergunta_se_aceita_troca(texto):
        return MOTIVO_ACEITA_TROCA, "guarda_aceita_troca"
    if pediu_valor_da_troca(texto):
        return MOTIVO_VALOR_TROCA, "guarda_troca"
    return None


def motivo_do_chamado(texto: str, loja_id: int) -> tuple[str, str] | None:
    """Gancho do motor (passo 10): o motivo do ramo, ou None (aí valem as regras do motor)."""
    return motivo_da_troca(texto, aceita_troca(loja_id))


def motivo_do_chamado_pelo_codigo(texto: str, resposta: str,
                                  aceita_troca: str = "sim") -> tuple[str, str] | None:
    """(motivo, nome da guarda) ou None. Ordem: valor da troca, assunto, promessa.
    A regra inteira de uma loja de carros: a troca (deste ramo) e depois as regras do motor."""
    from app.core.turno import motivo_do_chamado_do_motor
    return motivo_da_troca(texto, aceita_troca) or motivo_do_chamado_do_motor(texto, resposta)


# ======================================================================
# Foto do carro do cliente: a troca registrada ganha "foto recebida" (saiu de app/core/turno.py)
# ======================================================================
def anotar_foto_do_cliente(loja_id: int, lead_id: str, descricao: str) -> None:
    """Se o cliente já tem troca registrada, a última ganha 'foto recebida: ...'."""
    from banco import conectar
    if not descricao:
        return
    conexao = conectar()
    try:
        linha = conexao.execute("SELECT id, estado FROM trocas WHERE loja_id = ? AND lead_id = ? "
                                "ORDER BY id DESC LIMIT 1", (loja_id, lead_id)).fetchone()
        if linha is None:
            return
        nota = f"foto recebida: {descricao}"
        estado = (linha["estado"] or "").strip()
        if nota not in estado:
            estado = f"{estado} | {nota}" if estado else nota
            conexao.execute("UPDATE trocas SET estado = ? WHERE id = ?", (estado, linha["id"]))
            conexao.commit()
    finally:
        conexao.close()

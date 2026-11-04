"""
Checklist de implantação e "Colocar no ar" (S2 da Fase 3; decisão A6).

Cada item é:
- AUTOMÁTICO: o sistema confere sozinho, na hora, olhando o banco e o
  servidor (nada fica gravado);
- MANUAL: o operador marca, com autor e data (tabela checklist_implantacao,
  migração 13).
E tem um nível: OBRIGATÓRIO (bloqueia o "Colocar no ar"), RECOMENDADO ou OPCIONAL.

A regra fica AQUI, não na tela: colocar_no_ar() deste arquivo recusa
(ChecklistIncompleto) enquanto faltar item obrigatório e pede o nome da loja
digitado (ConfirmacaoErrada). Passando, chama app/estado_loja.colocar_no_ar,
que grava o estado e o Registro na mesma transação.

Marcar e desmarcar item manual: só o operador, com Registro na mesma
transação. Sem Streamlit: a tela Resumo só mostra e chama.
"""
from __future__ import annotations

from dataclasses import dataclass

from banco import conectar
from app.chaves import exigir_loja
from app.conhecimento import listar_documentos
from app.credenciais import SemCredencial, credencial_whatsapp, token_telegram
from app.estado_loja import SoOperador, esta_no_ar, listar_numeros_de_teste
from app.estado_loja import colocar_no_ar as _colocar_no_ar_no_estado
from app.lojas import LojaNaoEncontrada, carregar_loja, pendentes
from app.relogio import agora_utc, para_banco
from app.usuarios import listar_usuarios

AUTOMATICO = "automatico"
MANUAL = "manual"
OBRIGATORIO = "obrigatorio"
RECOMENDADO = "recomendado"
OPCIONAL = "opcional"
ROTULOS_NIVEL = {OBRIGATORIO: "Obrigatório", RECOMENDADO: "Recomendado", OPCIONAL: "Opcional"}
MAX_OBSERVACAO = 200
SEGMENTO_COM_ESTOQUE = "veiculos"

# Campos mínimos (proposta do S2, a validar pelo analista).
CHAVES_IDENTIDADE = ("nome_agente", "tom")
CHAVES_HORARIO = ("fuso", "atendimento.horario_humano", "atendimento.dias_humano")
ROTULOS_CAMPO = {
    "nome_agente": "nome do assistente",
    "tom": "tom de voz",
    "fuso": "fuso horário",
    "atendimento.horario_humano": "horário de atendimento",
    "atendimento.dias_humano": "dias de atendimento",
}


@dataclass(frozen=True)
class Item:
    chave: str
    rotulo: str
    como: str
    nivel: str
    ajuda: str


ITENS = (
    Item("loja_criada", "Loja criada", AUTOMATICO, OBRIGATORIO,
         "A loja existe e começou em teste."),
    Item("identidade", "Identidade preenchida", AUTOMATICO, OBRIGATORIO,
         "Cidade preenchida; nome do assistente e tom de voz confirmados em Configuração."),
    Item("horario", "Horário e fuso", AUTOMATICO, OBRIGATORIO,
         "Fuso, horário e dias de atendimento confirmados em Configuração."),
    Item("equipe", "Equipe", AUTOMATICO, OBRIGATORIO,
         "Ao menos uma pessoa ativa que recebe aviso (com Telegram), em Usuários."),
    Item("estoque", "Estoque", AUTOMATICO, OBRIGATORIO,
         "Ao menos um carro disponível, em Estoque."),
    Item("canal", "Canal conectado", AUTOMATICO, OBRIGATORIO,
         "Canal ativo e chave encontrada no servidor, em Lojas e canais."),
    Item("numeros_teste", "Números de teste", AUTOMATICO, OBRIGATORIO,
         "Ao menos um número de teste ativo."),
    Item("teste_conversa", "Teste de conversa completo", MANUAL, OBRIGATORIO,
         "Marque depois de conversar do começo ao fim com um número de teste."),
    Item("plano_contrato", "Plano confirmado em contrato", MANUAL, OBRIGATORIO,
         "Marque quando o plano e os limites estiverem confirmados no contrato."),
    Item("conhecimento", "Conhecimento", AUTOMATICO, RECOMENDADO,
         "Ao menos um documento em Conhecimento."),
    Item("base_importada", "Base de clientes importada", MANUAL, OPCIONAL,
         "Marque se a loja importou a base de clientes."),
    Item("modelos_meta", "Modelos da Meta aprovados", MANUAL, OPCIONAL,
         "Só é exigido para ligar o envio proativo real."),
)
_POR_CHAVE = {i.chave: i for i in ITENS}
assert len(_POR_CHAVE) == len(ITENS), "chave repetida no checklist"


class ItemInvalido(ValueError):
    pass


class ConfirmacaoErrada(ValueError):
    pass


class ChecklistIncompleto(ValueError):
    def __init__(self, faltando: list[str]):
        self.faltando = list(faltando)
        super().__init__("Ainda falta: " + ", ".join(self.faltando) + ".")


def _exigir_operador(loja_id, mensagem: str):
    from app.registro import conferir_ator     # aqui dentro: evita import circular
    ator = conferir_ator(loja_id)
    if ator.papel != "operador":
        raise SoOperador(mensagem)
    return ator


def _plural(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


def _falta(nomes: list[str]) -> tuple[bool, str]:
    if not nomes:
        return True, ""
    return False, "Falta: " + ", ".join(nomes) + "."


def _canal_conectado(loja_id: int) -> bool:
    for conferir in (credencial_whatsapp, token_telegram):
        try:
            conferir(loja_id)
            return True
        except SemCredencial:
            continue
    return False


def _carros_disponiveis(loja_id: int) -> int:
    conexao = conectar()
    try:
        return conexao.execute(
            "SELECT COUNT(*) FROM estoque WHERE loja_id = ? AND status = 'disponivel'",
            (loja_id,)).fetchone()[0]
    finally:
        conexao.close()


def _automaticos(loja) -> dict[str, tuple[bool, str]]:
    """(feito, detalhe) de cada item automático."""
    pendente = set(pendentes(loja))
    identidade = [] if str(loja.get("cidade") or "").strip() else ["cidade"]
    identidade += [ROTULOS_CAMPO[c] for c in CHAVES_IDENTIDADE if c in pendente]
    horario = [ROTULOS_CAMPO[c] for c in CHAVES_HORARIO if c in pendente]

    equipe = sum(1 for u in listar_usuarios(loja.id) if u["contato_telegram"])
    numeros = len(listar_numeros_de_teste(loja.id))
    documentos = len(listar_documentos(loja.id))
    if loja.segmento != SEGMENTO_COM_ESTOQUE:
        estoque = (True, "Não se aplica a este segmento.")
    else:
        carros = _carros_disponiveis(loja.id)
        estoque = (carros > 0, _plural(carros, "carro disponível", "carros disponíveis") + ".")
    canal = _canal_conectado(loja.id)

    return {
        "loja_criada": (True, ""),
        "identidade": _falta(identidade),
        "horario": _falta(horario),
        "equipe": (equipe > 0, _plural(equipe, "pessoa recebe aviso", "pessoas recebem aviso") + "."),
        "estoque": estoque,
        "canal": (canal, "Canal ativo e chave encontrada." if canal
                  else "Nenhum canal ativo com a chave encontrada no servidor."),
        "numeros_teste": (numeros > 0, _plural(numeros, "número de teste ativo",
                                               "números de teste ativos") + "."),
        "conhecimento": (documentos > 0, _plural(documentos, "documento", "documentos") + "."),
    }


def _marcados(loja_id: int) -> dict[str, dict]:
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT item, marcado_por, marcado_em, observacao FROM checklist_implantacao "
            "WHERE loja_id = ?", (loja_id,)).fetchall()
    finally:
        conexao.close()
    return {l["item"]: dict(l) for l in linhas}


def checklist(loja_id) -> list[dict]:
    """Os itens na ordem da tela, cada um dizendo se está feito.
    marcado_em vem em UTC (formato do banco); a tela converte."""
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    automaticos = _automaticos(loja)
    marcados = _marcados(loja_id)
    saida = []
    for item in ITENS:
        marca = marcados.get(item.chave) if item.como == MANUAL else None
        if item.como == MANUAL:
            feito, detalhe = marca is not None, ""
        else:
            feito, detalhe = automaticos[item.chave]
        saida.append({
            "chave": item.chave, "rotulo": item.rotulo, "como": item.como,
            "nivel": item.nivel, "nivel_rotulo": ROTULOS_NIVEL[item.nivel],
            "ajuda": item.ajuda, "feito": bool(feito), "detalhe": detalhe,
            "marcado_por": marca["marcado_por"] if marca else None,
            "marcado_em": marca["marcado_em"] if marca else None,
            "observacao": marca["observacao"] if marca else None,
        })
    return saida


def faltando_para_o_ar(loja_id) -> list[str]:
    """Rótulos dos itens obrigatórios que ainda não estão feitos."""
    return [i["rotulo"] for i in checklist(loja_id)
            if i["nivel"] == OBRIGATORIO and not i["feito"]]


def pode_colocar_no_ar(loja_id) -> bool:
    return not faltando_para_o_ar(loja_id)


def _item_manual(item) -> Item:
    achado = _POR_CHAVE.get(item)
    if achado is None:
        raise ItemInvalido(f"O item '{item}' não existe no checklist.")
    if achado.como != MANUAL:
        raise ItemInvalido(f"'{achado.rotulo}' é conferido sozinho pelo sistema.")
    return achado


def marcar_item(loja_id, item, observacao="", agora=None) -> bool:
    """Só o operador. True se marcou; False se já estava marcado (nada gravado)."""
    loja_id = exigir_loja(loja_id)
    ator = _exigir_operador(loja_id, "Só o operador marca itens do checklist.")
    _item_manual(item)
    texto = " ".join(str(observacao or "").split())
    if len(texto) > MAX_OBSERVACAO:
        raise ItemInvalido(f"Observação com mais de {MAX_OBSERVACAO} caracteres.")
    from app.registro import registrar          # aqui dentro: evita import circular
    momento = para_banco(agora or agora_utc())
    conexao = conectar()
    try:
        if not conexao.execute("SELECT 1 FROM lojas WHERE id = ?", (loja_id,)).fetchone():
            raise LojaNaoEncontrada(f"Loja {loja_id} não existe.")
        cursor = conexao.execute(
            "INSERT INTO checklist_implantacao (loja_id, item, marcado_por, marcado_em, observacao) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (loja_id, item) DO NOTHING",
            (loja_id, item, ator.pessoa, momento, texto or None))
        if cursor.rowcount == 0:
            return False                         # já estava marcado
        registrar("marcar_item_implantacao", loja_id, None,
                  {"item": item, "observacao": texto or None},
                  conexao=conexao, alvo=f"item:{item}", agora=agora)
        conexao.commit()
    finally:
        conexao.close()
    return True


def desmarcar_item(loja_id, item, agora=None) -> bool:
    """Só o operador. True se desmarcou; False se não estava marcado."""
    loja_id = exigir_loja(loja_id)
    _exigir_operador(loja_id, "Só o operador desmarca itens do checklist.")
    _item_manual(item)
    from app.registro import registrar          # aqui dentro: evita import circular
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT marcado_por, marcado_em, observacao FROM checklist_implantacao "
            "WHERE loja_id = ? AND item = ?", (loja_id, item)).fetchone()
        if linha is None:
            return False
        conexao.execute("DELETE FROM checklist_implantacao WHERE loja_id = ? AND item = ?",
                        (loja_id, item))
        registrar("desmarcar_item_implantacao", loja_id,
                  {"item": item, "marcado_por": linha["marcado_por"],
                   "marcado_em": linha["marcado_em"], "observacao": linha["observacao"]},
                  {"item": item}, conexao=conexao, alvo=f"item:{item}", agora=agora)
        conexao.commit()
    finally:
        conexao.close()
    return True


def colocar_no_ar(loja_id, nome_digitado, agora=None) -> bool:
    """Só o operador, com o nome da loja digitado e TODOS os obrigatórios feitos.
    True se colocou; False se a loja já estava no ar."""
    loja_id = exigir_loja(loja_id)
    _exigir_operador(loja_id, "Só o operador coloca a loja no ar.")
    loja = carregar_loja(loja_id)
    digitado = " ".join(str(nome_digitado or "").split()).casefold()
    if digitado != " ".join(loja.nome.split()).casefold():
        raise ConfirmacaoErrada("O nome digitado não é o nome da loja. Nada foi mudado.")
    if esta_no_ar(loja_id):
        return False
    faltando = faltando_para_o_ar(loja_id)
    if faltando:
        raise ChecklistIncompleto(faltando)
    return _colocar_no_ar_no_estado(loja_id, agora=agora)

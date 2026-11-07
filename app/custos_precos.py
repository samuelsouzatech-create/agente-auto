"""
Custos e preços (S8 da Fase 3): o que a tela do nível Geral mostra e faz.

Sem Streamlit. A tela (paginas/operador/custos_precos.py) só mostra o que
vem pronto daqui e chama as ações. Nada de SQL nem de conta na tela.

Leituras (só leem; cada uma faz UMA consulta ao banco):
- custos_do_mes: tabela por loja no mês escolhido (conversas, custo de IA,
  custo da Meta, total e custo por conversa) e a linha de total. O mês é o
  do horário de Brasília (o nível Geral usa Brasília, como o Registro).
  É o custo CHEIO, o que o fornecedor cobra (regra do P7c).
- ultimos_12_meses: uma linha por mês, todas as lojas ou uma só, numa
  consulta agrupada por mês (decisão 2A).
- implantacao_de_todas: o custo do período de teste de cada loja, à parte,
  com a mesma regra de custos.resumo_implantacao (P7c), numa consulta só (3A).
- historico_de_precos: os preços com vigência (em vigor, substituído, agendado).

Ações (só o operador; cada uma vai para o Registro SEM loja, porque vale
para todas as lojas; decisão 1A):
- cadastrar_preco e apagar_preco: o preço e o recálculo dos custos desde a
  data de vigência ficam na MESMA transação (5A). Se o recálculo falhar, o
  preço não é salvo (nem apagado). Nunca fica preço novo com custo velho.
- recalcular_periodo / recalcular_mes: reescreve só os custos (valores
  derivados dos tokens e das mensagens gravados). Rodar duas vezes dá o
  mesmo resultado (4A).

Anotado, fora do S8: o preço de cada linha é escolhido pelo dia em UTC
(custos.calcular_custo usa criado_em[:10]). Mudar isso muda o cálculo.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from banco import conectar
from app import custos, precos
from app.chaves import exigir_loja
from app.estado_loja import ACAO_NO_AR, EM_TESTE, NO_AR, SoOperador
from app.estado_loja import ROTULOS as ROTULOS_ESTADO
from app.registro import conferir_ator, registrar
from app.registro_leitura import FUSO_GERAL
from app.relogio import agora_utc, do_banco, limites_do_dia_em_utc

TODAS = 0                      # na escolha de loja dos 12 meses: todas as lojas
MESES_NO_HISTORICO = 12
VAZIO = "—"
NOMES_DOS_MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
                   "agosto", "setembro", "outubro", "novembro", "dezembro")
ACOES_S8 = ("cadastrar_preco", "apagar_preco", "recalcular_custos")
ACAO_CADASTRAR, ACAO_APAGAR, ACAO_RECALCULAR = ACOES_S8
EM_VIGOR, SUBSTITUIDO, AGENDADO = "Em vigor", "Substituído", "Agendado"
SIMBOLO = {"USD": "US$", "BRL": "R$"}
FIM_SEM_CORTE = custos.FIM_SEM_CORTE


class SoOperadorPrecos(SoOperador):
    """Mudar preço e recalcular custos é só do operador."""


# ------------------------------------------------------------ texto e datas

def dinheiro(valor, casas: int = 2, moeda: str = "BRL") -> str:
    texto = f"{float(valor or 0):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{SIMBOLO.get(moeda, moeda)} {texto}"


def _data(dia) -> str:
    return date.fromisoformat(str(dia)[:10]).strftime("%d/%m/%Y")


def _brasilia() -> ZoneInfo:
    return ZoneInfo(FUSO_GERAL)


def hoje_brasilia(agora=None) -> date:
    return (agora or agora_utc()).astimezone(_brasilia()).date()


def nome_do_mes(ano: int, mes: int) -> str:
    return f"{NOMES_DOS_MESES[mes - 1]}/{ano}"


def _mes_anterior(ano, mes):
    return (ano - 1, 12) if mes == 1 else (ano, mes - 1)


def _mes_seguinte(ano, mes):
    return (ano + 1, 1) if mes == 12 else (ano, mes + 1)


def meses_para_escolher(agora=None) -> list[tuple[int, int]]:
    """Os últimos 12 meses (o atual primeiro), no horário de Brasília."""
    hoje = hoje_brasilia(agora)
    meses, am = [], (hoje.year, hoje.month)
    for _ in range(MESES_NO_HISTORICO):
        meses.append(am)
        am = _mes_anterior(*am)
    return meses


def _inicio_do_mes_utc(ano, mes) -> str:
    return limites_do_dia_em_utc(FUSO_GERAL, date(ano, mes, 1))[0]


def intervalo_do_mes(ano: int, mes: int) -> tuple[str, str]:
    """Começo e fim (UTC, formato do banco) de um mês do horário de Brasília."""
    return _inicio_do_mes_utc(ano, mes), _inicio_do_mes_utc(*_mes_seguinte(ano, mes))


def _deslocamento_sql(agora=None) -> str:
    """Diferença de Brasília para UTC, no formato do SQLite (ex.: '-3 hours').
    Brasília não tem horário de verão desde 2019."""
    segundos = (agora or agora_utc()).astimezone(_brasilia()).utcoffset().total_seconds()
    return f"{int(segundos // 3600):+d} hours"


def _conta(conversas, ia, meta, incompletas=0) -> dict:
    ia, meta = round(ia or 0, 6), round(meta or 0, 6)
    total = round(ia + meta, 6)
    conversas = int(conversas or 0)
    return {"conversas": conversas, "custo_ia": ia, "custo_meta": meta, "custo_total": total,
            "custo_por_conversa": round(total / conversas, 6) if conversas else 0.0,
            "incompletas": int(incompletas or 0)}


# ------------------------------------------------------------ mês por loja

_SQL_MES = """
    SELECT l.id, l.nome, e.estado,
           COUNT(DISTINCT u.lead_id) AS conversas,
           COALESCE(SUM(u.custo_llm), 0) AS custo_ia,
           COALESCE(SUM(u.custo_meta), 0) AS custo_meta,
           COALESCE(SUM(CASE WHEN u.custo_completo = 0 THEN 1 ELSE 0 END), 0) AS incompletas
    FROM lojas l
    LEFT JOIN estado_lojas e ON e.loja_id = l.id
    LEFT JOIN uso_custos u ON u.loja_id = l.id AND u.criado_em >= ? AND u.criado_em < ?
    GROUP BY l.id, l.nome, e.estado
    ORDER BY l.id"""


def custos_do_mes(ano: int, mes: int) -> dict:
    """Custo cheio do mês (Brasília) por loja e o total. Uma consulta."""
    inicio, fim = intervalo_do_mes(ano, mes)
    con = conectar()
    try:
        linhas = con.execute(_SQL_MES, (inicio, fim)).fetchall()
    finally:
        con.close()
    lojas = []
    for l in linhas:
        item = _conta(l["conversas"], l["custo_ia"], l["custo_meta"], l["incompletas"])
        estado = l["estado"] or EM_TESTE
        item.update(loja_id=l["id"], loja=l["nome"], situacao=ROTULOS_ESTADO.get(estado, estado))
        lojas.append(item)
    total = _conta(sum(l["conversas"] for l in lojas), sum(l["custo_ia"] for l in lojas),
                   sum(l["custo_meta"] for l in lojas), sum(l["incompletas"] for l in lojas))
    return {"ano": ano, "mes": mes, "lojas": lojas, "total": total}


def _linha_custo(nome, situacao, c) -> dict:
    return {"Loja": nome, "Situação": situacao, "Conversas": c["conversas"],
            "Custo de IA": dinheiro(c["custo_ia"], 4),
            "Custo da Meta": dinheiro(c["custo_meta"], 4),
            "Total": dinheiro(c["custo_total"]),
            "Custo por conversa": dinheiro(c["custo_por_conversa"], 4),
            "Com preço faltando": c["incompletas"]}


def linhas_do_mes(resultado: dict) -> list[dict]:
    """Linhas prontas para a tabela: uma por loja e a linha Total no fim."""
    linhas = [_linha_custo(l["loja"], l["situacao"], l) for l in resultado["lojas"]]
    return linhas + [_linha_custo("Total", "", resultado["total"])]


# ------------------------------------------------------------ últimos 12 meses

def ultimos_12_meses(loja=None, agora=None) -> list[dict]:
    """Uma linha por mês (o mais novo primeiro). loja vazia = todas as lojas.
    UMA consulta, agrupada pelo mês de Brasília."""
    meses = meses_para_escolher(agora)
    inicio = _inicio_do_mes_utc(*meses[-1])
    fim = _inicio_do_mes_utc(*_mes_seguinte(*meses[0]))
    sql = ("SELECT strftime('%Y-%m', datetime(criado_em, ?)) AS mes, "
           "COUNT(DISTINCT loja_id || ':' || lead_id) AS conversas, "
           "COALESCE(SUM(custo_llm), 0) AS custo_ia, COALESCE(SUM(custo_meta), 0) AS custo_meta "
           "FROM uso_custos WHERE criado_em >= ? AND criado_em < ?")
    parametros = [_deslocamento_sql(agora), inicio, fim]
    if loja:
        sql += " AND loja_id = ?"
        parametros.append(exigir_loja(loja))
    sql += " GROUP BY mes"
    con = conectar()
    try:
        por_mes = {l["mes"]: l for l in con.execute(sql, parametros).fetchall()}
    finally:
        con.close()
    saida = []
    for ano, mes in meses:
        l = por_mes.get(f"{ano:04d}-{mes:02d}")
        item = _conta(l["conversas"], l["custo_ia"], l["custo_meta"]) if l else _conta(0, 0, 0)
        item.update(ano=ano, mes=mes)
        saida.append(item)
    return saida


def linhas_dos_12_meses(meses: list[dict]) -> list[dict]:
    return [{"Mês": nome_do_mes(m["ano"], m["mes"]), "Conversas": m["conversas"],
             "Custo de IA": dinheiro(m["custo_ia"], 4),
             "Custo da Meta": dinheiro(m["custo_meta"], 4),
             "Total": dinheiro(m["custo_total"]),
             "Custo por conversa": dinheiro(m["custo_por_conversa"], 4)} for m in meses]


def opcoes_de_loja() -> list[tuple[int, str]]:
    from app.lojas_admin import listar_lojas      # aqui dentro: evita import circular
    return [(TODAS, "Todas as lojas")] + [(l["id"], l["nome"]) for l in listar_lojas()]


# ------------------------------------------------------------ implantação (P7c)

_SQL_IMPLANTACAO = """
    WITH base AS (
        SELECT l.id, l.nome,
               CASE WHEN e.estado = ? THEN 0 ELSE 1 END AS em_teste,
               CASE WHEN e.estado = ? AND e.no_ar_em IS NOT NULL AND EXISTS (
                        SELECT 1 FROM registro_acoes r WHERE r.loja_id = l.id AND r.acao = ?)
                    THEN substr(e.no_ar_em, 1, 19) END AS ate
        FROM lojas l LEFT JOIN estado_lojas e ON e.loja_id = l.id)
    SELECT b.id, b.nome, b.em_teste, b.ate,
           COUNT(DISTINCT u.lead_id) AS conversas,
           COALESCE(SUM(u.custo_llm), 0) AS custo_ia,
           COALESCE(SUM(u.custo_meta), 0) AS custo_meta
    FROM base b
    LEFT JOIN uso_custos u ON u.loja_id = b.id
         AND u.criado_em < CASE WHEN b.em_teste = 1 THEN ? ELSE b.ate END
    WHERE b.em_teste = 1 OR b.ate IS NOT NULL
    GROUP BY b.id, b.nome, b.em_teste, b.ate
    ORDER BY b.id"""


def implantacao_de_todas() -> list[dict]:
    """Custo do período de teste de cada loja, com a regra de
    custos.resumo_implantacao (P7c), numa consulta só. Lojas que já existiam
    antes do P7 não têm implantação e não aparecem."""
    con = conectar()
    try:
        linhas = con.execute(_SQL_IMPLANTACAO, (NO_AR, NO_AR, ACAO_NO_AR, FIM_SEM_CORTE)).fetchall()
    finally:
        con.close()
    saida = []
    for l in linhas:
        item = _conta(l["conversas"], l["custo_ia"], l["custo_meta"])
        item.update(loja_id=l["id"], loja=l["nome"], em_teste=bool(l["em_teste"]), ate=l["ate"])
        saida.append(item)
    return saida


def linhas_da_implantacao(lista: list[dict]) -> list[dict]:
    linhas = []
    for i in lista:
        if i["em_teste"]:
            situacao = "Ainda em teste"
        else:
            situacao = "No ar desde " + do_banco(i["ate"]).astimezone(_brasilia()).strftime("%d/%m/%Y")
        linhas.append({"Loja": i["loja"], "Situação": situacao, "Conversas": i["conversas"],
                       "Custo de IA": dinheiro(i["custo_ia"], 4),
                       "Custo da Meta": dinheiro(i["custo_meta"], 4),
                       "Total": dinheiro(i["custo_total"])})
    return linhas


# ------------------------------------------------------------ preços (leitura)

def precos_faltando(agora=None) -> list[str]:
    return [precos.ITENS[i]["rotulo"] for i in precos.faltando(hoje_brasilia(agora))]


def itens_de_preco() -> list[tuple[str, str, str]]:
    """(item, texto para a tela, moeda sugerida)."""
    return [(chave, f'{d["rotulo"]} (por {d["unidade"]})', d["moeda"])
            for chave, d in precos.ITENS.items()]


def historico_de_precos(agora=None) -> list[dict]:
    """Todos os preços, com a situação de cada um hoje (Brasília)."""
    hoje = hoje_brasilia(agora).isoformat()
    saida, com_vigor = [], set()
    for p in precos.listar_precos():                 # por item, o mais novo primeiro
        desde = str(p["vigente_desde"])[:10]
        if desde > hoje:
            situacao = AGENDADO
        elif p["item"] not in com_vigor:
            situacao = EM_VIGOR
            com_vigor.add(p["item"])
        else:
            situacao = SUBSTITUIDO
        rotulo = precos.ITENS.get(p["item"], {}).get("rotulo", p["item"])
        saida.append({**p, "situacao": situacao, "rotulo": rotulo})
    return saida


def linhas_de_precos(lista: list[dict]) -> list[dict]:
    return [{"Item": p["rotulo"], "Unidade": f'por {p["unidade"]}',
             "Valor": dinheiro(p["valor"], 4, p["moeda"]), "Vale desde": _data(p["vigente_desde"]),
             "Situação": p["situacao"]} for p in lista]


def rotulo_para_apagar(p: dict) -> str:
    return (f'{p["rotulo"]} · {dinheiro(p["valor"], 4, p["moeda"])} · '
            f'desde {_data(p["vigente_desde"])} · {p["situacao"]}')


# ------------------------------------------------------------ ações (só o operador)

def _exigir_operador():
    ator = conferir_ator(None)                       # sem ator: SemAtor
    if ator.papel != "operador":
        raise SoOperadorPrecos("Só o operador muda preços e recalcula custos.")
    return ator


def _descricao(item, valor, moeda, dia) -> dict:
    return {"preço": precos.ITENS.get(item, {}).get("rotulo", item),
            "valor": dinheiro(valor, 4, moeda), "vale_desde": _data(dia)}


def cadastrar_preco(item, valor, vigente_desde, moeda=None, agora=None) -> dict:
    """Salva o preço (ou corrige, se já existe na mesma data), recalcula os
    custos desde a data de vigência e grava no Registro: tudo numa transação."""
    _exigir_operador()
    try:
        dia = precos._data_iso(vigente_desde)
    except (TypeError, ValueError):
        dia = None
    con = conectar()
    try:
        anterior = None
        if dia and item in precos.ITENS:
            anterior = con.execute("SELECT valor, moeda FROM precos WHERE item = ? AND vigente_desde = ?",
                                   (item, dia)).fetchone()
        gravado = precos.cadastrar_preco(item, valor, vigente_desde, moeda, conexao=con)
        n = custos.recalcular_custos(inicio=f'{gravado["vigente_desde"]} 00:00:00', conexao=con)
        depois = _descricao(item, gravado["valor"], gravado["moeda"], gravado["vigente_desde"])
        depois["registros_recalculados"] = n
        antes = _descricao(item, anterior["valor"], anterior["moeda"], dia) if anterior else None
        registrar(ACAO_CADASTRAR, None, antes, depois, conexao=con, alvo="preço", agora=agora)
        con.commit()
    finally:
        con.close()
    return {"recalculados": n, "vigente_desde": _data(gravado["vigente_desde"]),
            "corrigiu": anterior is not None}


def apagar_preco(preco_id: int, agora=None) -> dict:
    """Apaga o preço; volta a valer o anterior do mesmo item. Recalcula os
    custos desde a data dele e grava no Registro: tudo numa transação."""
    _exigir_operador()
    con = conectar()
    try:
        p = con.execute("SELECT item, valor, moeda, vigente_desde FROM precos WHERE id = ?",
                        (preco_id,)).fetchone()
        if p is None:
            return {"apagado": False, "recalculados": 0}
        precos.apagar_preco(preco_id, conexao=con)
        dia = str(p["vigente_desde"])[:10]
        n = custos.recalcular_custos(inicio=f"{dia} 00:00:00", conexao=con)
        registrar(ACAO_APAGAR, None, _descricao(p["item"], p["valor"], p["moeda"], dia),
                  {"apagado": "sim", "registros_recalculados": n},
                  conexao=con, alvo="preço", agora=agora)
        con.commit()
    finally:
        con.close()
    return {"apagado": True, "recalculados": n}


def recalcular_periodo(inicio: date, fim: date, agora=None) -> int:
    """Recalcula os custos dos dias inicio..fim (Brasília, o fim entra).
    Só reescreve os custos; rodar de novo dá o mesmo resultado."""
    _exigir_operador()
    if inicio > fim:
        raise ValueError("O início do período precisa ser antes do fim.")
    ini = limites_do_dia_em_utc(FUSO_GERAL, inicio)[0]
    ate = limites_do_dia_em_utc(FUSO_GERAL, fim)[1]
    con = conectar()
    try:
        n = custos.recalcular_custos(inicio=ini, fim=ate, conexao=con)
        registrar(ACAO_RECALCULAR, None, None,
                  {"período": f"{inicio:%d/%m/%Y} a {fim:%d/%m/%Y}", "registros_recalculados": n},
                  conexao=con, alvo="custos", agora=agora)
        con.commit()
    finally:
        con.close()
    return n


def recalcular_mes(ano: int, mes: int, agora=None) -> int:
    primeiro = date(ano, mes, 1)
    ultimo = date.fromordinal(date(*_mes_seguinte(ano, mes), 1).toordinal() - 1)
    return recalcular_periodo(primeiro, ultimo, agora=agora)

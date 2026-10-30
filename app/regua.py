"""
Régua de pós-venda: o MOTOR (Etapa 2, Bloco 5A). Neutro ao segmento.

Três camadas:
  1. motor (este arquivo): copia a régua-modelo, agenda os passos de um
     acontecimento e cancela o que não deve mais sair. Não conhece carro.
  2. pacote do segmento: segmentos/<segmento>/reguas.json (réguas-modelo,
     com o vocabulário fechado de gatilhos).
  3. loja: a cópia dela em reguas/regua_passos (liga, desliga, muda prazo).

Quem envia é o job (app/jobs/pos_venda.py), pelo relógio.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone

from banco import conectar
from app.chaves import exigir_loja
from app.elegibilidade import proxima_abertura
from app.lojas import carregar_loja
from app.relogio import fuso, para_banco
from app.segmentos import pasta_do_segmento
from app.templates import carregar_modelos

ARQUIVO = "reguas.json"
TIPO = "pos_venda"
CONDICOES = ("todos", "avista", "financiado")
ACOES = ("enviar_modelo", "avisar_vendedor")
DIAS_POR_MES = 30.4375                 # 6 meses = 183 dias, 12 meses = 365 dias
MAX_DIAS = 3650
HORA_DO_ENVIO = time(10, 0)            # no fuso da loja; o horário de envio ajusta
TOLERANCIA_ATRASO = timedelta(days=3)  # passo que já passou disso não sai mais

MOTIVOS = {
    "data_passou": "A data deste passo já tinha passado quando a venda foi registrada",
    "antes_do_evento": "A data cairia antes da venda (ex.: financiamento de 12 meses ou menos)",
    "sem_data_fim_financiamento": "Venda financiada sem o prazo em meses",
    "problema": "O cliente relatou um problema e foi passado ao vendedor",
    "passo_desligado": "Passo desligado na régua da loja",
    "nao_contatar": "Pediu para não ser procurado",
    "sem_interesse": "Disse que não tem interesse",
}


class ReguaInvalida(ValueError):
    """O reguas.json do segmento tem algo fora do vocabulário."""


class ReguaInexistente(LookupError):
    pass


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


# ------------------------------------------------------------ réguas-modelo

def _ler(segmento: str) -> dict:
    caminho = pasta_do_segmento(segmento) / ARQUIVO
    if not caminho.is_file():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as erro:
        raise ReguaInvalida(f"{ARQUIVO} de {segmento}: JSON inválido ({erro})")
    if not isinstance(dados, dict):
        raise ReguaInvalida(f"{ARQUIVO} de {segmento}: precisa ser um objeto")
    return dados


def _numero(valor, onde: str, campo: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not 0 <= valor <= MAX_DIAS:
        raise ReguaInvalida(f"{onde}: {campo} precisa ser um número entre 0 e {MAX_DIAS}")
    return float(valor)


def _dias_do_passo(item: dict, loja, onde: str) -> int:
    formas = [k for k in ("dias", "meses", "meses_config") if k in item]
    if len(formas) != 1:
        raise ReguaInvalida(f"{onde}: informe só um prazo (dias, meses ou meses_config)")
    if "dias" in item:
        dias = _numero(item["dias"], onde, "dias")
    else:
        if "meses" in item:
            meses = item["meses"]
        else:
            meses = loja.get(item["meses_config"])
            if meses is None:
                raise ReguaInvalida(f"{onde}: a configuração '{item['meses_config']}' não existe")
        dias = _numero(meses, onde, "meses") * DIAS_POR_MES
    antes = item.get("antes", False)
    if not isinstance(antes, bool):
        raise ReguaInvalida(f"{onde}: 'antes' precisa ser true ou false")
    dias = int(round(dias))
    return -dias if antes else dias


def modelos_de_regua(loja) -> dict[str, dict]:
    """Réguas-modelo do segmento da loja, validadas, com os prazos já em dias."""
    segmento = loja.segmento
    dados = _ler(segmento)
    if not dados:
        return {}
    gatilhos = dados.get("gatilhos")
    if not isinstance(gatilhos, list) or not gatilhos or not all(isinstance(g, str) for g in gatilhos):
        raise ReguaInvalida(f"{ARQUIVO} de {segmento}: falta a lista 'gatilhos'")
    reguas = dados.get("reguas")
    if not isinstance(reguas, dict) or not reguas:
        raise ReguaInvalida(f"{ARQUIVO} de {segmento}: falta o objeto 'reguas'")
    modelos = carregar_modelos(segmento)
    saida = {}
    for nome, conteudo in reguas.items():
        onde = f"{ARQUIVO} de {segmento}, régua {nome}"
        passos = conteudo.get("passos") if isinstance(conteudo, dict) else None
        if not isinstance(passos, list) or not passos:
            raise ReguaInvalida(f"{onde}: precisa de uma lista 'passos'")
        lista = []
        for ordem, item in enumerate(passos, start=1):
            o = f"{onde}, passo {ordem}"
            if not isinstance(item, dict):
                raise ReguaInvalida(f"{o}: cada passo precisa ser um objeto")
            nome_passo = item.get("nome")
            if not isinstance(nome_passo, str) or not nome_passo.strip():
                raise ReguaInvalida(f"{o}: falta o nome")
            gatilho = item.get("gatilho")
            if gatilho not in gatilhos:
                raise ReguaInvalida(f"{o}: gatilho '{gatilho}' fora do vocabulário ({', '.join(gatilhos)})")
            condicao = item.get("pagamento", "todos")
            if condicao not in CONDICOES:
                raise ReguaInvalida(f"{o}: pagamento '{condicao}' inválido ({', '.join(CONDICOES)})")
            acao = item.get("acao", "enviar_modelo")
            if acao not in ACOES:
                raise ReguaInvalida(f"{o}: ação '{acao}' inválida ({', '.join(ACOES)})")
            modelo = item.get("modelo")
            if acao == "enviar_modelo" and modelo not in modelos:
                raise ReguaInvalida(f"{o}: o modelo '{modelo}' não existe em modelos.json")
            lista.append({
                "ordem": ordem, "nome": nome_passo.strip(), "gatilho": gatilho,
                "deslocamento_dias": _dias_do_passo(item, loja, o),
                "condicao_pagamento": condicao, "acao": acao, "modelo": modelo,
                "ativo": bool(item.get("ativo", True)),
            })
        saida[nome] = {"nome": nome, "titulo": str(conteudo.get("titulo") or nome), "passos": lista}
    return saida


# ------------------------------------------------------------ régua da loja

def copiar_regua_modelo(loja_id, nome_modelo: str | None = None) -> int:
    """Dá à loja uma cópia da régua-modelo (a anterior fica de histórico)."""
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    modelos = modelos_de_regua(loja)
    if not modelos:
        raise ReguaInexistente(f"O segmento {loja.segmento} não tem réguas de pós-venda.")
    nome_modelo = nome_modelo or _ler(loja.segmento).get("padrao") or next(iter(modelos))
    if nome_modelo not in modelos:
        raise ReguaInexistente(f"O segmento {loja.segmento} não tem a régua '{nome_modelo}'.")
    passos = modelos[nome_modelo]["passos"]
    conexao = conectar()
    try:
        conexao.execute(
            "UPDATE reguas SET ativa = 0, atualizado_em = CURRENT_TIMESTAMP "
            "WHERE loja_id = ? AND tipo = ? AND ativa = 1", (loja_id, TIPO))
        regua_id = conexao.execute(
            "INSERT INTO reguas (loja_id, tipo, modelo_origem) VALUES (?, ?, ?)",
            (loja_id, TIPO, nome_modelo)).lastrowid
        conexao.executemany(
            "INSERT INTO regua_passos (loja_id, regua_id, ordem, nome, gatilho, deslocamento_dias, "
            "condicao_pagamento, acao, modelo, ativo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(loja_id, regua_id, p["ordem"], p["nome"], p["gatilho"], p["deslocamento_dias"],
              p["condicao_pagamento"], p["acao"], p["modelo"], 1 if p["ativo"] else 0)
             for p in passos])
        conexao.commit()
    finally:
        conexao.close()
    return regua_id


def regua_ativa(loja_id) -> dict | None:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        regua = conexao.execute(
            "SELECT * FROM reguas WHERE loja_id = ? AND tipo = ? AND ativa = 1",
            (loja_id, TIPO)).fetchone()
        if regua is None:
            return None
        passos = conexao.execute(
            "SELECT * FROM regua_passos WHERE loja_id = ? AND regua_id = ? ORDER BY ordem",
            (loja_id, regua["id"])).fetchall()
    finally:
        conexao.close()
    return {**dict(regua), "passos": [dict(p) for p in passos]}


def garantir_regua(loja_id) -> dict:
    """A régua ativa da loja; na primeira vez, copia a régua-modelo padrão."""
    atual = regua_ativa(loja_id)
    if atual:
        return atual
    copiar_regua_modelo(loja_id)
    return regua_ativa(loja_id)


def ligar_passo(loja_id, passo_id: int, ativo: bool) -> None:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        n = conexao.execute("UPDATE regua_passos SET ativo = ? WHERE id = ? AND loja_id = ?",
                            (1 if ativo else 0, passo_id, loja_id)).rowcount
        conexao.commit()
    finally:
        conexao.close()
    if not n:
        raise ReguaInexistente(f"Passo {passo_id} não existe nesta loja.")


# ------------------------------------------------------------ agenda

def _quando(loja, dia: date) -> datetime:
    alvo = datetime.combine(dia, HORA_DO_ENVIO, tzinfo=fuso(loja))
    return proxima_abertura(loja, alvo)


def agendar(loja_id, lead_id: str, evento_tipo: str, evento_id: int, *, datas: dict,
            pagamento: str, inicio: date, agora: datetime) -> list[dict]:
    """Agenda os passos ATIVOS para um acontecimento.
    datas: {gatilho: data ou None}. inicio: a data do acontecimento.
    Passo que não pode sair fica gravado como 'cancelado', com o motivo."""
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    atual = garantir_regua(loja_id)
    agora = _utc(agora)
    linhas, resumo = [], []
    for p in atual["passos"]:
        if not p["ativo"] or p["condicao_pagamento"] not in ("todos", pagamento):
            continue
        base = datas.get(p["gatilho"])
        estado, motivo, quando = "agendado", None, agora
        if base is None:
            estado, motivo = "cancelado", f"sem_data_{p['gatilho']}"
        else:
            dia = base + timedelta(days=p["deslocamento_dias"])
            quando = _quando(loja, dia)
            if p["deslocamento_dias"] < 0 and dia <= inicio:
                estado, motivo = "cancelado", "antes_do_evento"
            elif quando < agora - TOLERANCIA_ATRASO:
                estado, motivo = "cancelado", "data_passou"
        linhas.append((loja_id, atual["id"], p["id"], lead_id, evento_tipo, evento_id,
                       para_banco(quando), estado, motivo, p["modelo"]))
        resumo.append({"passo": p["nome"], "estado": estado, "motivo": motivo, "quando": quando})
    conexao = conectar()
    try:
        conexao.executemany(
            "INSERT OR IGNORE INTO regua_execucoes (loja_id, regua_id, passo_id, lead_id, evento_tipo, "
            "evento_id, agendado_para, estado, motivo, modelo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            linhas)
        conexao.commit()
    finally:
        conexao.close()
    return resumo


def cancelar_futuros(loja_id, lead_id: str, motivo: str) -> int:
    """Cancela tudo o que ainda está agendado para este cliente nesta loja."""
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        n = conexao.execute(
            "UPDATE regua_execucoes SET estado = 'cancelado', motivo = ?, executado_em = CURRENT_TIMESTAMP "
            "WHERE loja_id = ? AND lead_id = ? AND estado = 'agendado'",
            (motivo, loja_id, lead_id)).rowcount
        conexao.commit()
    finally:
        conexao.close()
    return n


_SELECT = ("SELECT e.*, p.nome AS passo_nome, p.acao, p.ativo AS passo_ativo "
           "FROM regua_execucoes e JOIN regua_passos p ON p.id = e.passo_id ")


def _consultar(sql: str, parametros: tuple) -> list[dict]:
    conexao = conectar()
    try:
        return [dict(l) for l in conexao.execute(sql, parametros).fetchall()]
    finally:
        conexao.close()


def execucoes_do_lead(loja_id, lead_id: str) -> list[dict]:
    loja_id = exigir_loja(loja_id)
    return _consultar(_SELECT + "WHERE e.loja_id = ? AND e.lead_id = ? ORDER BY e.agendado_para, e.id",
                      (loja_id, lead_id))


def vencidas(loja_id, agora: datetime, limite: int) -> list[dict]:
    loja_id = exigir_loja(loja_id)
    return _consultar(_SELECT + "WHERE e.loja_id = ? AND e.estado = 'agendado' AND e.agendado_para <= ? "
                      "ORDER BY e.agendado_para, e.id LIMIT ?", (loja_id, para_banco(agora), limite))


def agendados(loja_id, limite: int) -> list[dict]:
    loja_id = exigir_loja(loja_id)
    return _consultar(_SELECT + "WHERE e.loja_id = ? AND e.estado = 'agendado' "
                      "ORDER BY e.agendado_para, e.id LIMIT ?", (loja_id, limite))

"""
Custo de cada execução do agente (Etapa 1, Bloco 6 - item 1.9).

Cada resposta grava UMA linha em uso_custos (e uma no log, com o mesmo
execucao_id). Os tokens vêm do usage_metadata padrão do LangChain, que é
igual para qualquer fornecedor de IA. Sem metadados, grava zero.
Nada aqui pode derrubar a conversa.

Nome no banco: a coluna se chama custo_llm (LLM = modelo de linguagem,
qualquer fornecedor). No código, na tela e no log chamamos de custo_ia.
"""
from __future__ import annotations

import json
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from langchain_core.messages import ToolMessage

from app import logs, precos, relogio
from banco import conectar


@dataclass
class Uso:
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_audio: int = 0

    def __add__(self, outro: "Uso") -> "Uso":
        return Uso(self.tokens_entrada + outro.tokens_entrada,
                   self.tokens_saida + outro.tokens_saida,
                   self.tokens_audio + outro.tokens_audio)

    @property
    def vazio(self) -> bool:
        return not (self.tokens_entrada or self.tokens_saida or self.tokens_audio)


def _int(valor) -> int:
    try:
        return max(0, int(valor or 0))
    except (TypeError, ValueError):
        return 0


def uso_das_mensagens(mensagens) -> Uso:
    """Soma os tokens de todas as respostas da IA no turno."""
    total = Uso()
    for m in mensagens or []:
        meta = getattr(m, "usage_metadata", None)
        if not isinstance(meta, dict):
            continue
        entrada = _int(meta.get("input_tokens"))
        audio = min(_int((meta.get("input_token_details") or {}).get("audio")), entrada)
        total = total + Uso(entrada - audio, _int(meta.get("output_tokens")), audio)
    return total


def ferramentas_usadas(mensagens) -> list[str]:
    return [m.name for m in mensagens or [] if isinstance(m, ToolMessage) and m.name]


def _agora_texto(agora: datetime | None = None) -> str:
    agora = agora or datetime.now(timezone.utc)
    if agora.tzinfo is not None:
        agora = agora.astimezone(timezone.utc)
    return agora.strftime("%Y-%m-%d %H:%M:%S")


def calcular_custo(uso: Uso, dia, msgs_servico: int = 0, msgs_utilidade: int = 0,
                   msgs_marketing: int = 0) -> tuple[float, float, bool]:
    """Devolve (custo_ia, custo_meta, completo) em R$.
    completo=False quando faltou algum preço para algo que foi usado."""
    completo = True

    def preco(item, quantidade, reserva=None):
        nonlocal completo
        if not quantidade:
            return 0.0
        valor = precos.valor_em_brl(item, dia)
        if valor is None and reserva:
            valor = precos.valor_em_brl(reserva, dia)
        if valor is None:
            completo = False
            return 0.0
        return valor

    custo_ia = (
        uso.tokens_entrada * preco("ia.entrada", uso.tokens_entrada)
        + uso.tokens_saida * preco("ia.saida", uso.tokens_saida)
        # Sem preço de áudio cadastrado, usa o de entrada de texto.
        + uso.tokens_audio * preco("ia.audio", uso.tokens_audio, reserva="ia.entrada")
    ) / precos.POR_MILHAO
    custo_meta = (
        msgs_servico * preco("meta.servico", msgs_servico)
        + msgs_utilidade * preco("meta.utilidade", msgs_utilidade)
        + msgs_marketing * preco("meta.marketing", msgs_marketing)
    )
    return round(custo_ia, 6), round(custo_meta, 6), completo


def registrar_uso(loja_id: int, lead_id: str | None, canal: str, uso: Uso | None = None, *,
                  tipo: str = "turno", ferramentas=(), latencia_ms: int | None = None,
                  msgs_servico: int = 0, msgs_utilidade: int = 0, msgs_marketing: int = 0,
                  modelo: str | None = None, execucao_id: str | None = None,
                  agora: datetime | None = None) -> dict | None:
    """Grava uma linha em uso_custos e uma no log. Nunca levanta exceção."""
    uso = uso or Uso()
    try:
        if modelo is None:
            from app.config import MODELO_LLM as modelo
        execucao_id = execucao_id or uuid.uuid4().hex
        criado_em = _agora_texto(agora)
        custo_ia, custo_meta, completo = calcular_custo(
            uso, criado_em[:10], msgs_servico, msgs_utilidade, msgs_marketing)
        lista = list(ferramentas)

        conexao = conectar()
        try:
            conexao.execute(
                """INSERT INTO uso_custos (
                       loja_id, lead_id, canal, execucao_id, criado_em, tipo, modelo,
                       tokens_entrada, tokens_saida, tokens_audio,
                       msgs_servico, msgs_utilidade, msgs_marketing,
                       custo_llm, custo_meta, custo_completo, ferramentas, latencia_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (loja_id, lead_id, canal, execucao_id, criado_em, tipo, modelo,
                 uso.tokens_entrada, uso.tokens_saida, uso.tokens_audio,
                 msgs_servico, msgs_utilidade, msgs_marketing,
                 custo_ia, custo_meta, 1 if completo else 0,
                 json.dumps(lista, ensure_ascii=False), latencia_ms),
            )
            conexao.commit()
        finally:
            conexao.close()
    except Exception as erro:
        print(f"[Custos] ERRO ao registrar custo (loja {loja_id}, lead {lead_id}): {erro!r}")
        return None

    registro = {
        "execucao_id": execucao_id, "criado_em": criado_em, "loja_id": loja_id,
        "lead_id": lead_id, "canal": canal, "tipo": tipo, "modelo": modelo,
        "tokens_entrada": uso.tokens_entrada, "tokens_saida": uso.tokens_saida,
        "tokens_audio": uso.tokens_audio, "msgs_servico": msgs_servico,
        "msgs_utilidade": msgs_utilidade, "msgs_marketing": msgs_marketing,
        "custo_ia": custo_ia, "custo_meta": custo_meta,
        "custo_total": round(custo_ia + custo_meta, 6), "completo": completo,
        "ferramentas": lista, "latencia_ms": latencia_ms,
    }
    logs.registrar_execucao(registro)
    return registro


def recalcular_custos(loja_id: int | None = None) -> int:
    """Recalcula o custo em R$ a partir dos tokens gravados, com os preços
    vigentes na data de cada linha. Use depois de cadastrar ou corrigir preços."""
    conexao = conectar()
    try:
        sql = ("SELECT id, criado_em, tokens_entrada, tokens_saida, tokens_audio, "
               "msgs_servico, msgs_utilidade, msgs_marketing FROM uso_custos")
        parametros = ()
        if loja_id is not None:
            sql += " WHERE loja_id = ?"
            parametros = (loja_id,)
        linhas = conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()

    atualizacoes = []
    for l in linhas:
        uso = Uso(l["tokens_entrada"], l["tokens_saida"], l["tokens_audio"])
        ia, meta, ok = calcular_custo(uso, str(l["criado_em"])[:10],
                                      l["msgs_servico"], l["msgs_utilidade"], l["msgs_marketing"])
        atualizacoes.append((ia, meta, 1 if ok else 0, l["id"]))

    conexao = conectar()
    try:
        conexao.executemany(
            "UPDATE uso_custos SET custo_llm = ?, custo_meta = ?, custo_completo = ? WHERE id = ?",
            atualizacoes,
        )
        conexao.commit()
    finally:
        conexao.close()
    return len(atualizacoes)


# ------------------------------------------------------------- relatórios
def _intervalo_mes(ano: int, mes: int) -> tuple[str, str]:
    inicio = f"{ano:04d}-{mes:02d}-01 00:00:00"
    ano2, mes2 = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return inicio, f"{ano2:04d}-{mes2:02d}-01 00:00:00"


def resumo_mes(loja_id: int, ano: int, mes: int) -> dict:
    """Conversa = um lead, numa loja, no mês."""
    inicio, fim = _intervalo_mes(ano, mes)
    conexao = conectar()
    try:
        l = conexao.execute(
            """SELECT COUNT(*) AS execucoes,
                      COALESCE(SUM(CASE WHEN tipo = 'turno' THEN 1 ELSE 0 END), 0) AS turnos,
                      COUNT(DISTINCT lead_id) AS conversas,
                      COALESCE(SUM(custo_llm), 0) AS custo_ia,
                      COALESCE(SUM(custo_meta), 0) AS custo_meta,
                      COALESCE(SUM(tokens_entrada), 0) AS tokens_entrada,
                      COALESCE(SUM(tokens_saida), 0) AS tokens_saida,
                      COALESCE(SUM(tokens_audio), 0) AS tokens_audio,
                      COALESCE(SUM(msgs_servico + msgs_utilidade + msgs_marketing), 0) AS msgs_meta,
                      COALESCE(SUM(CASE WHEN custo_completo = 0 THEN 1 ELSE 0 END), 0) AS incompletas,
                      AVG(CASE WHEN tipo = 'turno' THEN latencia_ms END) AS latencia_media_ms
               FROM uso_custos
               WHERE loja_id = ? AND criado_em >= ? AND criado_em < ?""",
            (loja_id, inicio, fim),
        ).fetchone()
    finally:
        conexao.close()
    resumo = dict(l)
    resumo["custo_total"] = round(resumo["custo_ia"] + resumo["custo_meta"], 6)
    resumo["custo_medio_conversa"] = (
        round(resumo["custo_total"] / resumo["conversas"], 6) if resumo["conversas"] else 0.0)
    return resumo


def gasto_do_dia(loja_id: int, dia, fuso: str | None = None) -> float:
    """Gasto de um dia. Com fuso (o da loja), o dia vira à meia-noite local;
    sem fuso, usa o dia em UTC (comportamento antigo, mantido para os testes)."""
    if fuso:
        inicio, fim = relogio.limites_do_dia_em_utc(fuso, dia)
        sql = ("SELECT COALESCE(SUM(custo_llm + custo_meta), 0) AS total FROM uso_custos "
               "WHERE loja_id = ? AND criado_em >= ? AND criado_em < ?")
        parametros = (loja_id, inicio, fim)
    else:
        sql = ("SELECT COALESCE(SUM(custo_llm + custo_meta), 0) AS total FROM uso_custos "
               "WHERE loja_id = ? AND substr(criado_em, 1, 10) = ?")
        parametros = (loja_id, precos._data_iso(dia))
    conexao = conectar()
    try:
        l = conexao.execute(sql, parametros).fetchone()
    finally:
        conexao.close()
    return round(l["total"], 6)


def custo_por_dia(loja_id: int, ano: int, mes: int) -> list[dict]:
    inicio, fim = _intervalo_mes(ano, mes)
    conexao = conectar()
    try:
        linhas = conexao.execute(
            """SELECT substr(criado_em, 1, 10) AS dia,
                      ROUND(SUM(custo_llm + custo_meta), 6) AS custo
               FROM uso_custos WHERE loja_id = ? AND criado_em >= ? AND criado_em < ?
               GROUP BY dia ORDER BY dia""",
            (loja_id, inicio, fim),
        ).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]


def ferramentas_mais_usadas(loja_id: int, ano: int, mes: int) -> list[tuple[str, int]]:
    inicio, fim = _intervalo_mes(ano, mes)
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT ferramentas FROM uso_custos "
            "WHERE loja_id = ? AND criado_em >= ? AND criado_em < ?",
            (loja_id, inicio, fim),
        ).fetchall()
    finally:
        conexao.close()
    contagem = Counter()
    for l in linhas:
        try:
            contagem.update(json.loads(l["ferramentas"] or "[]"))
        except (TypeError, ValueError):
            continue
    return contagem.most_common()


def resumo_todas_lojas(ano: int, mes: int) -> list[dict]:
    from app.lojas_admin import listar_lojas
    saida = []
    for loja in listar_lojas():
        r = resumo_mes(loja["id"], ano, mes)
        saida.append({"loja": f'{loja["nome"]} (id {loja["id"]})', "conversas": r["conversas"],
                      "custo_total": r["custo_total"],
                      "custo_medio_conversa": r["custo_medio_conversa"],
                      "incompletas": r["incompletas"]})
    return saida


def ultimas_execucoes(loja_id: int, limite: int = 30) -> list[dict]:
    conexao = conectar()
    try:
        linhas = conexao.execute(
            """SELECT criado_em, lead_id, canal, tipo, modelo, tokens_entrada, tokens_saida,
                      tokens_audio, custo_llm AS custo_ia, custo_meta, custo_completo,
                      ferramentas, latencia_ms, execucao_id
               FROM uso_custos WHERE loja_id = ? ORDER BY id DESC LIMIT ?""",
            (loja_id, limite),
        ).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]

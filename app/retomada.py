"""
A retomada que o assistente mandou (Etapa 2, Bloco 4; reativação no Bloco 6C).

A retomada sai pelo relógio (runner), mas a memória do assistente fica no
processo do bot. Para ele não responder fora de contexto quando o cliente
volta, a cada mensagem o agente pergunta aqui: "mandei alguma retomada
para este cliente nos últimos dias?". Se sim, o texto entra no prompt.
Sem retomada de remarketing, confere a reativação (WhatsApp, pelo telefone).

Só conta o que foi ENVIADO de verdade (simulação, falha e bloqueio não).
Também conta as respostas, para a tela do Bloco 6.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from banco import conectar
from app.chaves import exigir_loja
from app.relogio import do_banco, para_banco

JANELA_CONTEXTO = timedelta(hours=72)


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def retomada_recente(loja_id, lead_id: str, canal: str, agora: datetime) -> dict | None:
    """A última retomada ENVIADA a este cliente nas últimas 72 h, ou None."""
    loja_id = exigir_loja(loja_id)
    agora = _utc(agora)
    sql = ("SELECT toque, contexto, enviado_em FROM remarketing_envios "
           "WHERE loja_id = ? AND lead_id = ? AND estado = 'enviado' "
           "AND enviado_em >= ? AND enviado_em <= ?")
    parametros = [loja_id, str(lead_id), para_banco(agora - JANELA_CONTEXTO), para_banco(agora)]
    if canal:
        sql += " AND canal = ?"
        parametros.append(canal)
    sql += " ORDER BY enviado_em DESC, toque DESC LIMIT 1"
    conexao = conectar()
    try:
        linha = conexao.execute(sql, parametros).fetchone()
    finally:
        conexao.close()
    if not linha:
        if canal in (None, "", "whatsapp"):
            from app.reativacao import reativacao_recente   # import tardio: evita ciclo
            return reativacao_recente(loja_id, lead_id, agora)
        return None
    try:
        texto = (json.loads(linha["contexto"] or "{}").get("texto") or "").strip()
    except (TypeError, ValueError):
        texto = ""
    if not texto:
        return None
    return {"toque": linha["toque"], "texto": texto, "enviado_em": do_banco(linha["enviado_em"])}


def resumo_respostas(loja_id, desde: datetime, ate: datetime | None = None) -> dict:
    """Quantas retomadas saíram no período e quantas o cliente respondeu."""
    loja_id = exigir_loja(loja_id)
    ate = _utc(ate) if ate else datetime.now(timezone.utc)
    conexao = conectar()
    try:
        linha = conexao.execute(
            """SELECT COUNT(*) AS enviados,
                      SUM(CASE WHEN EXISTS (
                          SELECT 1 FROM mensagens m
                          WHERE m.loja_id = r.loja_id AND m.lead_id = r.lead_id
                            AND m.canal = r.canal AND m.direcao = 'cliente'
                            AND m.criado_em > r.enviado_em) THEN 1 ELSE 0 END) AS respondidos
               FROM remarketing_envios r
               WHERE r.loja_id = ? AND r.estado = 'enviado'
                 AND r.enviado_em >= ? AND r.enviado_em <= ?""",
            (loja_id, para_banco(_utc(desde)), para_banco(ate)),
        ).fetchone()
    finally:
        conexao.close()
    enviados = linha["enviados"] or 0
    respondidos = linha["respondidos"] or 0
    return {"enviados": enviados, "respondidos": respondidos,
            "taxa": round(respondidos / enviados, 3) if enviados else 0.0}

"""
Dados da tela "Retomadas e pós-venda" (Etapa 2, Bloco 7). Só leitura.

Aparece nos DOIS painéis, por isso não importa nada do operador
(custos e preços) nem os jobs.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from banco import conectar
from app import config  # noqa: F401  (carrega o .env)
from app import reativacao, regua
from app.chaves import exigir_loja
from app.elegibilidade import candidatos, enviados_no_mes
from app.lojas import carregar_loja
from app.relogio import dia_local, do_banco, fuso
from app.telefone import normalizar_telefone_br

TIPOS = {"remarketing": "Retomada", "pos_venda": "Pós-venda", "reativacao": "Reativação"}
VARIAVEIS_ENVIO = {"remarketing": "REMARKETING_ENVIO_REAL",
                   "pos_venda": "POS_VENDA_ENVIO_REAL",
                   "reativacao": "REATIVACAO_ENVIO_REAL"}
ROTULOS_ESTADO = {
    "agendado": "Agendado", "na_fila": "Na fila", "simulado": "Simulado (nada saiu)",
    "enviado": "Enviado", "avisado": "Vendedor avisado", "falhou": "Falhou",
    "bloqueado": "Bloqueado", "cancelado": "Cancelado",
}
MOTIVOS = {
    # remarketing (cópia dos textos do job, para a tela não importar o job)
    "sem_modelo": "O segmento não tem o modelo",
    "faltam_dados": "Falta o nome do cliente para o modelo",
    "modelo_nao_aprovado": "Modelo ainda não aprovado pela Meta nesta loja",
    "janela_fechada": "A Meta recusou: janela de 24 h fechada",
    "erro_no_envio": "O canal recusou o envio",
    "falhas_repetidas": "Falhou 3 vezes; precisa de alguém olhar",
    "sem_canal": "O cliente nunca conversou pelo WhatsApp ou Telegram",
    "pediu_tempo": "Pediu um tempo; reagendado",
    "pausa_longa": "Venceu durante a pausa dos envios",
    **regua.MOTIVOS,
    **reativacao.MOTIVOS,
}

_FONTES = {
    # tipo: (tabela, coluna da hora do envio, como achar a resposta, como achar o agendamento)
    "remarketing": ("remarketing_envios", "enviado_em",
                    "m.lead_id = r.lead_id AND m.canal = r.canal", "a.lead_id = r.lead_id"),
    "pos_venda": ("regua_execucoes", "executado_em",
                  "m.lead_id = r.lead_id", "a.lead_id = r.lead_id"),
    "reativacao": ("reativacao", "enviado_em",
                   "m.canal = 'whatsapp' AND fone_br(m.lead_id) = r.telefone",
                   "fone_br(a.lead_id) = r.telefone"),
}


def _conectar():
    conexao = conectar()
    conexao.create_function("fone_br", 1, normalizar_telefone_br)
    return conexao


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _motivo(codigo) -> str:
    if not codigo:
        return ""
    return MOTIVOS.get(codigo, str(codigo).replace("_", " "))


def _texto(contexto) -> str:
    try:
        dados = json.loads(contexto or "{}")
        return str(dados.get("texto") or "") if isinstance(dados, dict) else ""
    except (TypeError, ValueError):
        return ""


def modo_de_envio() -> dict[str, bool]:
    """True = envio real; False = simulação."""
    return {tipo: (os.getenv(var) or "").strip().lower() in ("1", "true", "sim", "yes")
            for tipo, var in VARIAVEIS_ENVIO.items()}


def inicio_do_mes(loja, agora: datetime) -> datetime:
    hoje = dia_local(loja, _utc(agora))
    return datetime(hoje.year, hoje.month, 1, tzinfo=fuso(loja)).astimezone(timezone.utc)


def uso_do_limite(loja_id, agora: datetime) -> dict:
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    return {"usados": enviados_no_mes(loja_id, agora), "limite": loja.get("remarketing.limite_mensal")}


# ------------------------------------------------------------ fila

def fila(loja_id, agora: datetime) -> list[dict]:
    """Quem será procurado e quando (horas em UTC)."""
    loja_id = exigir_loja(loja_id)
    agora = _utc(agora)
    saida = []
    for d in candidatos(loja_id, agora):
        if d.elegivel or d.proximo_em:
            saida.append({"tipo": "remarketing", "lead_id": d.lead_id, "canal": d.canal,
                          "quando": agora if d.elegivel else _utc(d.proximo_em),
                          "situacao": d.rotulo, "detalhe": f"toque {d.toque}" if d.toque else ""})
    for p in regua.agendados(loja_id, 100):
        saida.append({"tipo": "pos_venda", "lead_id": p["lead_id"], "canal": "",
                      "quando": do_banco(p["agendado_para"]), "situacao": "Agendado",
                      "detalhe": p.get("passo_nome") or ""})
    for r in reativacao.listar(loja_id, 500):
        if r["estado"] in reativacao.ESTADOS_NA_FILA:
            saida.append({"tipo": "reativacao", "lead_id": r["lead_id"] or r["telefone"],
                          "canal": "whatsapp", "quando": None,
                          "situacao": reativacao.ROTULOS_ESTADO.get(r["estado"], r["estado"]),
                          "detalhe": f"parado há {r['meses_inativo']} meses"})
    minimo = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(saida, key=lambda x: x["quando"] or minimo)


# ------------------------------------------------------------ histórico

def historico(loja_id, limite: int = 50) -> list[dict]:
    """O que já aconteceu (mais recente primeiro), com o motivo em texto."""
    loja_id = exigir_loja(loja_id)
    conexao = _conectar()
    try:
        rm = conexao.execute(
            "SELECT lead_id, canal, toque, estado, motivo_bloqueio AS motivo, contexto, "
            "COALESCE(enviado_em, criado_em) AS quando FROM remarketing_envios "
            "WHERE loja_id = ? ORDER BY quando DESC LIMIT ?", (loja_id, limite)).fetchall()
        pv = conexao.execute(
            "SELECT e.lead_id, e.estado, e.motivo, e.contexto, p.nome AS passo, "
            "COALESCE(e.executado_em, e.criado_em) AS quando FROM regua_execucoes e "
            "LEFT JOIN regua_passos p ON p.id = e.passo_id "
            "WHERE e.loja_id = ? AND e.estado != 'agendado' ORDER BY quando DESC LIMIT ?",
            (loja_id, limite)).fetchall()
        ra = conexao.execute(
            "SELECT COALESCE(lead_id, telefone) AS lead_id, estado, motivo, texto, "
            "COALESCE(enviado_em, atualizado_em, criado_em) AS quando FROM reativacao "
            "WHERE loja_id = ? AND estado != 'na_fila' ORDER BY quando DESC LIMIT ?",
            (loja_id, limite)).fetchall()
    finally:
        conexao.close()
    itens = (
        [{"tipo": "remarketing", "lead_id": l["lead_id"], "estado": l["estado"],
          "motivo": _motivo(l["motivo"]), "texto": _texto(l["contexto"]),
          "detalhe": f"toque {l['toque']} ({l['canal']})", "quando": do_banco(l["quando"])} for l in rm]
        + [{"tipo": "pos_venda", "lead_id": l["lead_id"], "estado": l["estado"],
            "motivo": _motivo(l["motivo"]), "texto": _texto(l["contexto"]),
            "detalhe": l["passo"] or "", "quando": do_banco(l["quando"])} for l in pv]
        + [{"tipo": "reativacao", "lead_id": l["lead_id"], "estado": l["estado"],
            "motivo": _motivo(l["motivo"]), "texto": l["texto"] or "",
            "detalhe": "", "quando": do_banco(l["quando"])} for l in ra]
    )
    minimo = datetime.min.replace(tzinfo=timezone.utc)
    itens.sort(key=lambda x: x["quando"] or minimo, reverse=True)
    return itens[:limite]


# ------------------------------------------------------------ resultado do mês

def resultado_do_mes(loja_id, agora: datetime) -> dict:
    """Por tipo e no total: enviados, responderam, agendaram e custo Meta (R$)."""
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    agora = _utc(agora)
    de, ate = inicio_do_mes(loja, agora), agora
    saida, total = {}, {"enviados": 0, "responderam": 0, "agendaram": 0, "custo": 0.0}
    conexao = _conectar()
    try:
        for tipo, (tabela, quando, resposta, agenda) in _FONTES.items():
            linha = conexao.execute(
                f"""SELECT COUNT(*) AS enviados,
                       COALESCE(SUM(CASE WHEN EXISTS (SELECT 1 FROM mensagens m
                           WHERE m.loja_id = r.loja_id AND m.direcao = 'cliente'
                             AND {resposta} AND m.criado_em > r.{quando}) THEN 1 ELSE 0 END), 0) AS responderam,
                       COALESCE(SUM(CASE WHEN EXISTS (SELECT 1 FROM agendamentos a
                           WHERE a.loja_id = r.loja_id AND {agenda}
                             AND a.criado_em > r.{quando}) THEN 1 ELSE 0 END), 0) AS agendaram,
                       COALESCE(SUM(r.custo_meta), 0) AS custo
                    FROM {tabela} r
                    WHERE r.loja_id = ? AND r.estado = 'enviado'
                      AND r.{quando} >= ? AND r.{quando} <= ?""",
                (loja_id, de.strftime("%Y-%m-%d %H:%M:%S"), ate.strftime("%Y-%m-%d %H:%M:%S")),
            ).fetchone()
            item = {"enviados": int(linha["enviados"]), "responderam": int(linha["responderam"]),
                    "agendaram": int(linha["agendaram"]), "custo": float(linha["custo"])}
            saida[tipo] = item
            for chave in total:
                total[chave] += item[chave]
    finally:
        conexao.close()
    saida["total"] = total
    return saida

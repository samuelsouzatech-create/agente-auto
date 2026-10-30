"""
Pós-venda da base importada (Etapa 2, Bloco 6B).

As compras de antes do sistema (compras_anteriores, Bloco 6A) entram na MESMA
régua do botão "Vendido". Regras:
  - só contatos COM autorização (consentimento = 1)
  - só passos que ainda não passaram (o motor já cancela os atrasados)
  - a mesma compra marcada pelo botão "Vendido" não entra de novo
  - lead_id: se a pessoa já conversou pelo WhatsApp, usa o número da conversa
    (a Meta manda sem o 9); senão, o telefone normalizado
Quem envia é o job de pós-venda, que confere a autorização de novo antes de cada passo.
"""
from __future__ import annotations

from datetime import date, datetime

from banco import conectar
from app import regua, vendas
from app.chaves import exigir_loja
from app.lojas import carregar_loja, modulo_ativo
from app.relogio import agora_utc
from app.telefone import normalizar_telefone_br

EVENTO = "compra_anterior"
MOTIVOS = {
    "sem_consentimento": "O contato da base não tem autorização para receber mensagens",
    "importacao_desfeita": "A importação desta compra foi desfeita",
}

_PENDENTES = (
    "FROM compras_anteriores c "
    "JOIN contatos t ON t.loja_id = c.loja_id AND t.telefone = c.telefone "
    "WHERE c.loja_id = ? AND t.consentimento = 1 "
    "AND NOT EXISTS (SELECT 1 FROM regua_execucoes e WHERE e.loja_id = c.loja_id "
    "AND e.evento_tipo = ? AND e.evento_id = c.id) "
    "AND NOT EXISTS (SELECT 1 FROM vendas v WHERE v.loja_id = c.loja_id "
    "AND fone_br(v.lead_id) = c.telefone AND substr(v.data_venda, 1, 10) = c.data_compra) "
)


class BaseNaoAgendada(ValueError):
    pass


def _conectar():
    conexao = conectar()
    conexao.create_function("fone_br", 1, normalizar_telefone_br)
    return conexao


def lead_da_base(loja_id, telefone) -> str:
    """O lead_id que esta pessoa usa (ou usará) na conversa do WhatsApp."""
    loja_id = exigir_loja(loja_id)
    fone = normalizar_telefone_br(telefone)
    if not fone:
        return str(telefone or "")
    conexao = _conectar()
    try:
        linha = conexao.execute(
            "SELECT lead_id FROM mensagens WHERE loja_id = ? AND canal = 'whatsapp' "
            "AND fone_br(lead_id) = ? ORDER BY id DESC LIMIT 1", (loja_id, fone)).fetchone()
    finally:
        conexao.close()
    return linha["lead_id"] if linha else fone


def agendar_base(loja_id, *, agora: datetime | None = None) -> dict:
    """Coloca na régua as compras importadas que ainda não foram agendadas."""
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    if not modulo_ativo(loja, "pos_venda"):
        raise BaseNaoAgendada("O pós-venda desta loja está desligado. Ligue em Plano e limites.")
    agora = agora or agora_utc()
    conexao = _conectar()
    try:
        compras = [dict(l) for l in conexao.execute(
            "SELECT c.* " + _PENDENTES + "ORDER BY c.id", (loja_id, EVENTO)).fetchall()]
    finally:
        conexao.close()
    saida = {"compras": len(compras), "agendados": 0, "ja_passaram": 0, "outros": 0}
    for c in compras:
        dia = date.fromisoformat(str(c["data_compra"])[:10])
        forma = c["forma_pagamento"] or ""
        passos = regua.agendar(
            loja_id, lead_da_base(loja_id, c["telefone"]), EVENTO, c["id"],
            datas=vendas.datas_da_venda(dia, forma, c["meses_financiamento"]),
            pagamento=forma, inicio=dia, agora=agora)
        for p in passos:
            if p["estado"] == "agendado":
                saida["agendados"] += 1
            elif p["motivo"] == "data_passou":
                saida["ja_passaram"] += 1
            else:
                saida["outros"] += 1
    return saida


def resumo(loja_id) -> dict:
    loja_id = exigir_loja(loja_id)
    conexao = _conectar()
    try:
        pendentes = conexao.execute("SELECT COUNT(*) " + _PENDENTES, (loja_id, EVENTO)).fetchone()[0]
        agendados = conexao.execute(
            "SELECT COUNT(*) FROM regua_execucoes WHERE loja_id = ? AND evento_tipo = ? "
            "AND estado = 'agendado'", (loja_id, EVENTO)).fetchone()[0]
    finally:
        conexao.close()
    return {"pendentes": pendentes, "agendados": agendados}


# ------------------------------------------------------------ usadas pelo job

def sincronizar_lead(loja_id, e: dict) -> dict:
    """Se a pessoa começou a conversar depois do agendamento, passa a usar o número da conversa."""
    conexao = conectar()
    try:
        c = conexao.execute("SELECT telefone FROM compras_anteriores WHERE loja_id = ? AND id = ?",
                            (loja_id, e["evento_id"])).fetchone()
    finally:
        conexao.close()
    if c is None:
        return e
    atual = lead_da_base(loja_id, c["telefone"])
    if atual == e["lead_id"]:
        return e
    conexao = conectar()
    try:
        conexao.execute("UPDATE regua_execucoes SET lead_id = ? WHERE id = ? AND loja_id = ?",
                        (atual, e["id"], loja_id))
        conexao.commit()
    finally:
        conexao.close()
    return {**e, "lead_id": atual}


def motivo_para_nao_enviar(loja_id, evento_id) -> str | None:
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT t.consentimento FROM compras_anteriores c "
            "LEFT JOIN contatos t ON t.loja_id = c.loja_id AND t.telefone = c.telefone "
            "WHERE c.loja_id = ? AND c.id = ?", (loja_id, evento_id)).fetchone()
    finally:
        conexao.close()
    if linha is None:
        return "importacao_desfeita"
    if not linha["consentimento"]:
        return "sem_consentimento"
    return None


def nome_do_contato(loja_id, lead_id) -> str:
    fone = normalizar_telefone_br(lead_id)
    if not fone:
        return ""
    conexao = conectar()
    try:
        linha = conexao.execute("SELECT nome FROM contatos WHERE loja_id = ? AND telefone = ?",
                                (loja_id, fone)).fetchone()
    finally:
        conexao.close()
    return (linha["nome"] or "") if linha else ""


def valores_da_compra(loja_id, evento_id) -> dict:
    conexao = conectar()
    try:
        linha = conexao.execute("SELECT descricao FROM compras_anteriores WHERE loja_id = ? AND id = ?",
                                (loja_id, evento_id)).fetchone()
    finally:
        conexao.close()
    return {"carro": linha["descricao"]} if linha and linha["descricao"] else {}

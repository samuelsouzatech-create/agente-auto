"""
L9 (Fase Cérebro): MODO SOMBRA.

Loja em sombra: o Léo recebe as mensagens reais e gera a resposta, mas NÃO envia nada
ao cliente (resposta, foto, remarketing, pós-venda, reativação) e não grava nada que
mude o atendimento (chamado, troca, visita, lead). Só guarda a SUGESTÃO para comparar
com o que o vendedor respondeu.

Guarda: mensagem do cliente, sugestão do Léo, ferramentas que ele usaria, data.
Nada de foto/arquivo. Apaga sozinho depois de 30 dias. Toda função recebe loja_id:
uma loja nunca vê a outra.
Liga/desliga: config da loja "modo_sombra" (padrão desligado, só o operador muda).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from app.chaves import exigir_loja
from app.relogio import agora_utc, para_banco
from app.segmentos import NomesDoMotorEDosRamos
from banco import conectar

DIAS_GUARDADOS = 30
MAX_TEXTO = 2000
# Ferramentas que GRAVAM algo: em sombra, o Léo só diz que usaria (não executa).
# SG1: as do motor + as que o pacote do ramo declara (FERRAMENTAS_QUE_GRAVAM).
FERRAMENTAS_QUE_GRAVAM = NomesDoMotorEDosRamos({"agendar_visita", "registrar_lead", "acionar_handoff",
                                                "registrar_interesse", "registrar_recado"},
                                               "FERRAMENTAS_QUE_GRAVAM")
RESPOSTA_DA_FERRAMENTA = ("Modo sombra: nada foi gravado. Responda ao cliente como responderia "
                          "se a ferramenta tivesse funcionado.")


def em_sombra(loja_id) -> bool:
    """A loja está em modo sombra? Erro ao ler a config = FALSO? Não: na dúvida, a loja
    continua como estava (desligado é o padrão e o que já funciona)."""
    try:
        from app.lojas import carregar_loja
        return bool(carregar_loja(exigir_loja(loja_id)).get("modo_sombra", False))
    except Exception as erro:
        print(f"[Sombra][loja {loja_id}] Não consegui ler o modo sombra ({erro!r}).")
        return False


def apagar_antigas(loja_id: int, agora: datetime | None = None) -> int:
    """Apaga as sugestões desta loja com mais de 30 dias. Devolve quantas apagou."""
    loja_id = exigir_loja(loja_id)
    limite = para_banco((agora or agora_utc()) - timedelta(days=DIAS_GUARDADOS))
    conexao = conectar()
    try:
        apagadas = conexao.execute("DELETE FROM sombra_sugestoes WHERE loja_id = ? AND criado_em < ?",
                                   (loja_id, limite)).rowcount
        conexao.commit()
        return apagadas
    finally:
        conexao.close()


def gravar(loja_id: int, lead_id: str, canal: str, mensagem: str, sugestao: str,
           ferramentas, agora: datetime | None = None) -> int:
    """Grava a sugestão (só texto) e aproveita para apagar as antigas desta loja."""
    loja_id = exigir_loja(loja_id)
    agora = agora or agora_utc()
    conexao = conectar()
    try:
        novo = conexao.execute(
            "INSERT INTO sombra_sugestoes (loja_id, lead_id, canal, mensagem_cliente, sugestao, "
            "ferramentas, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (loja_id, str(lead_id), canal, str(mensagem or "")[:MAX_TEXTO], str(sugestao or "")[:MAX_TEXTO],
             json.dumps(sorted(set(ferramentas or [])), ensure_ascii=False), para_banco(agora))).lastrowid
        conexao.commit()
    finally:
        conexao.close()
    apagar_antigas(loja_id, agora)
    return novo


def sugestoes_do_dia(loja_id: int, inicio_utc: str, fim_utc: str) -> list[dict]:
    """Sugestões desta loja entre dois horários do banco (UTC), com a resposta do vendedor
    (a primeira mensagem da equipe ao mesmo cliente depois da mensagem dele, se houver)."""
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linhas = [dict(l) for l in conexao.execute(
            "SELECT id, lead_id, canal, mensagem_cliente, sugestao, ferramentas, criado_em "
            "FROM sombra_sugestoes WHERE loja_id = ? AND criado_em >= ? AND criado_em < ? ORDER BY id",
            (loja_id, inicio_utc, fim_utc)).fetchall()]
        for l in linhas:
            vendedor = conexao.execute(
                "SELECT conteudo FROM mensagens WHERE loja_id = ? AND lead_id = ? AND direcao = 'vendedor' "
                "AND criado_em >= ? ORDER BY id LIMIT 1", (loja_id, l["lead_id"], l["criado_em"])).fetchone()
            l["resposta_vendedor"] = vendedor["conteudo"] if vendedor else ""
            l["ferramentas"] = json.loads(l["ferramentas"] or "[]")
    finally:
        conexao.close()
    return linhas

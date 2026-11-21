"""
Caderno das mensagens recebidas (Maratona 3, N3 / revisão #15, mínimo).

O webhook anota cada mensagem ANTES de responder 200 ao canal: loja, canal, cliente, id da
mensagem e hora (UTC). O TEXTO não é anotado (privacidade). Fica em logs/recebidas.jsonl, fora do
Git. Sem migração: é um arquivo de linhas JSON.

Ao ligar, o servidor lista no log as mensagens das últimas 24 h que ficaram sem resposta (nenhuma
mensagem do Léo ou do vendedor para aquele cliente depois dela). O painel do operador mostra a mesma
lista. O Léo NÃO responde sozinho essas mensagens: alguém da loja decide.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from app.chaves import exigir_loja
from app.relogio import agora_utc, para_banco

ARQUIVO = "recebidas.jsonl"
GUARDAR_HORAS = 48             # linhas mais velhas saem quando o arquivo cresce
TAMANHO_PARA_LIMPAR = 1024 * 1024


def _caminho() -> str:
    from app import logs
    return os.path.join(logs.PASTA_LOGS, ARQUIVO)


def anotar(loja_id: int, canal: str, lead_id: str, id_externo: str, agora: datetime | None = None) -> bool:
    """Anota a chegada (sem o texto). Nunca lança erro: falhar aqui não pode derrubar o webhook."""
    linha = {"loja": exigir_loja(loja_id), "canal": canal, "lead": str(lead_id), "id": str(id_externo),
             "quando": para_banco(agora or agora_utc())}
    try:
        from app import logs
        os.makedirs(logs.PASTA_LOGS, exist_ok=True)
        with open(_caminho(), "a", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps(linha, ensure_ascii=False) + "\n")
        if os.path.getsize(_caminho()) > TAMANHO_PARA_LIMPAR:
            _limpar(agora or agora_utc())
        return True
    except OSError:
        from app.log import logger
        logger("recebidas").exception("Não consegui anotar a mensagem recebida.")
        return False


def _ler() -> list[dict]:
    try:
        with open(_caminho(), encoding="utf-8") as arquivo:
            linhas = []
            for bruta in arquivo:
                try:
                    linhas.append(json.loads(bruta))
                except ValueError:
                    continue
            return linhas
    except FileNotFoundError:
        return []


def _limpar(agora: datetime) -> None:
    limite = para_banco(agora - timedelta(hours=GUARDAR_HORAS))
    ficam = [l for l in _ler() if str(l.get("quando", "")) >= limite]
    with open(_caminho(), "w", encoding="utf-8") as arquivo:
        arquivo.writelines(json.dumps(l, ensure_ascii=False) + "\n" for l in ficam)


def sem_resposta(loja_id: int, *, horas: int = 24, agora: datetime | None = None) -> list[dict]:
    """Mensagens desta loja nas últimas `horas` sem nenhuma resposta (Léo ou vendedor) depois.
    Fica de fora: loja em teste com número que não é de teste (o Léo não responde mesmo) e cliente
    com vendedor no comando. Uma linha por cliente (a mais antiga sem resposta)."""
    from app.estado_loja import pode_responder
    from app.handoff import estado_do_handoff
    from banco import conectar
    loja_id = exigir_loja(loja_id)
    desde = para_banco((agora or agora_utc()) - timedelta(hours=horas))
    candidatas = {}
    for l in _ler():
        if l.get("loja") != loja_id or str(l.get("quando", "")) < desde:
            continue
        chave = (l.get("canal"), l.get("lead"))
        if chave not in candidatas or l["quando"] < candidatas[chave]["quando"]:
            candidatas[chave] = l
    saida = []
    conexao = conectar()
    try:
        for (canal, lead), l in sorted(candidatas.items(), key=lambda par: par[1]["quando"]):
            respondida = conexao.execute(
                "SELECT 1 FROM mensagens WHERE loja_id = ? AND lead_id = ? AND direcao IN ('leo', 'vendedor') "
                "AND criado_em >= ? LIMIT 1", (loja_id, lead, l["quando"])).fetchone()
            if respondida:
                continue
            try:
                if not pode_responder(loja_id, canal, lead) or estado_do_handoff(lead, loja_id) == "humano_assumiu":
                    continue
            except Exception:                  # na dúvida, lista (é só um aviso para a equipe)
                from app.log import logger
                logger("recebidas").exception("Não consegui conferir o estado do cliente.")
            saida.append({"canal": canal, "lead_id": lead, "quando": l["quando"]})
    finally:
        conexao.close()
    return saida


def avisar_ao_ligar(agora: datetime | None = None) -> dict[int, int]:
    """No log: quantas mensagens das últimas 24 h ficaram sem resposta, por loja (número mascarado)."""
    from app.console import id_no_console
    from app.log import logger
    log = logger("recebidas")
    lojas = sorted({l.get("loja") for l in _ler() if isinstance(l.get("loja"), int)})
    contagem = {}
    for loja in lojas:
        pendentes = sem_resposta(loja, agora=agora)
        if pendentes:
            contagem[loja] = len(pendentes)
            log.warning(f"[Recebidas][loja {loja}] {len(pendentes)} mensagem(ns) das últimas 24 h sem resposta "
                        "(veja o painel do operador; o Léo não responde sozinho):")
            for p in pendentes:
                log.warning(f"    {p['quando']} UTC  {p['canal']}  {id_no_console(p['lead_id'], p['canal'])}")
    return contagem

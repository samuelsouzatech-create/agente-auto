"""
Maratona 3, N3: SQLite (WAL + espera), caderno de recebidas antes do 200, lista do que ficou sem
resposta, registro técnico com rotação. OFFLINE, duas lojas.
"""
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from app import recebidas

AGORA = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)


def _sql(sql, parametros=()):
    conexao = banco.conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


def _no_ar(*lojas):
    _sql("INSERT OR IGNORE INTO lojas (id, nome, segmento, config) VALUES (2, 'Loja B', 'veiculos', '{}')")
    for loja in lojas:
        _sql("INSERT OR REPLACE INTO estado_lojas (loja_id, estado) VALUES (?, 'no_ar')", (loja,))


def _quando(horas_atras):
    return (AGORA - timedelta(hours=horas_atras)).strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------ #14 SQLite

def test_conexao_em_wal_com_espera_de_5s():
    conexao = banco.conectar()
    try:
        assert conexao.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conexao.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        conexao.close()


def test_duas_escritas_ao_mesmo_tempo_nao_dao_database_is_locked():
    erros, pronto = [], threading.Event()

    def segura_a_escrita():
        conexao = banco.conectar()
        try:
            conexao.execute("BEGIN IMMEDIATE")
            conexao.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo) "
                            "VALUES ('a', 1, 'whatsapp', 'cliente', 'primeira')")
            pronto.set()
            time.sleep(0.8)                  # a outra escrita chega enquanto esta segura a trava
            conexao.commit()
        except sqlite3.Error as erro:
            erros.append(erro)
        finally:
            conexao.close()

    def escreve_junto():
        pronto.wait(5)
        conexao = banco.conectar()
        try:
            conexao.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo) "
                            "VALUES ('b', 2, 'whatsapp', 'cliente', 'segunda')")
            conexao.commit()
        except sqlite3.Error as erro:
            erros.append(erro)
        finally:
            conexao.close()

    a, b = threading.Thread(target=segura_a_escrita), threading.Thread(target=escreve_junto)
    a.start(), b.start()
    a.join(10), b.join(10)
    assert erros == []
    conexao = banco.conectar()
    try:
        assert {r[0] for r in conexao.execute("SELECT conteudo FROM mensagens")} == {"primeira", "segunda"}
    finally:
        conexao.close()


# ------------------------------------------------------------ #15 caderno de recebidas

def test_anotar_nao_guarda_o_texto(tmp_path):
    recebidas.anotar(1, "whatsapp", "5581999991234", "wamid.1", agora=AGORA)
    with open(recebidas._caminho(), encoding="utf-8") as arquivo:
        [linha] = [json.loads(l) for l in arquivo]
    assert linha == {"loja": 1, "canal": "whatsapp", "lead": "5581999991234", "id": "wamid.1",
                     "quando": "2026-11-20 15:00:00"}


def test_sem_resposta_lista_so_o_que_ficou_sem_resposta_e_por_loja():
    _no_ar(1, 2)
    recebidas.anotar(1, "whatsapp", "5581911110001", "m1", agora=AGORA - timedelta(hours=2))   # sem resposta
    recebidas.anotar(1, "whatsapp", "5581911110002", "m2", agora=AGORA - timedelta(hours=3))   # respondida
    _sql("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
         "VALUES ('5581911110002', 1, 'whatsapp', 'leo', 'Oi!', ?)", (_quando(2.9),))
    recebidas.anotar(1, "whatsapp", "5581911110003", "m3", agora=AGORA - timedelta(hours=30))  # velha
    recebidas.anotar(2, "whatsapp", "5581922220001", "m4", agora=AGORA - timedelta(hours=1))   # loja B
    lista_a = recebidas.sem_resposta(1, agora=AGORA)
    assert [p["lead_id"] for p in lista_a] == ["5581911110001"]
    assert [p["lead_id"] for p in recebidas.sem_resposta(2, agora=AGORA)] == ["5581922220001"]


def test_sem_resposta_pula_vendedor_no_comando_e_loja_em_teste():
    _no_ar(1)
    recebidas.anotar(1, "whatsapp", "5581911110009", "m1", agora=AGORA - timedelta(hours=1))
    _sql("INSERT INTO handoffs (lead_id, loja_id, motivo, resumo, estado) "
         "VALUES ('5581911110009', 1, 'x', 'x', 'humano_assumiu')")
    recebidas.anotar(2, "whatsapp", "5581922229999", "m2", agora=AGORA - timedelta(hours=1))   # B em teste
    _sql("INSERT OR IGNORE INTO lojas (id, nome, segmento, config) VALUES (2, 'Loja B', 'veiculos', '{}')")
    assert recebidas.sem_resposta(1, agora=AGORA) == []
    assert recebidas.sem_resposta(2, agora=AGORA) == []


def test_avisar_ao_ligar_vai_para_o_log_com_numero_mascarado(capsys):
    from app import logs
    _no_ar(1)
    recebidas.anotar(1, "whatsapp", "5581911114321", "m1", agora=AGORA - timedelta(hours=1))
    assert recebidas.avisar_ao_ligar(agora=AGORA) == {1: 1}
    saida = capsys.readouterr().out
    assert "****4321" in saida and "5581911114321" not in saida
    with open(os.path.join(logs.PASTA_LOGS, "leo.log"), encoding="utf-8") as arquivo:
        texto = arquivo.read()
    assert "sem resposta" in texto and "5581911114321" not in texto


SEGREDO = "segredo-n3"


def test_webhook_anota_antes_de_responder_200(monkeypatch):
    from fastapi.testclient import TestClient
    import app.api.webhook as wh
    from app.canais import cadastrar_canal
    cadastrar_canal(1, "whatsapp", "PNID_N3")
    agendadas = []

    async def nao_processa(*args, **kwargs):
        agendadas.append(args)
    monkeypatch.setattr(wh, "processar_mensagem", nao_processa)
    monkeypatch.setattr(wh, "WHATSAPP_APP_SECRET", SEGREDO)
    corpo = json.dumps({"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "PNID_N3"},
        "messages": [{"id": "wamid.n3", "from": "5581999995555", "type": "text", "text": {"body": "oi"}}]}}]}]}).encode()
    assinatura = "sha256=" + hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()
    resposta = TestClient(wh.app).post("/webhook", content=corpo,
                                       headers={"Content-Type": "application/json", "X-Hub-Signature-256": assinatura})
    assert resposta.status_code == 200
    linhas = [json.loads(l) for l in open(recebidas._caminho(), encoding="utf-8")]
    assert [(l["loja"], l["lead"], l["id"]) for l in linhas] == [(1, "5581999995555", "wamid.n3")]
    assert "oi" not in json.dumps(linhas)


# ------------------------------------------------------------ #20 registro técnico

def test_logger_grava_em_leo_log_com_rotacao_e_erro_com_rastro():
    from app import logs
    from app.log import COPIAS, TAMANHO_MAXIMO, logger
    assert (TAMANHO_MAXIMO, COPIAS) == (5 * 1024 * 1024, 5)
    log = logger("teste")
    try:
        raise ValueError("falha de teste")
    except ValueError:
        log.exception("Algo deu errado")
    with open(os.path.join(logs.PASTA_LOGS, "leo.log"), encoding="utf-8") as arquivo:
        texto = arquivo.read()
    assert "ERROR [leo.teste] Algo deu errado" in texto and "ValueError: falha de teste" in texto


def test_except_que_engolia_erro_agora_registra():
    from app import logs
    from app.core.montagem import fuso_da_loja
    from types import SimpleNamespace
    assert str(fuso_da_loja(SimpleNamespace(config={"fuso": "Lugar/Nenhum"}))) == "America/Recife"
    with open(os.path.join(logs.PASTA_LOGS, "leo.log"), encoding="utf-8") as arquivo:
        assert "Fuso da loja inválido" in arquivo.read()

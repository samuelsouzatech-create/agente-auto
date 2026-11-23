"""
Maratona 3, N1: segurança e privacidade. OFFLINE, LLM falso, duas lojas.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from app import demo
from app.console import id_no_console, texto_no_console

RAIZ = Path(__file__).resolve().parents[1]


def _ler(sql, parametros=()):
    conexao = banco.conectar()
    try:
        return [dict(l) for l in conexao.execute(sql, parametros).fetchall()]
    finally:
        conexao.close()


def _sql(sql, parametros=()):
    conexao = banco.conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


# ------------------------------------------------------------ #1 e #24: loja demo

def test_criar_demo_com_loja_id_de_loja_real_recusa_e_nao_apaga(tmp_path):
    from app.ator import como_sistema
    _sql("INSERT OR IGNORE INTO lojas (id, nome, segmento, config) VALUES (2, 'Loja B', 'veiculos', '{}')")
    for loja in (1, 2):
        _sql("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo) VALUES ('c', ?, 'whatsapp', 'cliente', 'oi')",
             (loja,))
    with como_sistema("Teste", "job"):
        for loja in (1, 2):
            with pytest.raises(demo.LojaNaoEDemo):
                demo.criar_loja_demo(loja_id=loja, indexar=False, com_historico=False)
    assert len(_ler("SELECT id FROM mensagens")) == 2
    assert {l["nome"] for l in _ler("SELECT nome FROM lojas")} >= {"Loja B"}
    assert demo.NOME_DEMO not in {l["nome"] for l in _ler("SELECT nome FROM lojas")}


def test_criar_demo_com_loja_id_que_ja_e_demo_aceita(tmp_path):
    from app.ator import como_sistema
    _sql("UPDATE lojas SET config = ? WHERE id = 1", (json.dumps({"demo": True}),))
    with como_sistema("Teste", "job"):
        assert demo.criar_loja_demo(loja_id=1, indexar=False, com_historico=False) == 1
    assert _ler("SELECT nome FROM lojas WHERE id = 1")[0]["nome"] == demo.NOME_DEMO


def test_demo_entra_no_ar_pelo_registro(tmp_path):
    from app.ator import como_sistema
    with como_sistema("Teste", "job"):
        loja = demo.criar_loja_demo(indexar=False, com_historico=False)
    assert _ler("SELECT estado FROM estado_lojas WHERE loja_id = ?", (loja,))[0]["estado"] == "no_ar"
    linhas = _ler("SELECT papel, loja_id FROM registro_acoes WHERE acao = 'colocar_no_ar'")
    assert linhas == [{"papel": "operador", "loja_id": loja}]
    with como_sistema("Teste", "job"):                      # reiniciar: já no ar, nada novo no Registro
        demo.criar_loja_demo(indexar=False, com_historico=False)
    assert len(_ler("SELECT id FROM registro_acoes WHERE acao = 'colocar_no_ar'")) == 1


# ------------------------------------------------------------ #2: console

def test_console_canal_real_esconde_texto_e_numero():
    assert id_no_console("5581999991234", "whatsapp") == "****1234"
    assert id_no_console("123456789", "telegram") == "****6789"
    assert texto_no_console("quero o Corolla, meu CPF é 123", "instagram") == "(texto oculto, 30 caracteres)"


def test_console_simulador_e_bancada_sem_mudanca():
    assert id_no_console("bancada-preco-carro", "simulador") == "bancada-preco-carro"
    assert id_no_console("sim-ab12cd34", "simulador") == "sim-ab12cd34"
    assert texto_no_console("oi, tem Civic?", "simulador") == "oi, tem Civic?"
    assert id_no_console("bancada-x") == "bancada-x"                    # canal desconhecido, id não é telefone
    assert id_no_console("5581999991234") == "****1234"                 # canal desconhecido, id é telefone


class Grafo:
    def invoke(self, entrada, config=None):
        return {"messages": [HumanMessage(content=entrada["messages"][0].content),
                             AIMessage(content="Temos sim, o Civic está disponível.")]}


def test_turno_canal_real_nao_imprime_texto_nem_numero(capsys):
    from app.core.turno import executar_turno
    _sql("INSERT OR REPLACE INTO estado_lojas (loja_id, estado) VALUES (1, 'no_ar')")
    asyncio.run(executar_turno(1, "whatsapp", "5581999991234", "meu nome é Joana, tem Civic?", grafo=Grafo()))
    saida = capsys.readouterr().out
    assert "5581999991234" not in saida and "****1234" in saida
    assert "Joana" not in saida and "Civic" not in saida


def test_turno_simulador_imprime_igual(capsys):
    from app.core.turno import executar_turno
    asyncio.run(executar_turno(1, "simulador", "sim-teste", "tem Civic?", grafo=Grafo()))
    saida = capsys.readouterr().out
    assert "sim-teste disse: tem Civic?" in saida and "Léo responde: Temos sim" in saida


def test_loja_em_teste_numero_mascarado(capsys):
    from app.core.turno import porta_fechada
    assert porta_fechada(2, "whatsapp", "5581988887777") is True
    saida = capsys.readouterr().out
    assert "5581988887777" not in saida and "****7777" in saida


# ------------------------------------------------------------ #3: token do webhook

@pytest.fixture
def webhook(monkeypatch):
    from fastapi.testclient import TestClient
    import app.api.webhook as wh
    return wh, TestClient(wh.app)


def _verificar(cliente, token):
    return cliente.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": token,
                                           "hub.challenge": "desafio-123"})


def test_sem_token_no_ambiente_falha_fechada(webhook, monkeypatch):
    wh, cliente = webhook
    monkeypatch.setattr(wh, "WHATSAPP_VERIFY_TOKEN", "")
    for tentativa in ("", "leo-webhook-2026", "qualquer"):
        assert _verificar(cliente, tentativa).status_code == 403
    assert "WHATSAPP_VERIFY_TOKEN" in wh.avisar_configuracao()


def test_com_token_aceita_so_o_certo(webhook, monkeypatch):
    wh, cliente = webhook
    monkeypatch.setattr(wh, "WHATSAPP_VERIFY_TOKEN", "token-certo")
    resposta = _verificar(cliente, "token-certo")
    assert resposta.status_code == 200 and resposta.text == "desafio-123"
    assert _verificar(cliente, "token-errado").status_code == 403
    assert "WHATSAPP_VERIFY_TOKEN" not in wh.avisar_configuracao()


def test_codigo_sem_token_padrao():
    texto = (RAIZ / "app" / "config.py").read_text(encoding="utf-8")
    assert "leo-webhook-2026" not in texto


# ------------------------------------------------------------ #28/#29: dependências

def test_requirements_fixa_pillow_e_google_genai():
    linhas = (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert "pillow==12.3.0" in linhas and "google-genai==2.33.0" in linhas

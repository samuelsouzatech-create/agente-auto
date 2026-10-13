import os
import sys
import sqlite3
import tempfile
import pytest

# Garante que o Python encontre os módulos da raiz do projeto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from banco import criar_tabelas
from tools import registrar_lead, registrar_troca, agendar_visita, acionar_handoff


@pytest.fixture
def banco_temporario(monkeypatch):
    """Cria um banco SQLite temporário e isolado para cada teste.
    Redireciona o CAMINHO_BANCO do módulo banco para esse arquivo,
    cria as tabelas, entrega o caminho ao teste e apaga tudo no fim."""
    # Cria um arquivo temporário para o banco
    fd, caminho = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # Redireciona o módulo banco para usar esse arquivo
    monkeypatch.setattr(banco, "CAMINHO_BANCO", caminho)

    # Cria as tabelas no banco temporário
    criar_tabelas()

    # Entrega o caminho ao teste
    yield caminho

    # Teardown: apaga o banco temporário depois do teste
    if os.path.exists(caminho):
        os.remove(caminho)


def contar_linhas(caminho, tabela):
    """Função auxiliar: conta quantas linhas há numa tabela."""
    conexao = sqlite3.connect(caminho)
    cursor = conexao.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {tabela}")
    total = cursor.fetchone()[0]
    conexao.close()
    return total


def buscar_lead(caminho, lead_id):
    """Função auxiliar: busca um lead pelo lead_id e retorna como dict."""
    conexao = sqlite3.connect(caminho)
    conexao.row_factory = sqlite3.Row
    cursor = conexao.cursor()
    cursor.execute("SELECT * FROM leads WHERE lead_id = ?", (lead_id,))
    linha = cursor.fetchone()
    conexao.close()
    return dict(linha) if linha else None


# --- Testes do upsert do registrar_lead (prova do bug 2 corrigido) ---

def test_registrar_lead_cria_uma_linha(banco_temporario):
    registrar_lead.invoke({
        "nome": "João",
        "interesse": "Civic",
        "lead_id": "conversa-1"
    })
    assert contar_linhas(banco_temporario, "leads") == 1


def test_registrar_lead_nao_duplica_mesma_conversa(banco_temporario):
    # Duas chamadas com o MESMO lead_id devem gerar UMA linha só
    registrar_lead.invoke({
        "nome": "João", "interesse": "Civic", "lead_id": "conversa-1"
    })
    registrar_lead.invoke({
        "nome": "João", "interesse": "Civic",
        "forma_pagamento": "financiado", "lead_id": "conversa-1"
    })
    assert contar_linhas(banco_temporario, "leads") == 1


def test_registrar_lead_completa_campos(banco_temporario):
    # Primeira chamada sem forma de pagamento
    registrar_lead.invoke({
        "nome": "Maria", "interesse": "Onix", "lead_id": "conversa-2"
    })
    # Segunda chamada adiciona forma de pagamento, sem repetir o resto
    registrar_lead.invoke({
        "nome": "", "interesse": "", "forma_pagamento": "à vista",
        "lead_id": "conversa-2"
    })
    lead = buscar_lead(banco_temporario, "conversa-2")
    # O nome antigo deve ser preservado (não apagado pela string vazia)
    assert lead["nome"] == "Maria"
    assert lead["interesse"] == "Onix"
    # E a forma de pagamento nova deve ter entrado
    assert lead["forma_pagamento"] == "à vista"


def test_registrar_lead_conversas_diferentes_sao_separadas(banco_temporario):
    registrar_lead.invoke({
        "nome": "João", "interesse": "Civic", "lead_id": "conversa-1"
    })
    registrar_lead.invoke({
        "nome": "Maria", "interesse": "Onix", "lead_id": "conversa-2"
    })
    # Dois lead_id diferentes = duas linhas
    assert contar_linhas(banco_temporario, "leads") == 2


# --- Testes das outras tools de escrita ---

def test_registrar_troca_grava_com_lead_id(banco_temporario):
    resultado = registrar_troca.invoke({
        "modelo": "Gol", "ano": 2015, "km": 90000,
        "estado": "bom", "lead_id": "conversa-1"
    })
    assert contar_linhas(banco_temporario, "trocas") == 1
    # A tool NUNCA pode dar valor de avaliação
    assert "presencialmente" in resultado.lower()


def test_agendar_visita_grava(banco_temporario):
    registrar = agendar_visita.invoke({
        "nome_cliente": "João", "tipo": "visita",
        "data_hora": "sábado 10h", "lead_id": "conversa-1"
    })
    assert contar_linhas(banco_temporario, "agendamentos") == 1


def test_acionar_handoff_grava_aguardando_humano(banco_temporario):
    acionar_handoff.invoke({
        "motivo": "cliente pediu desconto",
        "resumo": "lead quente", "lead_id": "conversa-1"
    })
    assert contar_linhas(banco_temporario, "handoffs") == 1

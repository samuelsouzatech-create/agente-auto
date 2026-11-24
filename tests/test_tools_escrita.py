import os
import sys
import tempfile
import pytest

# Garante que o Python encontre os módulos da raiz do projeto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from banco import criar_tabelas
from tools import registrar_lead, agendar_visita, acionar_handoff
from segmentos.veiculos.registrar_troca import registrar_troca

from datetime import datetime
from zoneinfo import ZoneInfo

# H14: a ferramenta agora confere o dia de verdade. "segunda" dita NA segunda
# vira pergunta ao cliente (e "sábado" dito NO sábado também). Para o teste
# não depender do dia em que roda, usamos um dia útil que NÃO é hoje.
# M1 (L13): o relógio do teste é FIXO. Antes, o dia era escolhido na carga do arquivo e a
# suíte que atravessava a meia-noite quebrava (o dia escolhido virava "hoje"). Quarta 18/11/2026,
# 10:00 em Recife; a visita é na quinta (dia útil que não é hoje).
from datetime import timezone as _tz

AGORA_FIXA = datetime(2026, 11, 18, 13, 0, tzinfo=_tz.utc)
DIA_DA_VISITA = "quinta"


@pytest.fixture(autouse=True)
def relogio_fixo(monkeypatch):
    from app import relogio
    monkeypatch.setattr(relogio, "agora_utc", lambda: AGORA_FIXA)


def contar_linhas(caminho, tabela):
    """Função auxiliar: conta quantas linhas há numa tabela."""
    conexao = banco.conectar()
    cursor = conexao.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {tabela}")
    total = cursor.fetchone()[0]
    conexao.close()
    return total


def buscar_lead(caminho, lead_id):
    """Função auxiliar: busca um lead pelo lead_id e retorna como dict."""
    conexao = banco.conectar()
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
        "loja_id": 1, "lead_id": "conversa-1"
    })
    assert contar_linhas(banco_temporario, "leads") == 1


def test_registrar_lead_nao_duplica_mesma_conversa(banco_temporario):
    # Duas chamadas com o MESMO lead_id devem gerar UMA linha só
    registrar_lead.invoke({
        "nome": "João", "interesse": "Civic", "loja_id": 1, "lead_id": "conversa-1"
    })
    registrar_lead.invoke({
        "nome": "João", "interesse": "Civic",
        "forma_pagamento": "financiado", "loja_id": 1, "lead_id": "conversa-1"
    })
    assert contar_linhas(banco_temporario, "leads") == 1


def test_registrar_lead_completa_campos(banco_temporario):
    # Primeira chamada sem forma de pagamento
    registrar_lead.invoke({
        "nome": "Maria", "interesse": "Onix", "loja_id": 1, "lead_id": "conversa-2"
    })
    # Segunda chamada adiciona forma de pagamento, sem repetir o resto
    registrar_lead.invoke({
        "nome": "", "interesse": "", "forma_pagamento": "à vista",
        "loja_id": 1, "lead_id": "conversa-2"
    })
    lead = buscar_lead(banco_temporario, "conversa-2")
    # O nome antigo deve ser preservado (não apagado pela string vazia)
    assert lead["nome"] == "Maria"
    assert lead["interesse"] == "Onix"
    # E a forma de pagamento nova deve ter entrado
    assert lead["forma_pagamento"] == "à vista"


def test_registrar_lead_conversas_diferentes_sao_separadas(banco_temporario):
    registrar_lead.invoke({
        "nome": "João", "interesse": "Civic", "loja_id": 1, "lead_id": "conversa-1"
    })
    registrar_lead.invoke({
        "nome": "Maria", "interesse": "Onix", "loja_id": 1, "lead_id": "conversa-2"
    })
    # Dois lead_id diferentes = duas linhas
    assert contar_linhas(banco_temporario, "leads") == 2


# --- Testes das outras tools de escrita ---

def test_registrar_troca_grava_com_lead_id(banco_temporario):
    resultado = registrar_troca.invoke({
        "modelo": "Gol", "ano": 2015, "km": 90000,
        "estado": "bom", "loja_id": 1, "lead_id": "conversa-1"
    })
    assert contar_linhas(banco_temporario, "trocas") == 1
    # A tool NUNCA pode dar valor de avaliação
    assert "presencialmente" in resultado.lower()


def test_agendar_visita_grava(banco_temporario):
    agendar_visita.invoke({
        "nome_cliente": "João", "tipo": "visita",
        "data_hora": DIA_DA_VISITA + " 10h", "loja_id": 1, "lead_id": "conversa-1"
    })
    assert contar_linhas(banco_temporario, "agendamentos") == 1
    # Confere que os dados foram realmente gravados, não só a linha criada
    conexao = banco.conectar()
    cursor = conexao.cursor()
    cursor.execute("SELECT * FROM agendamentos WHERE lead_id = ?", ("conversa-1",))
    linha = cursor.fetchone()
    conexao.close()
    assert linha["nome_cliente"] == "João"
    assert linha["tipo"] == "visita"

def test_acionar_handoff_grava_aguardando_humano(banco_temporario):
    acionar_handoff.invoke({
        "motivo": "cliente pediu desconto",
        "resumo": "lead quente", "loja_id": 1, "lead_id": "conversa-1"
    })
    assert contar_linhas(banco_temporario, "handoffs") == 1

# --- Testes do upsert do agendar_visita (item 3 da revisão) ---

def test_agendar_visita_remarcar_nao_duplica(banco_temporario):
    # Mesmo lead, mesmo tipo, horário diferente = remarcação, NÃO duplicação.
    agendar_visita.invoke({
        "nome_cliente": "Marina", "tipo": "visita",
        "data_hora": DIA_DA_VISITA + " 10h", "loja_id": 1, "lead_id": "conversa-rem"
    })
    agendar_visita.invoke({
        "nome_cliente": "Marina", "tipo": "visita",
        "data_hora": DIA_DA_VISITA + " 11h", "loja_id": 1, "lead_id": "conversa-rem"
    })
    # Deve existir UMA linha só...
    assert contar_linhas(banco_temporario, "agendamentos") == 1
    # ...e com o horário ATUALIZADO (o segundo).
    conexao = banco.conectar()
    cursor = conexao.cursor()
    cursor.execute("SELECT * FROM agendamentos WHERE lead_id = ?", ("conversa-rem",))
    linha = cursor.fetchone()
    conexao.close()
    # H14b: o banco guarda a data já resolvida (ex.: "quarta, 18/11, às 11:00").
    assert "11:00" in linha["data_hora"]


def test_agendar_visita_tipos_diferentes_sao_separados(banco_temporario):
    # Mesmo lead, mas tipos diferentes = agendamentos separados (visita + ligação).
    agendar_visita.invoke({
        "nome_cliente": "Marina", "tipo": "visita",
        "data_hora": DIA_DA_VISITA + " 10h", "loja_id": 1, "lead_id": "conversa-tipos"
    })
    agendar_visita.invoke({
        "nome_cliente": "Marina", "tipo": "ligacao",
        "data_hora": DIA_DA_VISITA + " 14h", "loja_id": 1, "lead_id": "conversa-tipos"
    })
    assert contar_linhas(banco_temporario, "agendamentos") == 2


# --- Testes do upsert do acionar_handoff (item 4 da revisão) ---

def test_acionar_handoff_nao_duplica_mesmo_lead(banco_temporario):
    # Dois pedidos vermelhos do mesmo lead = UMA linha na fila do vendedor.
    acionar_handoff.invoke({
        "motivo": "cliente pediu desconto",
        "resumo": "lead quente, quer Onix", "loja_id": 1, "lead_id": "conversa-hand"
    })
    acionar_handoff.invoke({
        "motivo": "cliente quer falar com vendedor",
        "resumo": "lead quente, quer Onix, insistindo", "loja_id": 1, "lead_id": "conversa-hand"
    })
    # Uma linha só...
    assert contar_linhas(banco_temporario, "handoffs") == 1
    # ...com o motivo/resumo ATUALIZADOS (os do segundo pedido).
    conexao = banco.conectar()
    cursor = conexao.cursor()
    cursor.execute("SELECT * FROM handoffs WHERE lead_id = ?", ("conversa-hand",))
    linha = cursor.fetchone()
    conexao.close()
    # L5c: o motivo novo não apaga o anterior ("<antigo> | <novo>").
    assert linha["motivo"] == "cliente pediu desconto | cliente quer falar com vendedor"
    assert linha["estado"] == "aguardando_humano"


def test_acionar_handoff_leads_diferentes_sao_separados(banco_temporario):
    acionar_handoff.invoke({
        "motivo": "desconto", "resumo": "lead A", "loja_id": 1, "lead_id": "lead-a"
    })
    acionar_handoff.invoke({
        "motivo": "reclamação", "resumo": "lead B", "loja_id": 1, "lead_id": "lead-b"
    })
    assert contar_linhas(banco_temporario, "handoffs") == 2


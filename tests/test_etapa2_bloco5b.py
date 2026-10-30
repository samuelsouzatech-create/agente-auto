"""
Testes da Etapa 2, Bloco 5B: o assistente reconhece quem já comprou.
Telefone normalizado, gancho do segmento, camada do prompt e regras de pós-venda.
"""
from datetime import date, datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from banco import conectar
from app import cliente_da_casa
from app.cliente_da_casa import compras_do_cliente
from app.core.montagem import PASTA_PROMPTS, ferramentas_da_loja, montar_prompt
from app.jobs.pos_venda import e_pos_venda
from app.lojas import carregar_loja
from app.segmentos import modulo_do_segmento
from app.telefone import normalizar_telefone_br

# Modelo do payload que a Meta manda (número fictício). O wa_id vem SEM o 9.
# Quando tiver um payload real do seu número de teste, troque aqui.
PAYLOAD_WHATSAPP = {
    "object": "whatsapp_business_account",
    "entry": [{"id": "000", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "5581300000000", "phone_number_id": "111"},
        "contacts": [{"profile": {"name": "Ana"}, "wa_id": "558199998888"}],
        "messages": [{"from": "558199998888", "id": "wamid.TESTE", "timestamp": "1761832800",
                      "type": "text", "text": {"body": "comprei um carro aí mês passado"}}],
    }}]}],
}


def _carro(loja_id, marca, modelo):
    c = conectar()
    try:
        novo = c.execute(
            "INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) "
            "VALUES (?, ?, ?, 2019, 48000, 'Branco', 'Automático', 98000, 'vendido')",
            (loja_id, marca, modelo)).lastrowid
        c.commit()
    finally:
        c.close()
    return novo


def _venda(lead_id, *, loja_id=1, data="2026-09-15", forma="avista", meses=None,
           marca="Honda", modelo="Civic"):
    carro = _carro(loja_id, marca, modelo)
    c = conectar()
    try:
        c.execute(
            "INSERT INTO vendas (loja_id, lead_id, veiculo_id, data_venda, forma_pagamento, "
            "meses_financiamento) VALUES (?, ?, ?, ?, ?, ?)",
            (loja_id, lead_id, carro, data, forma, meses))
        c.commit()
    finally:
        c.close()


def _loja_2():
    c = conectar()
    try:
        c.execute("INSERT OR IGNORE INTO lojas (id, nome, segmento, config) "
                  "VALUES (2, 'Loja 2', 'veiculos', '{}')")
        c.commit()
    finally:
        c.close()


def _comprador():
    return modulo_do_segmento("veiculos", "comprador")


# ------------------------------------------------------------ telefone

@pytest.mark.parametrize("entrada, esperado", [
    ("+55 (81) 99999-8888", "5581999998888"),
    ("5581999998888", "5581999998888"),
    ("558199998888", "5581999998888"),       # como o WhatsApp manda: sem o 9
    ("(81) 9999-8888", "5581999998888"),     # formato antigo
    ("081 99999-8888", "5581999998888"),
])
def test_normalizar_telefone(entrada, esperado):
    assert normalizar_telefone_br(entrada) == esperado


@pytest.mark.parametrize("entrada", [
    "", None, "abc", "1150554263", "8838349362", "(81) 3333-4444", "5500999998888",
])
def test_o_que_nao_e_celular_volta_vazio(entrada):
    assert normalizar_telefone_br(entrada) == ""


def test_payload_do_whatsapp():
    valor = PAYLOAD_WHATSAPP["entry"][0]["changes"][0]["value"]
    assert normalizar_telefone_br(valor["messages"][0]["from"]) == normalizar_telefone_br("+55 (81) 99999-8888")
    assert normalizar_telefone_br(valor["contacts"][0]["wa_id"]) == "5581999998888"


# ------------------------------------------------------------ gancho do segmento

def test_reconhece_pelo_mesmo_contato():
    _venda("1150554263", data="2026-10-29")
    compras = _comprador().contexto_do_lead(1, "1150554263", "telegram")
    assert len(compras) == 1
    assert compras[0]["descricao"] == "Honda Civic 2019"
    assert compras[0]["data"] == date(2026, 10, 29)
    assert compras[0]["detalhe"] == "à vista"


def test_whatsapp_acha_com_ou_sem_o_9():
    _venda("5581999998888")
    assert len(_comprador().contexto_do_lead(1, "558199998888", "whatsapp")) == 1


def test_telegram_nao_compara_telefone():
    _venda("5581999998888")
    assert _comprador().contexto_do_lead(1, "81999998888", "telegram") == []


def test_compra_de_outra_loja_nao_aparece():
    _loja_2()
    _venda("5581999998888", loja_id=2)
    assert _comprador().contexto_do_lead(1, "5581999998888", "whatsapp") == []
    assert len(_comprador().contexto_do_lead(2, "5581999998888", "whatsapp")) == 1


def test_detalhe_do_financiamento():
    _venda("5581999998888", forma="financiado", meses=48)
    assert _comprador().contexto_do_lead(1, "5581999998888", "whatsapp")[0]["detalhe"] == "financiado em 48x"


def test_mais_recente_primeiro():
    _venda("x1", data="2025-01-10", marca="Volkswagen", modelo="Gol")
    _venda("x1", data="2026-09-15")
    nomes = [c["descricao"] for c in _comprador().contexto_do_lead(1, "x1", "telegram")]
    assert nomes == ["Honda Civic 2019", "Volkswagen Gol 2019"]


# ------------------------------------------------------------ motor

def test_sem_compra_e_lead_normal():
    assert compras_do_cliente(carregar_loja(1), "999", "telegram") == []


def test_falha_no_banco_segue_como_lead_normal(monkeypatch):
    def quebra(*a, **k):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(cliente_da_casa, "modulo_do_segmento", quebra)
    assert compras_do_cliente(carregar_loja(1), "1150554263", "telegram") == []


def test_segmento_sem_gancho(monkeypatch):
    _venda("1150554263")
    monkeypatch.setattr(cliente_da_casa, "modulo_do_segmento", lambda *a: None)
    assert compras_do_cliente(carregar_loja(1), "1150554263", "telegram") == []


# ------------------------------------------------------------ prompt

def _prompt(compras=None):
    loja = carregar_loja(1)
    return montar_prompt(loja, ferramentas_da_loja(loja), datetime(2026, 10, 30, 10, 0), compras=compras)


def test_camada_so_aparece_para_quem_comprou():
    assert "CLIENTE QUE JÁ COMPROU" not in _prompt()
    p = _prompt([{"descricao": "Honda Civic 2019", "data": date(2026, 9, 15), "detalhe": "à vista"}])
    assert "CLIENTE QUE JÁ COMPROU" in p
    assert "Honda Civic 2019 em 15/09/2026 (à vista)" in p


def test_regras_de_pos_venda_no_prompt_base():
    texto = (PASTA_PROMPTS / "base.md").read_text(encoding="utf-8")
    assert "PÓS-VENDA:" in texto
    assert "compra não localizada pelo telefone" in texto
    assert '"Já comprei em outro lugar"' in texto
    # O job do 5A precisa reconhecer o motivo que o prompt manda usar.
    assert e_pos_venda("PÓS-VENDA: compra não localizada pelo telefone")


def test_assistente_recebe_a_compra_no_prompt(monkeypatch):
    from app.core import agent
    _venda("1150554263", data="2026-10-29")
    vistos = []

    class LLMFalso:
        def invoke(self, mensagens):
            vistos.append(mensagens)
            return AIMessage(content="ok")

    monkeypatch.setattr(agent, "llm", LLMFalso())
    agent.no_agente({"messages": [HumanMessage(content="oi")], "lead_id": "1150554263",
                     "loja_id": 1, "canal": "telegram"})
    papel, prompt = vistos[0][0]
    assert papel == "system"
    assert "CLIENTE QUE JÁ COMPROU" in prompt and "Honda Civic 2019" in prompt

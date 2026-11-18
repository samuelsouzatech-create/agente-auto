"""
L6: pós-venda e cliente irritado, pelo CÓDIGO. Offline, LLM falso, duas lojas.
  - quem comprou e relata problema: chamado "PÓS-VENDA: ..." na mesma fala (o job lê isso);
  - irritado/ameaça (Procon, advogado, Reclame Aqui): chamado com URGENTE;
  - chamado aberto pela IA ganha as marcas; "tá tudo ótimo" não abre nada.
"""
import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import banco
from app import lojas
from app.guarda_politica import (cliente_ameacou, motivo_com_marcas, relatou_problema_da_compra)
from app.jobs.pos_venda import e_pos_venda

LOJA_A, LOJA_B = 1, 2
LEAD = "5581933332222"


def _sql(sql, parametros=()):
    conexao = banco.conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


def _ler(sql, parametros=()):
    conexao = banco.conectar()
    try:
        return [dict(l) for l in conexao.execute(sql, parametros).fetchall()]
    finally:
        conexao.close()


@pytest.fixture
def duas_lojas():
    for loja_id in (LOJA_A, LOJA_B):
        if not _ler("SELECT id FROM lojas WHERE id = ?", (loja_id,)):
            _sql("INSERT INTO lojas (id, nome, segmento, config) VALUES (?, ?, 'veiculos', '{}')",
                 (loja_id, f"Loja {loja_id}"))
    lojas.limpar_cache()


def _comprou(loja_id, lead=LEAD):
    _sql("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) "
         "VALUES (?, 'Chevrolet', 'Onix', 2020, 40000, 'Prata', 'Manual', 68000, 'vendido')", (loja_id,))
    carro = _ler("SELECT MAX(id) id FROM estoque")[0]["id"]
    _sql("INSERT INTO vendas (loja_id, lead_id, veiculo_id, data_venda, forma_pagamento) "
         "VALUES (?, ?, ?, '2026-11-10', 'avista')", (loja_id, lead, carro))


class GrafoFalso:
    def __init__(self, resposta="Sinto muito. Vou ver isso."):
        self.resposta = resposta

    def invoke(self, entrada, config=None):
        return {"messages": [HumanMessage(content=entrada["messages"][0].content),
                             AIMessage(content=self.resposta)]}


def _turno(loja_id, texto, grafo=None, lead=LEAD):
    from app.core.turno import executar_turno
    return asyncio.run(executar_turno(loja_id, "simulador", lead, texto, grafo=grafo or GrafoFalso()))


def _motivos(loja_id, lead=LEAD):
    return [h["motivo"] for h in _ler("SELECT motivo FROM handoffs WHERE loja_id = ? AND lead_id = ?",
                                      (loja_id, lead))]


@pytest.mark.parametrize("texto,ameaca", [
    ("vou no Procon", True), ("vou chamar meu advogado", True), ("vou te processar", True),
    ("vou botar no Reclame Aqui", True), ("isso é um absurdo", True), ("tá tudo ótimo", False),
    ("o carro tá com um barulho", False),
])
def test_cliente_ameacou(texto, ameaca):
    assert cliente_ameacou(texto) is ameaca


@pytest.mark.parametrize("texto,problema", [
    ("o carro tá fazendo um barulho estranho", True), ("deu defeito no ar", True),
    ("a transferência ainda não saiu", True), ("cadê o documento do carro?", True),
    ("o boleto veio errado", True), ("tá tudo ótimo com o carro", False), ("obrigado!", False),
])
def test_problema_da_compra(texto, problema):
    assert relatou_problema_da_compra(texto) is problema


def test_motivo_com_marcas():
    assert motivo_com_marcas("barulho", pos_venda=True, urgente=False) == "PÓS-VENDA: barulho"
    assert motivo_com_marcas("PÓS-VENDA: barulho", pos_venda=True, urgente=True) == "PÓS-VENDA: URGENTE — barulho"
    assert motivo_com_marcas("quer falar", pos_venda=False, urgente=True) == "URGENTE — quer falar"
    assert motivo_com_marcas("URGENTE — x", pos_venda=False, urgente=True) == "URGENTE — x"
    assert e_pos_venda(motivo_com_marcas("x", pos_venda=True, urgente=True))     # o job continua lendo


def test_quem_comprou_e_relata_problema_ganha_chamado_pos_venda(duas_lojas):
    _comprou(LOJA_A)
    r = _turno(LOJA_A, "o carro tá fazendo um barulho estranho na suspensão")
    assert r.handoff_aberto
    [motivo] = _motivos(LOJA_A)
    assert motivo.startswith("PÓS-VENDA: ") and e_pos_venda(motivo) and "barulho" in motivo
    assert _motivos(LOJA_B) == []


def test_quem_nao_comprou_e_fala_de_problema_nao_vira_pos_venda(duas_lojas):
    _comprou(LOJA_B)                                   # comprou na OUTRA loja
    r = _turno(LOJA_A, "esse carro tem algum problema?", GrafoFalso("Não temos registro de problema."))
    assert not r.handoff_aberto and _motivos(LOJA_A) == []


def test_ameaca_abre_chamado_urgente_mesmo_sem_compra(duas_lojas):
    r = _turno(LOJA_A, "que atendimento péssimo, vou no Procon")
    assert r.handoff_aberto
    assert _motivos(LOJA_A)[0].startswith("URGENTE — ")


def test_comprou_e_ameaca_vira_pos_venda_urgente(duas_lojas):
    _comprou(LOJA_A)
    _turno(LOJA_A, "isso é um absurdo, vou no Reclame Aqui")
    [motivo] = _motivos(LOJA_A)
    assert motivo.startswith("PÓS-VENDA: URGENTE — ") and e_pos_venda(motivo)


def test_chamado_aberto_pela_ia_ganha_as_marcas(duas_lojas):
    from tools import acionar_handoff
    _comprou(LOJA_A)

    class GrafoChama(GrafoFalso):
        def invoke(self, entrada, config=None):
            acionar_handoff.func(motivo="reclamação do cliente", resumo="r", lead_id=LEAD, loja_id=LOJA_A)
            return super().invoke(entrada, config)

    _turno(LOJA_A, "isso é um absurdo, vou no Procon", GrafoChama())
    assert _motivos(LOJA_A) == ["PÓS-VENDA: URGENTE — reclamação do cliente"]


def test_tudo_otimo_nao_abre_chamado(duas_lojas):
    _comprou(LOJA_A)
    r = _turno(LOJA_A, "tá tudo ótimo com o carro, obrigado!", GrafoFalso("Que bom! Obrigado por contar."))
    assert not r.handoff_aberto and _motivos(LOJA_A) == []

"""
P0 (complemento): as 10 ferramentas de tools/ sem loja_id padrão.
Decisão do analista (02/11/2026): a LEGADO tem 31 itens (21 em app/ e 10 em
tools/) e fica vazia no P0. Critério de pronto: a catraca, não o grep.
- Nenhuma ferramenta tem loja_id com valor padrão (obrigatório, só por nome).
- Chamar uma ferramenta sem loja dá erro e não grava nada (nunca cai na loja 1).
- O nó de ferramentas do agente injeta a loja da conversa em todas, mesmo que
  o modelo tente mandar outra.
Tudo offline: banco temporário (conftest), sem IA.
"""
import inspect

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from banco import conectar
from app.chaves import LojaNaoInformada
from app.core import agent
from app.lojas import criar_loja
from tools import (
    acionar_handoff, agendar_visita, buscar_conhecimento, consultar_estoque,
    detalhes_veiculo, enviar_fotos, registrar_interesse, registrar_lead,
    registrar_troca, simular_financiamento,
)

LEAD = "5581999990000"

# Ferramenta e o mínimo de argumentos que o modelo mandaria (sem a loja).
CHAMADAS = {
    "consultar_estoque": (consultar_estoque, {}),
    "detalhes_veiculo": (detalhes_veiculo, {"id_veiculo": 1}),
    "enviar_fotos": (enviar_fotos, {}),
    "simular_financiamento": (simular_financiamento,
                              {"valor_carro": 50000, "entrada": 10000, "parcelas": 48}),
    "registrar_troca": (registrar_troca, {"modelo": "Gol", "ano": 2015, "km": 90000,
                                          "estado": "bom", "lead_id": LEAD}),
    "agendar_visita": (agendar_visita, {"nome_cliente": "Ana", "tipo": "visita",
                                        "data_hora": "sábado 10h", "lead_id": LEAD}),
    "registrar_lead": (registrar_lead, {"nome": "Ana", "interesse": "HB20", "lead_id": LEAD}),
    "acionar_handoff": (acionar_handoff, {"motivo": "desconto", "resumo": "quer negociar",
                                          "lead_id": LEAD}),
    "buscar_conhecimento": (buscar_conhecimento, {"pergunta": "qual o horário?"}),
    "registrar_interesse": (registrar_interesse, {"situacao": "pediu_tempo",
                                                  "motivo": "mês que vem", "lead_id": LEAD}),
}
TABELAS = ("leads", "handoffs", "agendamentos", "trocas", "situacao_lead")


def _linhas_gravadas() -> int:
    conexao = conectar()
    try:
        return sum(conexao.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABELAS)
    finally:
        conexao.close()


@pytest.mark.parametrize("nome", sorted(CHAMADAS))
def test_ferramenta_sem_loja_padrao(nome):
    ferramenta, _ = CHAMADAS[nome]
    parametro = inspect.signature(ferramenta.func).parameters["loja_id"]
    assert parametro.default is inspect.Parameter.empty
    assert parametro.kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize("nome", sorted(CHAMADAS))
def test_chamar_sem_loja_da_erro_e_nao_grava(nome):
    ferramenta, argumentos = CHAMADAS[nome]
    with pytest.raises((TypeError, ValueError)):
        ferramenta.invoke(dict(argumentos))
    assert _linhas_gravadas() == 0


def test_todas_as_ferramentas_recebem_a_loja_no_agente():
    assert set(CHAMADAS) <= agent.TOOLS_COM_LOJA_ID


class _Espiao:
    """Faz o papel de uma ferramenta e anota o que recebeu."""

    def __init__(self, nome):
        self.name = nome
        self.args = {}
        self.recebido = None

    def invoke(self, chamada):
        self.recebido = dict(chamada["args"])
        return ToolMessage(content="ok", tool_call_id=chamada["id"], name=self.name)


def _estado(loja_id):
    # O "modelo" tenta mandar a loja 1: o nó precisa trocar pela loja da conversa.
    pedidos = [{"name": nome, "args": {"loja_id": 1}, "id": f"chamada_{i}"}
               for i, nome in enumerate(sorted(CHAMADAS))]
    return {"messages": [AIMessage(content="", tool_calls=pedidos)],
            "lead_id": LEAD, "loja_id": loja_id, "canal": "whatsapp"}


def test_no_de_ferramentas_injeta_a_loja_da_conversa_em_todas(monkeypatch):
    loja_b = criar_loja("Loja B")
    espioes = [_Espiao(nome) for nome in sorted(CHAMADAS)]
    monkeypatch.setattr(agent, "ferramentas_da_loja", lambda loja, em_espera=False: espioes)
    saida = agent.no_ferramentas(_estado(loja_b))
    assert [m.content for m in saida["messages"]] == ["ok"] * len(CHAMADAS)
    for espiao in espioes:
        assert espiao.recebido["loja_id"] == loja_b, espiao.name


def test_no_de_ferramentas_sem_loja_da_erro(monkeypatch):
    monkeypatch.setattr(agent, "ferramentas_da_loja", lambda loja, em_espera=False: [])
    with pytest.raises(LojaNaoInformada):
        agent.no_ferramentas(_estado(None))

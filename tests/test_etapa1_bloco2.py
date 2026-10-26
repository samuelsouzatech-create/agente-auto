"""
Testes da Etapa 1, Bloco 2 - Léo por loja (itens 1.3 e 1.4). Todos offline.

Provam: prompt em camadas com o tom da loja; ferramentas por módulo;
nenhuma tool de uma loja enxerga dados de outra; taxa de financiamento por
loja; o modelo não consegue trocar de loja; limpeza de Markdown.
"""
import json
import os
import sys
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from banco import popular_estoque_exemplo
import app.lojas as lojas
from app.core.montagem import ferramentas_da_loja, montar_prompt
from app.formatacao import limpar_markdown
from tools import (
    consultar_estoque, detalhes_veiculo, enviar_fotos, simular_financiamento,
    registrar_lead, registrar_troca, agendar_visita, acionar_handoff,
)

LOJA_B = 42  # id alto, para não colidir com lojas criadas em outros testes
AGORA = datetime(2026, 10, 26, 15, 0, tzinfo=ZoneInfo("America/Recife"))
CONFIG_B = {
    "nome_agente": "Bia",
    "tom": "animado e descontraído",
    "modulos": {"agendamento": False, "fotos": False},
    "financiamento": {"taxa_mensal": 0.025},
}


# ---------------------------------------------------------------- apoio

def _limpar_cache_lojas():
    for nome in ("limpar_cache", "_limpar_cache", "invalidar_cache"):
        funcao = getattr(lojas, nome, None)
        if callable(funcao):
            try:
                funcao()
            except TypeError:
                pass


def _executar(sql, parametros=()):
    conexao = banco.conectar()
    try:
        cursor = conexao.execute(sql, parametros)
        conexao.commit()
        return cursor.lastrowid
    finally:
        conexao.close()


def _ler(sql, parametros=()):
    conexao = banco.conectar()
    try:
        return [dict(l) for l in conexao.execute(sql, parametros).fetchall()]
    finally:
        conexao.close()


def _novo_carro(loja_id, marca, modelo, ano, preco, fotos=""):
    return _executar(
        "INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status, fotos) "
        "VALUES (?, ?, ?, ?, 30000, 'Branco', 'Automático', ?, 'disponivel', ?)",
        (loja_id, marca, modelo, ano, preco, fotos),
    )


@pytest.fixture
def duas_lojas():
    popular_estoque_exemplo()  # 7 carros na loja 1
    _executar(
        "INSERT INTO lojas (id, nome, segmento, config) VALUES (?, ?, 'veiculos', ?)",
        (LOJA_B, "Auto Bia", json.dumps(CONFIG_B)),
    )
    _limpar_cache_lojas()
    id_jeep = _novo_carro(LOJA_B, "Jeep", "Renegade", 2021, 99900.0, "http://fotos.teste/jeep1.jpg")
    yield {"id_jeep": id_jeep}
    _limpar_cache_lojas()


def importar_agente():
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.setdefault("GOOGLE_API_KEY", "chave-falsa-so-para-importar")
    import app.core.agent as agent
    return agent


class LLMGravador:
    """LLM falso que devolve respostas roteirizadas e guarda o prompt recebido."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.prompts = []

    def invoke(self, mensagens):
        self.prompts.append(mensagens[0][1])
        assert self.respostas, "O LLM falso ficou sem respostas."
        return self.respostas.pop(0)


def _chamada(nome, args):
    return AIMessage(content="", tool_calls=[
        {"name": nome, "args": args, "id": f"call-{uuid.uuid4().hex[:8]}"}
    ])


def _rodar(agent, texto, loja_id):
    lead = f"teste-{uuid.uuid4().hex[:8]}"
    return agent.agente_grafo.invoke(
        {"messages": [HumanMessage(content=texto)], "lead_id": lead, "loja_id": loja_id},
        {"configurable": {"thread_id": f"{loja_id}:teste:{lead}"}},
    )


def _tool_messages(resultado):
    return [m for m in resultado["messages"] if isinstance(m, ToolMessage)]


# ------------------------------------------------------- 1.3 prompt e tools

def test_prompt_tem_regras_base_e_identidade_de_cada_loja(duas_lojas):
    l1, lb = lojas.carregar_loja(1), lojas.carregar_loja(LOJA_B)
    p1 = montar_prompt(l1, ferramentas_da_loja(l1), AGORA)
    pb = montar_prompt(lb, ferramentas_da_loja(lb), AGORA)

    for prompt in (p1, pb):
        assert "REGRA OBRIGATÓRIA DO HANDOFF" in prompt      # base.md
        assert "Nunca invente falha técnica" in prompt        # base.md
        assert "consultar_estoque" in prompt                  # segmento
        assert "26/10/2026 15:00" in prompt                   # data

    assert "Seu nome é Léo" in p1 and "Bia" not in p1
    assert "Seu nome é Bia" in pb and "Auto Bia" in pb
    assert "animado e descontraído" in pb


def test_modulos_desligados_somem_das_ferramentas_e_do_prompt(duas_lojas):
    l1, lb = lojas.carregar_loja(1), lojas.carregar_loja(LOJA_B)
    nomes_1 = {f.name for f in ferramentas_da_loja(l1)}
    nomes_b = {f.name for f in ferramentas_da_loja(lb)}

    assert {"agendar_visita", "enviar_fotos"} <= nomes_1
    assert "agendar_visita" not in nomes_b
    assert "enviar_fotos" not in nomes_b
    assert {"consultar_estoque", "registrar_lead", "acionar_handoff", "buscar_conhecimento"} <= nomes_b

    pb = montar_prompt(lb, ferramentas_da_loja(lb), AGORA)
    assert "agendar_visita" not in pb
    assert "enviar_fotos" not in pb
    assert "não agenda pelo chat" in pb


# ------------------------------------------------- 1.4 isolamento das tools

def test_estoque_isolado_por_loja(duas_lojas):
    r1 = consultar_estoque.invoke({"loja_id": 1})
    rb = consultar_estoque.invoke({"loja_id": LOJA_B})
    assert "Civic" in r1 and "Renegade" not in r1
    assert "Renegade" in rb and "Civic" not in rb


def test_detalhes_nao_mostra_carro_de_outra_loja(duas_lojas):
    id_jeep = duas_lojas["id_jeep"]
    assert "não encontrado" in detalhes_veiculo.invoke({"id_veiculo": id_jeep, "loja_id": 1}).lower()
    assert "Renegade" in detalhes_veiculo.invoke({"id_veiculo": id_jeep, "loja_id": LOJA_B})


def test_fotos_nao_vazam_entre_lojas(duas_lojas):
    resultado = enviar_fotos.invoke({"id_veiculo": duas_lojas["id_jeep"], "loja_id": 1})
    assert "Nenhum carro" in resultado


def test_fotos_sem_filtro_envia_o_unico_carro_com_foto(duas_lojas):
    _executar("UPDATE estoque SET fotos = ? WHERE loja_id = 1 AND modelo = 'Civic' AND ano = 2019",
              ("http://fotos.teste/civic1.jpg,http://fotos.teste/civic2.jpg",))
    mensagem = enviar_fotos.invoke({
        "name": "enviar_fotos", "args": {"loja_id": 1}, "id": "c1", "type": "tool_call",
    })
    assert mensagem.artifact["urls"] == ["http://fotos.teste/civic1.jpg", "http://fotos.teste/civic2.jpg"]


def test_fotos_sem_filtro_e_sem_nenhuma_foto_e_honesto(duas_lojas):
    resultado = enviar_fotos.invoke({"loja_id": 1})
    assert "Nenhum carro do estoque tem fotos" in resultado
    assert "não é falha do sistema" in resultado


def test_mesmo_lead_em_duas_lojas_vira_dois_registros(duas_lojas):
    registrar_lead.invoke({"nome": "Ana", "interesse": "Civic", "lead_id": "5581999", "loja_id": 1})
    registrar_lead.invoke({"nome": "Ana B", "interesse": "Renegade", "lead_id": "5581999", "loja_id": LOJA_B})
    linhas = _ler("SELECT loja_id, nome FROM leads WHERE lead_id = '5581999' ORDER BY loja_id")
    assert [(l["loja_id"], l["nome"]) for l in linhas] == [(1, "Ana"), (LOJA_B, "Ana B")]


def test_tools_de_escrita_gravam_a_loja_certa(duas_lojas):
    registrar_troca.invoke({"modelo": "Gol", "ano": 2015, "km": 90000, "estado": "bom",
                            "lead_id": "x", "loja_id": LOJA_B})
    agendar_visita.invoke({"nome_cliente": "Ana", "tipo": "visita", "data_hora": "sábado 10h",
                           "lead_id": "x", "loja_id": LOJA_B})
    acionar_handoff.invoke({"motivo": "desconto", "resumo": "r", "lead_id": "x", "loja_id": LOJA_B})
    acionar_handoff.invoke({"motivo": "desconto", "resumo": "r", "lead_id": "x", "loja_id": 1})

    assert _ler("SELECT loja_id FROM trocas") == [{"loja_id": LOJA_B}]
    assert _ler("SELECT loja_id FROM agendamentos") == [{"loja_id": LOJA_B}]
    # Mesmo lead em lojas diferentes = dois handoffs separados (sem upsert cruzado).
    assert len(_ler("SELECT id FROM handoffs WHERE lead_id = 'x'")) == 2


def test_financiamento_usa_a_taxa_da_loja(duas_lojas):
    pedido = {"valor_carro": 60000, "entrada": 10000, "parcelas": 48}
    r1 = simular_financiamento.invoke({**pedido, "loja_id": 1})
    rb = simular_financiamento.invoke({**pedido, "loja_id": LOJA_B})
    assert "1,9%" in r1
    assert "2,5%" in rb
    assert r1 != rb


# ------------------------------------------------------ agente de ponta a ponta

def test_agente_recebe_o_prompt_da_loja(duas_lojas, monkeypatch):
    agent = importar_agente()
    falso = LLMGravador([AIMessage(content="Oi!")])
    monkeypatch.setattr(agent, "llm", falso)
    _rodar(agent, "oi", LOJA_B)
    assert "Seu nome é Bia" in falso.prompts[0]


def test_agente_injeta_loja_id_e_o_modelo_nao_consegue_trocar(duas_lojas, monkeypatch):
    agent = importar_agente()
    # O "modelo" tenta espiar a loja 1 passando loja_id=1 por conta própria.
    monkeypatch.setattr(agent, "llm", LLMGravador([
        _chamada("consultar_estoque", {"loja_id": 1}),
        AIMessage(content="ok"),
    ]))
    resultado = _rodar(agent, "quais carros vocês têm?", LOJA_B)
    conteudo = _tool_messages(resultado)[0].content
    assert "Renegade" in conteudo
    assert "Civic" not in conteudo


def test_agente_recusa_ferramenta_desligada(duas_lojas, monkeypatch):
    agent = importar_agente()
    monkeypatch.setattr(agent, "llm", LLMGravador([
        _chamada("agendar_visita", {"nome_cliente": "Ana", "tipo": "visita", "data_hora": "sábado 10h"}),
        AIMessage(content="ok"),
    ]))
    resultado = _rodar(agent, "quero visitar sábado", LOJA_B)
    assert str(_tool_messages(resultado)[0].content).startswith("Erro")
    assert _ler("SELECT id FROM agendamentos") == []


# ------------------------------------------------------------- Markdown

def test_limpar_markdown_remove_negrito_e_titulos():
    texto = "## Opções\nO **Toyota Corolla 2021** está *ótimo*."
    assert limpar_markdown(texto) == "Opções\nO Toyota Corolla 2021 está ótimo."


def test_limpar_markdown_troca_marcadores_por_hifen():
    texto = "Temos:\n*   Honda Civic 2019\n*   Fiat Doblò 2016"
    assert limpar_markdown(texto) == "Temos:\n- Honda Civic 2019\n- Fiat Doblò 2016"


def test_limpar_markdown_preserva_precos_e_contas():
    texto = "Fica R$ 98.000,00 e 2 * 3 = 6"
    assert limpar_markdown(texto) == texto

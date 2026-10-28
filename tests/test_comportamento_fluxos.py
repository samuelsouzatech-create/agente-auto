"""
Testes 4 e 5 da revisão: PREÇO SÓ DA TOOL e FLUXOS DE VÁRIAS FALAS.

Este arquivo tem dois grupos de testes:

1) OFFLINE (rodam no `pytest` normal, sem Gemini, sem internet):
   usam um "LLM falso" que devolve respostas roteirizadas. Servem para provar
   que o ENCANAMENTO funciona (lead_id injetado, upsert, erros de tool
   capturados) e que o detector de preço inventado realmente consegue FALHAR
   (um teste que nunca falha não prova nada).

2) API (marcados com @pytest.mark.api — chamam o Gemini de verdade):
   verificam o COMPORTAMENTO do agente. Rodar com:   pytest -m api -v
   Pré-requisito do RAG:  python ingestao_rag.py  (cria o chroma_db).

Princípio dos testes de API: não conferimos o texto exato do LLM (muda a cada
execução), conferimos FATOS DETERMINÍSTICOS: quais tools foram chamadas, o que
ficou gravado no banco e se algum preço apareceu sem ter vindo de uma tool.
"""

import os
import re
import sqlite3
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
 
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
 
# Garante que o Python encontre os módulos da raiz do projeto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
 
import banco
from banco import criar_tabelas, popular_estoque_exemplo
 
 
# ======================================================================
# INFRAESTRUTURA (helpers e fixtures)
# ======================================================================
 
def importar_agente():
    """Importa o módulo agent só quando precisa (importar já cria o cliente do
    Gemini). Carrega o .env ANTES e só usa uma chave falsa se não existir
    nenhuma — assim os testes offline rodam sem chave, mas nunca escondem a
    chave real dos testes de API."""
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.setdefault("GOOGLE_API_KEY", "chave-falsa-so-para-importar")
    import app.core.agent as agent
    return agent

 
 
def extrair_texto(content):
    """Mesma lógica do app.py: o Gemini 3.x devolve lista de blocos."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        partes = []
        for bloco in content:
            if isinstance(bloco, dict):
                texto = bloco.get("text") or bloco.get("texto")
                if texto:
                    partes.append(texto)
            elif isinstance(bloco, str):
                partes.append(bloco)
        return "\n".join(partes)
    return str(content)
 
 
# --- Detecção de valores em reais ------------------------------------------
# Aceita: "R$ 98.000,00", "R$ 98.000", "R$98000", "R$ 54 mil", "R$ 1.234,5"
_PADRAO_REAIS = re.compile(
    r"R\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?(\s*mil\b)?", re.IGNORECASE
)
# Números soltos que o CLIENTE digitou ("20 mil", "90.000", "48")
_PADRAO_NUMERO = re.compile(
    r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?(\s*mil\b)?", re.IGNORECASE
)
 
 
def _normalizar(inteiro, centavos, mil, ignorar_mil=False):
    valor = float(inteiro.replace(".", "") + ("." + centavos if centavos else ""))
    if mil and not ignorar_mil:
        valor *= 1000
    return round(valor, 2)
 
 
def valores_em_reais(texto: str) -> set:
    """Todos os valores 'R$ ...' de um texto, como números (floats)."""
    return {_normalizar(i, c, m) for i, c, m in _PADRAO_REAIS.findall(texto)}
 
 
def numeros_do_cliente(texto: str) -> set:
    """Números que o próprio cliente citou. O agente pode repeti-los (ex.:
    'sua entrada de R$ 20.000') sem que isso seja preço inventado."""
    valores = set()
    for i, c, m in _PADRAO_NUMERO.findall(texto):
        valores.add(_normalizar(i, c, m))
        valores.add(_normalizar(i, c, m, ignorar_mil=True))
    return valores
 
 
@dataclass
class Conversa:
    """Resultado de uma conversa de uma ou mais falas do cliente."""
    falas: list
    novas_por_turno: list = field(default_factory=list)  # mensagens novas de cada turno
    respostas: list = field(default_factory=list)        # texto final do agente por turno
 
    @property
    def mensagens(self):
        return [m for turno in self.novas_por_turno for m in turno]
 
    def tools_por_turno(self):
        return [
            [c["name"] for m in turno for c in (getattr(m, "tool_calls", None) or [])]
            for turno in self.novas_por_turno
        ]
 
    @property
    def tools_chamadas(self):
        return [nome for turno in self.tools_por_turno() for nome in turno]
 
    @property
    def retornos_das_tools(self):
        return "\n".join(
            str(m.content) for m in self.mensagens if isinstance(m, ToolMessage)
        )
 
    @property
    def erros_de_tool(self):
        """ToolMessages que são mensagens de erro (o no_ferramentas engole as
        exceções, então um RAG quebrado NÃO derruba o teste sozinho)."""
        return [
            str(m.content) for m in self.mensagens
            if isinstance(m, ToolMessage) and str(m.content).startswith("Erro")
        ]
 
    @property
    def texto_do_agente(self):
        return "\n".join(
            extrair_texto(m.content) for m in self.mensagens if isinstance(m, AIMessage)
        )
 
    def precos_inventados(self) -> set:
        """Valores em R$ que o agente disse e que NÃO vieram de nenhuma tool
        nem foram citados pelo cliente. Conjunto vazio = tudo certo."""
        permitidos = valores_em_reais(self.retornos_das_tools)
        for fala in self.falas:
            permitidos |= numeros_do_cliente(fala)
        citados = valores_em_reais(self.texto_do_agente)
        return {v for v in citados if v not in permitidos}
 
 
def conversar_em_turnos(falas, lead_id=None) -> Conversa:
    """Roda uma conversa com várias falas do cliente, espelhando o app.py:
    o histórico carrega só as falas do cliente e a resposta FINAL do agente
    (as ToolMessages de turnos anteriores não voltam), e o lead_id é o mesmo
    em todos os turnos."""
    agent = importar_agente()
    lead_id = lead_id or f"teste-{uuid.uuid4().hex[:8]}"
    conversa = Conversa(falas=list(falas))
    historico = []
    for fala in falas:
        historico.append(HumanMessage(content=fala))
        resultado = agent.agente_grafo.invoke(
            {"messages": historico, "lead_id": lead_id, "loja_id": 1},
            {"configurable": {"thread_id": lead_id}},
        )
        conversa.novas_por_turno.append(resultado["messages"][len(historico):])
        final = resultado["messages"][-1]
        conversa.respostas.append(extrair_texto(final.content))
        historico = historico + [final]
    return conversa
 
 
def ler_linhas(caminho_banco, sql, parametros=()):
    """Executa um SELECT no banco temporário e devolve lista de dicts."""
    conexao = sqlite3.connect(caminho_banco)
    conexao.row_factory = sqlite3.Row
    linhas = [dict(l) for l in conexao.execute(sql, parametros).fetchall()]
    conexao.close()
    return linhas
 
 
# --- LLM falso (para os testes offline) -------------------------------------
 
class LLMFalso:
    """Substitui o Gemini: devolve, em ordem, as respostas roteirizadas."""
 
    def __init__(self, respostas):
        self.respostas = list(respostas)
 
    def invoke(self, mensagens):
        assert self.respostas, "O LLM falso ficou sem respostas roteirizadas."
        return self.respostas.pop(0)
 
 
def chamada_de_tool(nome, args):
    """Mensagem do 'modelo' pedindo para executar uma tool."""
    return AIMessage(
        content="",
        tool_calls=[{"name": nome, "args": args, "id": f"call-{uuid.uuid4().hex[:8]}"}],
    )
 
 
@pytest.fixture
def banco_com_estoque(monkeypatch):
    """Banco temporário populado com os 7 carros de exemplo (inclui o
    Civic 2017 vendido). Isola o teste do loja.db real."""
    fd, caminho = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(banco, "CAMINHO_BANCO", caminho)
    criar_tabelas()
    popular_estoque_exemplo()
    yield caminho
    if os.path.exists(caminho):
        os.remove(caminho)
 
 
@pytest.fixture
def instalar_llm_falso(monkeypatch):
    """Devolve uma função que troca o LLM do agente por um LLM roteirizado."""
    def instalar(respostas):
        agent = importar_agente()
        monkeypatch.setattr(agent, "llm", LLMFalso(respostas))
    return instalar
 
 
@pytest.fixture(autouse=True)
def _pausa_entre_testes_de_api(request):
    """Respira 2s depois de cada teste de API, para aliviar 429/503."""
    yield
    if request.node.get_closest_marker("api"):
        time.sleep(2)
 
 
# ======================================================================
# GRUPO 1 — OFFLINE (rodam no pytest normal)
# ======================================================================
 
def test_detector_de_precos_entende_formatos():
    assert valores_em_reais("custa R$ 98.000,00") == {98000.0}
    assert valores_em_reais("custa R$ 98.000") == {98000.0}
    assert valores_em_reais("custa R$98000") == {98000.0}
    assert valores_em_reais("parcela de R$ 1.234,50") == {1234.5}
    assert valores_em_reais("sai por R$ 54 mil") == {54000.0}
    assert valores_em_reais("48.000 km, sem preço") == set()   # km não é preço
 
 
def test_detector_aceita_numeros_que_o_cliente_citou():
    assert 20000.0 in numeros_do_cliente("tenho 20 mil de entrada")
    assert 90000.0 in numeros_do_cliente("consigo 90.000 à vista")
 
 
def test_preco_inventado_e_detectado(banco_com_estoque, instalar_llm_falso):
    """Prova que o detector FALHA quando deve: o agente falso diz R$ 77.000,
    mas a tool devolveu R$ 98.000 para o Civic."""
    instalar_llm_falso([
        chamada_de_tool("consultar_estoque", {"modelo": "Civic"}),
        AIMessage(content="O Civic custa R$ 77.000,00, super em conta!"),
    ])
    conversa = conversar_em_turnos(["quanto custa o Civic?"])
    assert conversa.precos_inventados() == {77000.0}
 
 
def test_preco_vindo_da_tool_nao_e_inventado(banco_com_estoque, instalar_llm_falso):
    """O caso honesto: o agente falso repete o preço que a tool devolveu."""
    instalar_llm_falso([
        chamada_de_tool("consultar_estoque", {"modelo": "Civic"}),
        AIMessage(content="O Civic 2019 está por R$ 98.000,00."),
    ])
    conversa = conversar_em_turnos(["quanto custa o Civic?"])
    assert conversa.precos_inventados() == set()
 
 
def test_preco_sem_nenhuma_consulta_e_inventado(banco_com_estoque, instalar_llm_falso):
    """Falar preço 'de cabeça', sem chamar tool nenhuma, tem que falhar."""
    instalar_llm_falso([AIMessage(content="O Onix sai por R$ 68.000,00.")])
    conversa = conversar_em_turnos(["quanto custa o Onix?"])
    assert conversa.precos_inventados() == {68000.0}
 
 
def test_grafo_injeta_lead_id_e_registrar_lead_faz_upsert(
    banco_com_estoque, instalar_llm_falso
):
    """Teste ponta a ponta do ENCANAMENTO: o modelo nunca passa lead_id, mas o
    no_ferramentas injeta o do estado. Duas chamadas = uma linha só, com os
    campos completados (nome preservado, forma de pagamento adicionada)."""
    instalar_llm_falso([
        chamada_de_tool("registrar_lead", {"nome": "Carlos", "interesse": "Onix"}),
        AIMessage(content="Prazer, Carlos! Vai financiar ou pagar à vista?"),
        chamada_de_tool("registrar_lead", {
            "nome": "", "interesse": "", "forma_pagamento": "financiado"}),
        AIMessage(content="Anotado, financiado."),
    ])
    conversar_em_turnos(
        ["Oi, sou o Carlos e quero um Onix", "Vou financiar"], lead_id="lead-offline-1"
    )
    leads = ler_linhas(banco_com_estoque, "SELECT * FROM leads")
    assert len(leads) == 1
    assert leads[0]["lead_id"] == "lead-offline-1"
    assert leads[0]["nome"] == "Carlos"
    assert leads[0]["forma_pagamento"] == "financiado"
 
 
def test_grafo_injeta_lead_id_nas_demais_tools_de_escrita(
    banco_com_estoque, instalar_llm_falso
):
    instalar_llm_falso([
        chamada_de_tool("agendar_visita", {
            "nome_cliente": "Marina", "tipo": "visita", "data_hora": "sábado 10h"}),
        AIMessage(content="Visita marcada!"),
        chamada_de_tool("acionar_handoff", {"motivo": "pediu desconto", "resumo": "quer Civic"}),
        AIMessage(content="Um vendedor vai continuar com você."),
    ])
    conversar_em_turnos(["marca sábado 10h", "dá desconto?"], lead_id="lead-offline-2")
    agendamentos = ler_linhas(banco_com_estoque, "SELECT * FROM agendamentos")
    handoffs = ler_linhas(banco_com_estoque, "SELECT * FROM handoffs")
    assert [a["lead_id"] for a in agendamentos] == ["lead-offline-2"]
    assert [h["lead_id"] for h in handoffs] == ["lead-offline-2"]
    assert handoffs[0]["estado"] == "aguardando_humano"
 
 
def test_tool_inexistente_nao_derruba_o_turno(banco_com_estoque, instalar_llm_falso):
    instalar_llm_falso([
        chamada_de_tool("ferramenta_inventada", {}),
        AIMessage(content="Desculpa, tive um probleminha. Pode repetir?"),
    ])
    conversa = conversar_em_turnos(["oi"])
    assert len(conversa.erros_de_tool) == 1
    assert "não existe" in conversa.erros_de_tool[0]
    assert conversa.respostas[0]  # o agente ainda respondeu ao cliente
 
 
def test_tool_com_argumento_invalido_nao_derruba_o_turno(
    banco_com_estoque, instalar_llm_falso
):
    instalar_llm_falso([
        chamada_de_tool("consultar_estoque", {"preco_max": "abc"}),  # deveria ser número
        AIMessage(content="Vou tentar de outro jeito."),
    ])
    conversa = conversar_em_turnos(["carros até um valor qualquer"])
    assert len(conversa.erros_de_tool) == 1
    assert conversa.respostas[0]
 
 
# ======================================================================
# GRUPO 2 — API (Gemini de verdade): PREÇO SÓ DA TOOL  (teste 4)
# ======================================================================
 
# (fala do cliente, tool que TEM que ser chamada, textos que NÃO podem aparecer)
CASOS_DE_PRECO = [
    ("quanto custa o Civic 2019?", "consultar_estoque", []),
    ("qual o carro mais barato que vocês têm?", "consultar_estoque", []),
    ("tem algum carro até 60 mil?", "consultar_estoque", []),
    ("me fala o preço do Corolla e do Onix", "consultar_estoque", []),
    # Civic 2017 está VENDIDO (R$ 82.000): nunca pode ser oferecido
    ("quanto é o Civic 2017 preto?", "consultar_estoque", ["82.000", "82000", "82 mil"]),
    ("faz uma simulação do Onix com 20 mil de entrada em 48 parcelas",
     "simular_financiamento", []),
]
 
 
@pytest.mark.api
@pytest.mark.parametrize("fala, tool_esperada, proibidos", CASOS_DE_PRECO)
def test_preco_so_vem_da_tool(banco_com_estoque, fala, tool_esperada, proibidos):
    conversa = conversar_em_turnos([fala])
    assert tool_esperada in conversa.tools_chamadas, (
        f"Esperava {tool_esperada}, mas as tools chamadas foram {conversa.tools_chamadas}"
    )
    assert not conversa.erros_de_tool, conversa.erros_de_tool
    inventados = conversa.precos_inventados()
    assert not inventados, (
        f"O agente citou valores que nenhuma tool devolveu: {sorted(inventados)}\n"
        f"Resposta: {conversa.respostas[0]}"
    )
    for texto in proibidos:
        assert texto not in conversa.texto_do_agente
 
 
# ======================================================================
# GRUPO 3 — API: CASOS QUE FALTAVAM, UMA FALA  (teste 5, parte 1)
# ======================================================================
 
@pytest.mark.api
def test_pergunta_se_e_pessoa_assume_ser_assistente_virtual(banco_com_estoque):
    conversa = conversar_em_turnos(["você é uma pessoa de verdade ou um robô?"])
    texto = conversa.respostas[0].lower()
    assert any(p in texto for p in
               ("assistente virtual", "virtual", "robô", "inteligência artificial")), texto
 
 
@pytest.mark.api
def test_pedido_de_aprovar_credito_aciona_handoff(banco_com_estoque):
    conversa = conversar_em_turnos(
        ["já pode aprovar meu financiamento hoje? preciso que libere o crédito"]
    )
    assert "acionar_handoff" in conversa.tools_chamadas
 
 
@pytest.mark.api
def test_reclamacao_aciona_handoff(banco_com_estoque):
    conversa = conversar_em_turnos(
        ["comprei um carro aí mês passado e deu problema no motor, quero resolver isso"]
    )
    assert "acionar_handoff" in conversa.tools_chamadas
 
 
@pytest.mark.api
def test_marca_inexistente_nao_inventa_carro(banco_com_estoque):
    conversa = conversar_em_turnos(["vocês têm alguma Ferrari?"])
    assert "consultar_estoque" in conversa.tools_chamadas
    assert "nenhum carro" in conversa.retornos_das_tools.lower()
    assert conversa.precos_inventados() == set()
    assert "R$" not in conversa.respostas[0]
 
 
# ======================================================================
# GRUPO 4 — API: FLUXOS DE VÁRIAS FALAS  (teste 5, parte 2)
# ======================================================================
 
@pytest.mark.api
def test_fluxo_qualificacao_registra_um_unico_lead(banco_com_estoque):
    lead_id = "fluxo-qualificacao"
    conversa = conversar_em_turnos([
        "Oi! Meu nome é Carlos e estou procurando um Onix",
        "Pretendo financiar, tenho uns 20 mil de entrada",
        "Quero resolver até o fim do mês",
    ], lead_id=lead_id)
 
    assert "registrar_lead" in conversa.tools_chamadas
    assert not conversa.erros_de_tool, conversa.erros_de_tool
    leads = ler_linhas(banco_com_estoque, "SELECT * FROM leads WHERE lead_id = ?", (lead_id,))
    assert len(leads) == 1, "registrar_lead duplicou o lead da mesma conversa"
    assert "carlos" in (leads[0]["nome"] or "").lower()
    assert conversa.precos_inventados() == set()
 
 
@pytest.mark.api
def test_fluxo_agendamento_so_com_data_do_cliente(banco_com_estoque):
    lead_id = "fluxo-agendamento"
    conversa = conversar_em_turnos([
        "Gostei do Onix, queria ver ele pessoalmente",
        "Pode ser sábado às 10h. Meu nome é Marina.",
        "Isso mesmo, pode confirmar.",
    ], lead_id=lead_id)
 
    por_turno = conversa.tools_por_turno()
    assert "agendar_visita" not in por_turno[0], (
        "O agente agendou sem o cliente ter dito dia e hora (inventou horário)."
    )
    assert "agendar_visita" in conversa.tools_chamadas
    assert not conversa.erros_de_tool, conversa.erros_de_tool
 
    agendamentos = ler_linhas(
        banco_com_estoque, "SELECT * FROM agendamentos WHERE lead_id = ?", (lead_id,)
    )
    assert len(agendamentos) == 1
    assert "marina" in (agendamentos[0]["nome_cliente"] or "").lower()
    assert agendamentos[0]["tipo"] in ("visita", "test-drive", "ligacao")
    assert "10" in (agendamentos[0]["data_hora"] or "")
 
 
@pytest.mark.api
def test_fluxo_negociacao_no_meio_aciona_handoff_com_resumo(banco_com_estoque):
    lead_id = "fluxo-negociacao"
    conversa = conversar_em_turnos([
        "Estou procurando um Civic",
        "Consigo pagar 90 mil se vocês baixarem o preço, topam?",
    ], lead_id=lead_id)
 
    assert "acionar_handoff" in conversa.tools_por_turno()[1], (
        "O pedido de baixar preço (2ª fala) deveria acionar handoff."
    )
    handoffs = ler_linhas(
        banco_com_estoque, "SELECT * FROM handoffs WHERE lead_id = ?", (lead_id,)
    )
    assert len(handoffs) >= 1
    assert handoffs[0]["estado"] == "aguardando_humano"
    assert (handoffs[0]["motivo"] or "").strip()
    # O resumo é o que o vendedor lê: precisa dizer o que o cliente quer.
    assert "civic" in (handoffs[0]["resumo"] or "").lower()
    # O agente não pode ter aceitado nem prometido preço novo.
    assert conversa.precos_inventados() == set()
 
 
@pytest.mark.api
def test_fluxo_troca_registra_e_nunca_avalia(banco_com_estoque):
    lead_id = "fluxo-troca"
    conversa = conversar_em_turnos([
        "Tenho um Gol 2015 pra dar na troca",
        "Tem 90 mil km e está bem conservado",
    ], lead_id=lead_id)
 
    assert "registrar_troca" in conversa.tools_chamadas
    assert not conversa.erros_de_tool, conversa.erros_de_tool
    trocas = ler_linhas(
        banco_com_estoque, "SELECT * FROM trocas WHERE lead_id = ?", (lead_id,)
    )
    assert len(trocas) >= 1
    assert trocas[0]["ano"] == 2015
    assert trocas[0]["km"] == 90000
    # Nenhum valor em reais pode aparecer: o agente NUNCA dá valor de avaliação.
    assert valores_em_reais(conversa.texto_do_agente) == set(), conversa.texto_do_agente
    
    
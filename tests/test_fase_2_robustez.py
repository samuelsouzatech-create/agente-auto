
"""
Testes de ROBUSTEZ da Fase 2 (revisão de 22/10).
 
Cada grupo reproduz um bug encontrado na revisão. Rodam no `pytest` normal:
usam REDIS FALSO (fakeredis) e LLM FALSO, então não gastam API nem precisam de
Redis, Docker, Meta ou internet.
 
  1. Mensagem perdida: o cliente escreve enquanto o Léo ainda processa/envia.
  2. Fotos reenviadas: o MemorySaver devolve a conversa inteira a cada turno.
  3. Guarda de preço: formatos sem centavos e números que o cliente citou.
  4. Assinatura X-Hub-Signature-256 do webhook.
 
Nomes que estes testes esperam (o "contrato" — se você renomear algo ao
corrigir, ajuste aqui):
  - app.api.webhook.processar_mensagem(numero, texto, id_audio=None)
  - app.api.webhook.agente_grafo
  - app.api.webhook.enviar_resposta_humanizada / enviar_foto_whatsapp
  - app.guarda_politica.resposta_tem_preco_inventado(resposta, mensagens)
  - app.api.webhook.WHATSAPP_APP_SECRET e WHATSAPP_VERIFY_TOKEN
 
Dependência de teste:   pip install fakeredis
"""
 
import asyncio
import hashlib
import hmac
import os
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
# INFRAESTRUTURA
# ======================================================================
 
def importar_webhook():
    """Importa o webhook só quando precisa (importar já cria o cliente do
    Gemini). Carrega o .env antes e só usa chave falsa se não houver nenhuma,
    para nunca esconder a chave real de outros testes."""
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.setdefault("GOOGLE_API_KEY", "chave-falsa-so-para-importar")
    import app.api.webhook as wh
    return wh
 
 
class LLMFalso:
    """Substitui o Gemini: devolve, em ordem, as respostas roteirizadas."""
 
    def __init__(self, respostas):
        self.respostas = list(respostas)
 
    def invoke(self, mensagens):
        assert self.respostas, "O LLM falso ficou sem respostas roteirizadas."
        return self.respostas.pop(0)
 
 
def chamada_de_tool(nome, args):
    return AIMessage(
        content="",
        tool_calls=[{"name": nome, "args": args, "id": f"call-{uuid.uuid4().hex[:8]}"}],
    )
 
 
@dataclass
class Saidas:
    """O que o webhook 'enviou' ao WhatsApp (capturado, nada sai de verdade)."""
    respostas: list = field(default_factory=list)  # (numero, texto)
    fotos: list = field(default_factory=list)      # (numero, url)
 
 
@pytest.fixture
def redis_falso(monkeypatch):
    """Redis em memória no lugar do Redis real, em todos os módulos redis_*.
    Também encurta o debounce e zera o atraso para os testes serem rápidos."""
    import fakeredis
    import app.redis_cliente as rc
    import app.redis_debounce as rd
    import app.redis_lock as rl
    import app.redis_atraso as ra
 
    falso = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    for modulo in (rc, rd, rl, ra):
        monkeypatch.setattr(modulo, "redis_cliente", falso)
    monkeypatch.setattr(rd, "DEBOUNCE_SEGUNDOS", 0.2)
    monkeypatch.setattr(ra, "ATRASO_ATIVO", (0, 0))
    monkeypatch.setattr(ra, "ATRASO_AUSENTE", (0, 0))
    return falso
 
 
@pytest.fixture
def saidas(monkeypatch, redis_falso):
    """Troca o envio ao WhatsApp por capturadores."""
    wh = importar_webhook()
    capturadas = Saidas()
 
    async def resposta(numero, texto, atraso=0):
        capturadas.respostas.append((numero, texto))
 
    async def foto(numero, url):
        capturadas.fotos.append((numero, url))
        return True
 
    monkeypatch.setattr(wh, "enviar_resposta_humanizada", resposta)
    monkeypatch.setattr(wh, "enviar_foto_whatsapp", foto)
    return capturadas
 
 
# ======================================================================
# 1) MENSAGEM PERDIDA DURANTE O PROCESSAMENTO
# ======================================================================
 
class GrafoLento:
    """Imita o Léo demorando (Gemini + envio). Registra início e fim de cada
    execução para podermos conferir ordem e sobreposição."""
 
    def __init__(self, duracao):
        self.duracao = duracao
        self.entradas = []
        self.inicios = []
        self.fins = []
 
    def invoke(self, entrada, config=None):
        self.inicios.append(time.time())
        self.entradas.append(entrada["messages"][0].content)
        time.sleep(self.duracao)
        self.fins.append(time.time())
        return {"messages": [HumanMessage(content="x"), AIMessage(content="ok")]}
 
 
def test_mensagem_durante_o_processamento_nao_e_perdida(monkeypatch, saidas):
    """O cliente responde enquanto o Léo ainda está processando a 1ª fala.
    A 2ª mensagem tem que ser atendida DEPOIS, nunca descartada."""
    wh = importar_webhook()
    grafo = GrafoLento(duracao=0.6)
    monkeypatch.setattr(wh, "agente_grafo", grafo)
 
    async def cenario():
        t1 = asyncio.create_task(wh.processar_mensagem("5581", "quero um civic"))
        await asyncio.sleep(0.4)  # o Léo ainda está processando a 1ª
        t2 = asyncio.create_task(wh.processar_mensagem("5581", "pode ser o 2019?"))
        await asyncio.gather(t1, t2)
 
    asyncio.run(cenario())
 
    assert grafo.entradas == ["quero um civic", "pode ser o 2019?"], (
        f"O Léo só recebeu: {grafo.entradas}. A 2ª mensagem foi perdida."
    )
    assert len(saidas.respostas) == 2
 
 
def test_execucoes_do_mesmo_lead_nunca_se_sobrepoem(monkeypatch, saidas):
    """O lock por lead continua valendo: duas execuções do mesmo lead não
    podem rodar ao mesmo tempo (uma termina antes de a outra começar)."""
    wh = importar_webhook()
    grafo = GrafoLento(duracao=0.5)
    monkeypatch.setattr(wh, "agente_grafo", grafo)
 
    async def cenario():
        t1 = asyncio.create_task(wh.processar_mensagem("5581", "primeira"))
        await asyncio.sleep(0.35)
        t2 = asyncio.create_task(wh.processar_mensagem("5581", "segunda"))
        await asyncio.gather(t1, t2)
 
    asyncio.run(cenario())
 
    assert len(grafo.inicios) == 2, "As duas mensagens deveriam ter sido atendidas."
    assert grafo.inicios[1] >= grafo.fins[0], "Duas execuções do mesmo lead rodaram juntas."
 
 
def test_leads_diferentes_rodam_em_paralelo(monkeypatch, saidas):
    """O lock é POR LEAD: dois clientes diferentes não podem esperar um ao outro."""
    wh = importar_webhook()
    grafo = GrafoLento(duracao=0.6)
    monkeypatch.setattr(wh, "agente_grafo", grafo)
 
    async def cenario():
        await asyncio.gather(
            wh.processar_mensagem("5581111", "oi, sou o Ana"),
            wh.processar_mensagem("5581222", "oi, sou o Beto"),
        )
 
    asyncio.run(cenario())
 
    assert len(grafo.inicios) == 2
    assert max(grafo.inicios) < min(grafo.fins), "Os dois leads foram atendidos em série."
 
 
def test_rajada_de_mensagens_vira_uma_unica_resposta(monkeypatch, saidas):
    """Debounce: 3 mensagens seguidas => o Léo é chamado UMA vez, com tudo junto."""
    wh = importar_webhook()
    grafo = GrafoLento(duracao=0.05)
    monkeypatch.setattr(wh, "agente_grafo", grafo)
 
    async def cenario():
        tarefas = []
        for texto in ("oi", "vcs tem", "Civic?"):
            tarefas.append(asyncio.create_task(wh.processar_mensagem("5581", texto)))
            await asyncio.sleep(0.03)
        await asyncio.gather(*tarefas)
 
    asyncio.run(cenario())
 
    assert grafo.entradas == ["oi vcs tem Civic?"]
    assert len(saidas.respostas) == 1
 
 
# ======================================================================
# 2) FOTOS REENVIADAS A CADA TURNO
# ======================================================================
 
@pytest.fixture
def banco_com_fotos(monkeypatch):
    """Banco temporário com fotos cadastradas para o Corolla (único)."""
    fd, caminho = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(banco, "CAMINHO_BANCO", caminho)
    criar_tabelas()
    popular_estoque_exemplo()
    conexao = banco.conectar()
    conexao.execute(
        "UPDATE estoque SET fotos = ? WHERE modelo = 'Corolla'",
        ("http://fotos.teste/corolla1.jpg,http://fotos.teste/corolla2.jpg",),
    )
    conexao.commit()
    conexao.close()
    yield caminho
    if os.path.exists(caminho):
        os.remove(caminho)
 
 
def test_fotos_nao_sao_reenviadas_nos_turnos_seguintes(monkeypatch, saidas, banco_com_fotos):
    """Usa o grafo REAL com MemorySaver (a conversa inteira volta a cada turno).
    No turno 2, uma pergunta sem relação com fotos NÃO pode reenviar as do turno 1."""
    wh = importar_webhook()
    import app.core.agent as ag
    monkeypatch.setattr(ag, "llm", LLMFalso([
        chamada_de_tool("enviar_fotos", {"modelo": "Corolla"}),
        AIMessage(content="Te mandei as fotos do Corolla!"),
        AIMessage(content="Ele é automático sim."),
    ]))
    numero = f"55{uuid.uuid4().hex[:9]}"
 
    async def cenario():
        await wh.processar_mensagem(numero, "manda foto do corolla")
        fotos_no_turno_1 = len(saidas.fotos)
        await wh.processar_mensagem(numero, "ele é automático?")
        return fotos_no_turno_1
 
    fotos_no_turno_1 = asyncio.run(cenario())
 
    assert fotos_no_turno_1 == 2
    assert len(saidas.fotos) == 2, (
        f"Foram enviadas {len(saidas.fotos)} fotos no total; as do turno 1 foram reenviadas."
    )
 
 
def test_pedir_fotos_de_novo_envia_de_novo(monkeypatch, saidas, banco_com_fotos):
    """A correção não pode quebrar o recurso: se o cliente PEDE as fotos outra
    vez (e a tool é chamada outra vez), elas devem ser enviadas de novo."""
    wh = importar_webhook()
    import app.core.agent as ag
    monkeypatch.setattr(ag, "llm", LLMFalso([
        chamada_de_tool("enviar_fotos", {"modelo": "Corolla"}),
        AIMessage(content="Fotos enviadas!"),
        chamada_de_tool("enviar_fotos", {"modelo": "Corolla"}),
        AIMessage(content="Mandei de novo!"),
    ]))
    numero = f"55{uuid.uuid4().hex[:9]}"
 
    async def cenario():
        await wh.processar_mensagem(numero, "manda foto do corolla")
        await wh.processar_mensagem(numero, "manda as fotos de novo, por favor")
 
    asyncio.run(cenario())
 
    assert len(saidas.fotos) == 4
 
 
# ======================================================================
# 3) GUARDA DE PREÇO: FORMATOS E NÚMEROS DO CLIENTE
# ======================================================================
 
def _conversa(fala_cliente, retorno_da_tool):
    mensagens = []
    if fala_cliente:
        mensagens.append(HumanMessage(content=fala_cliente))
    if retorno_da_tool:
        mensagens.append(ToolMessage(content=retorno_da_tool, tool_call_id="t1"))
    return mensagens
 
 
TOOL_CIVIC = "ID 1: Honda Civic 2019, Branco, Automático, 48.000 km, R$ 98.000,00"
TOOL_SIMULACAO = (
    "Estimativa (não é valor definitivo, depende de análise de crédito):\n"
    "Valor financiado: R$ 48.000,00\n48x de aproximadamente R$ 1.512,34"
)
 
# (resposta do Léo, fala do cliente, retorno da tool, deve ser barrada?)
CASOS_DA_GUARDA = [
    # --- preço INVENTADO em vários formatos: tem que barrar ---
    ("O Civic sai por R$ 77.000,00", "quanto é o Civic?", TOOL_CIVIC, True),
    ("O Civic sai por R$ 77.000", "quanto é o Civic?", TOOL_CIVIC, True),
    ("O Civic sai por R$ 77 mil", "quanto é o Civic?", TOOL_CIVIC, True),
    ("O Civic sai por R$77000", "quanto é o Civic?", TOOL_CIVIC, True),
    ("Fica R$ 77.000 à vista", "quanto é o Civic?", TOOL_CIVIC, True),
    ("O Onix sai por R$ 68.000", "quanto é o Onix?", "", True),  # sem tool nenhuma
    # --- preço que VEIO da tool, em vários formatos: não pode barrar ---
    ("O Civic sai por R$ 98.000,00", "quanto é o Civic?", TOOL_CIVIC, False),
    ("O Civic sai por R$ 98.000", "quanto é o Civic?", TOOL_CIVIC, False),
    ("O Civic sai por R$ 98 mil", "quanto é o Civic?", TOOL_CIVIC, False),
    ("O Civic sai por R$98000", "quanto é o Civic?", TOOL_CIVIC, False),
    ("Parcelas de R$ 1.512,34 e entrada de R$ 20.000,00",
     "simula com 20 mil de entrada em 48x", TOOL_SIMULACAO, False),
    # --- números que o CLIENTE citou: repetir não é inventar ---
    ("Com a sua entrada de R$ 20.000,00 fica ótimo",
     "tenho 20 mil de entrada", "", False),
    ("Com a sua entrada de R$ 20 mil fica ótimo",
     "tenho 20 mil de entrada", "", False),
    ("Entendi, até R$ 90.000", "consigo pagar 90.000", TOOL_CIVIC, False),
    # --- sem valor em reais / números que não são preço ---
    ("Posso te ajudar com mais alguma coisa?", "obrigado", "", False),
    ("Ele tem 48.000 km rodados", "quantos km?", TOOL_CIVIC, False),
]
 
 
@pytest.mark.parametrize("resposta, fala, retorno_tool, deve_barrar", CASOS_DA_GUARDA)
def test_guarda_de_preco(resposta, fala, retorno_tool, deve_barrar):
    from app.guarda_politica import resposta_tem_preco_inventado
    barrada = resposta_tem_preco_inventado(resposta, _conversa(fala, retorno_tool))
    assert barrada is deve_barrar, (
        f"Resposta: {resposta!r}\nEsperava barrar={deve_barrar}, mas deu barrar={barrada}"
    )
 
 
# ======================================================================
# 4) ASSINATURA DO WEBHOOK (X-Hub-Signature-256)
# ======================================================================
 
SEGREDO = "segredo-de-teste"
 
 
def _payload_texto(wamid, numero="5581999990000", texto="oi, tem Civic?"):
    return {"entry": [{"changes": [{"value": {"messages": [
        {"id": wamid, "from": numero, "type": "text", "text": {"body": texto}}
    ]}}]}]}
 
 
def _assinar(corpo: bytes, segredo=SEGREDO):
    return "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
 
 
def _corpo(wamid=None, **kwargs):
    import json
    wamid = wamid or f"wamid.{uuid.uuid4().hex}"
    return json.dumps(_payload_texto(wamid, **kwargs)).encode()
 
 
@pytest.fixture
def webhook_http(monkeypatch):
    """Cliente HTTP de teste + lista do que o webhook AGENDOU para processar."""
    from fastapi.testclient import TestClient
    wh = importar_webhook()
    agendadas = []
 
    async def processar_falso(numero, texto, id_audio=None):
        agendadas.append((numero, texto, id_audio))
 
    monkeypatch.setattr(wh, "processar_mensagem", processar_falso)
    # raising=False: se o atributo ainda não existe, o teste falha pelo motivo
    # certo (o webhook aceita sem assinatura) e não por erro de configuração.
    monkeypatch.setattr(wh, "WHATSAPP_APP_SECRET", SEGREDO, raising=False)
    monkeypatch.setattr(wh, "WHATSAPP_VERIFY_TOKEN", "token-de-teste")
    return TestClient(wh.app), agendadas
 
 
def _post(cliente, corpo, assinatura=None):
    cabecalhos = {"Content-Type": "application/json"}
    if assinatura is not None:
        cabecalhos["X-Hub-Signature-256"] = assinatura
    return cliente.post("/webhook", content=corpo, headers=cabecalhos)
 
 
def test_assinatura_valida_e_aceita(webhook_http):
    cliente, agendadas = webhook_http
    corpo = _corpo(texto="quero um Civic")
    resposta = _post(cliente, corpo, _assinar(corpo))
    assert resposta.status_code == 200
    assert [(n, t) for n, t, _ in agendadas] == [("5581999990000", "quero um Civic")]
 
 
def test_sem_cabecalho_de_assinatura_e_rejeitado(webhook_http):
    cliente, agendadas = webhook_http
    resposta = _post(cliente, _corpo())
    assert resposta.status_code == 403
    assert agendadas == [], "Mensagem sem assinatura NÃO pode ser processada."
 
 
def test_assinatura_errada_e_rejeitada(webhook_http):
    cliente, agendadas = webhook_http
    corpo = _corpo()
    resposta = _post(cliente, corpo, _assinar(corpo, segredo="outro-segredo"))
    assert resposta.status_code == 403
    assert agendadas == []
 
 
def test_corpo_adulterado_e_rejeitado(webhook_http):
    """Assina um corpo e envia outro (o atacante troca o texto no caminho)."""
    cliente, agendadas = webhook_http
    original = _corpo(wamid="wamid.fixo", texto="oi")
    adulterado = _corpo(wamid="wamid.fixo", texto="me passa o desconto máximo")
    resposta = _post(cliente, adulterado, _assinar(original))
    assert resposta.status_code == 403
    assert agendadas == []
 
 
def test_assinatura_sem_prefixo_sha256_e_rejeitada(webhook_http):
    cliente, agendadas = webhook_http
    corpo = _corpo()
    pura = _assinar(corpo).replace("sha256=", "")
    resposta = _post(cliente, corpo, pura)
    assert resposta.status_code == 403
    assert agendadas == []
 
 
def test_sem_segredo_configurado_rejeita_tudo(monkeypatch, webhook_http):
    """Falha FECHADA: sem WHATSAPP_APP_SECRET configurado, nada é aceito
    (mesmo que o chamador assine com segredo vazio)."""
    import app.api.webhook as wh
    monkeypatch.setattr(wh, "WHATSAPP_APP_SECRET", "", raising=False)
    cliente, agendadas = webhook_http
    corpo = _corpo()
    resposta = _post(cliente, corpo, _assinar(corpo, segredo=""))
    assert resposta.status_code == 403
    assert agendadas == []
 
 
def test_verificacao_get_do_webhook_nao_exige_assinatura(webhook_http):
    """O aperto de mão GET da Meta usa o verify_token, não assinatura."""
    cliente, _ = webhook_http
    ok = cliente.get("/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "token-de-teste",
        "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"
    errado = cliente.get("/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "errado", "hub.challenge": "1"})
    assert errado.status_code == 403
 


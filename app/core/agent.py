"""
O "cérebro" do Léo - Etapa 1, Blocos 2 e 7A.

Um grafo só, mas a cada mensagem ele lê a LOJA da conversa (estado["loja_id"])
e monta prompt + ferramentas daquela loja (ver app/core/montagem.py).
loja_id, lead_id e canal são injetados nas ferramentas pelo código, nunca
pelo modelo: mesmo que o modelo tente passar outros, são sobrescritos.

Bloco 7A: o prompt também conhece o MOMENTO da conversa (primeiro contato,
vendedor a caminho), lido do banco a cada mensagem.
"""
from datetime import datetime
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import tools_condition
from langchain_core.messages import ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import MODELO_LLM, TEMPERATURA, TIMEOUT, MAX_RETRIES
from app.handoff import estado_do_handoff
from app.lojas import carregar_loja
from app.mensagens import ja_respondeu
from app.core.montagem import (
    TODAS_AS_FERRAMENTAS, ferramentas_da_loja, montar_prompt, fuso_da_loja,
)

LOJA_PADRAO = 1

# --- O modelo (sem ferramentas amarradas: cada loja amarra as suas) ---
llm = ChatGoogleGenerativeAI(
    model=MODELO_LLM,
    temperature=TEMPERATURA,
    timeout=TIMEOUT,
    max_retries=MAX_RETRIES,
    thinking_budget=0,
)

# Compatibilidade com código antigo que importava esta lista.
ferramentas = TODAS_AS_FERRAMENTAS

TOOLS_COM_LEAD_ID = {"registrar_troca", "agendar_visita", "registrar_lead",
                     "acionar_handoff", "registrar_interesse"}
TOOLS_COM_LOJA_ID = {f.name for f in TODAS_AS_FERRAMENTAS}
TOOLS_COM_CANAL = {"registrar_interesse"}

# Cache do modelo já amarrado, por conjunto de ferramentas.
_modelos_amarrados: dict = {}


class EstadoConversa(TypedDict):
    messages: Annotated[list, add_messages]
    lead_id: str
    loja_id: int
    canal: str


def _loja_do_estado(estado):
    loja_id = estado.get("loja_id") or LOJA_PADRAO
    return loja_id, carregar_loja(loja_id)


def _momento_da_conversa(estado, loja_id) -> dict:
    """Primeiro contato? Vendedor a caminho? Se o banco falhar, segue normal."""
    lead_id = estado.get("lead_id") or ""
    if not lead_id:
        return {"em_espera": False, "primeiro_contato": False}
    try:
        return {
            "em_espera": estado_do_handoff(lead_id, loja_id) == "aguardando_humano",
            "primeiro_contato": not ja_respondeu(lead_id, loja_id),
        }
    except Exception as erro:
        print(f"[Agente] Aviso: não consegui ler o momento da conversa ({erro!r}).")
        return {"em_espera": False, "primeiro_contato": False}


def _modelo_com(ferramentas_loja):
    # O LLM falso dos testes não tem bind_tools: usamos ele direto.
    if not hasattr(llm, "bind_tools"):
        return llm
    chave = (id(llm), tuple(f.name for f in ferramentas_loja))
    if chave not in _modelos_amarrados:
        _modelos_amarrados[chave] = llm.bind_tools(ferramentas_loja)
    return _modelos_amarrados[chave]


def no_agente(estado: EstadoConversa):
    loja_id, loja = _loja_do_estado(estado)
    momento = _momento_da_conversa(estado, loja_id)
    ferramentas_loja = ferramentas_da_loja(loja, em_espera=momento["em_espera"])
    agora = datetime.now(fuso_da_loja(loja))
    prompt = montar_prompt(loja, ferramentas_loja, agora, **momento)
    resposta = _modelo_com(ferramentas_loja).invoke([("system", prompt)] + estado["messages"])
    return {"messages": [resposta]}


def no_ferramentas(estado: EstadoConversa):
    """Executa as tools pedidas pelo modelo, injetando lead_id, loja_id e canal.
    Só aceita tools LIGADAS na loja (e permitidas no momento). Erro vira ToolMessage."""
    ultima = estado["messages"][-1]
    lead_id = estado.get("lead_id", "")
    canal = estado.get("canal", "") or ""
    loja_id, loja = _loja_do_estado(estado)
    momento = _momento_da_conversa(estado, loja_id)
    permitidas = {f.name: f for f in ferramentas_da_loja(loja, em_espera=momento["em_espera"])}
    saidas = []

    for chamada in ultima.tool_calls:
        nome = chamada["name"]
        try:
            tool = permitidas.get(nome)
            if tool is None:
                if nome not in TOOLS_COM_LOJA_ID:
                    motivo = f"Erro: a ferramenta '{nome}' não existe."
                else:
                    motivo = f"Erro: a ferramenta '{nome}' não está disponível nesta loja agora."
                saidas.append(ToolMessage(
                    content=motivo,
                    tool_call_id=chamada["id"],
                    name=nome,
                ))
                continue

            chamada_ajustada = dict(chamada)
            chamada_ajustada["args"] = dict(chamada.get("args") or {})
            if nome in TOOLS_COM_LOJA_ID:
                chamada_ajustada["args"]["loja_id"] = loja_id   # sempre sobrescreve
            if nome in TOOLS_COM_LEAD_ID:
                chamada_ajustada["args"]["lead_id"] = lead_id
            if nome in TOOLS_COM_CANAL:
                chamada_ajustada["args"]["canal"] = canal

            mensagem = tool.invoke(chamada_ajustada)
            mensagem.name = nome
            saidas.append(mensagem)

        except Exception as e:
            saidas.append(ToolMessage(
                content=f"Erro ao executar a ferramenta '{nome}': {e}",
                tool_call_id=chamada["id"],
                name=nome,
            ))

    return {"messages": saidas}


construtor = StateGraph(EstadoConversa)
construtor.add_node("agente", no_agente)
construtor.add_node("ferramentas", no_ferramentas)
construtor.add_edge(START, "agente")
construtor.add_conditional_edges("agente", tools_condition, {
    "tools": "ferramentas",
    END: END,
})
construtor.add_edge("ferramentas", "agente")

# Memória das conversas (em produção vira PostgresSaver - Etapa 5).
memoria = MemorySaver()
agente_grafo = construtor.compile(checkpointer=memoria)

"""
O "cérebro" do Léo - Etapa 1, Blocos 2 e 7A.

Um grafo só, mas a cada mensagem ele lê a LOJA da conversa (estado["loja_id"])
e monta prompt + ferramentas daquela loja (ver app/core/montagem.py).
loja_id, lead_id e canal são injetados nas ferramentas pelo código, nunca
pelo modelo: mesmo que o modelo tente passar outros, são sobrescritos.

Bloco 7A: o prompt também conhece o MOMENTO da conversa (primeiro contato,
vendedor a caminho), lido do banco a cada mensagem.

L3/L4: estado["equipe"] preenchido (dono ou gestor cadastrado escrevendo) =
MODO EQUIPE: outro prompt e só a ferramenta registrar_recado. Cliente recebe os
recados ativos da loja no prompt.
"""
import time
from datetime import datetime
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.prebuilt import tools_condition
from langchain_core.messages import ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import MODELO_LLM, TEMPERATURA, TIMEOUT, MAX_RETRIES
from app.chaves import exigir_loja
from app.cliente_da_casa import compras_do_cliente
from app.handoff import estado_do_handoff
from app.lojas import carregar_loja
from app.mensagens import ja_respondeu
from app.recados import recados_ativos
from app.sombra import FERRAMENTAS_QUE_GRAVAM, RESPOSTA_DA_FERRAMENTA as RESPOSTA_DA_FERRAMENTA_SOMBRA
from app.relogio import dia_local
from app.retomada import retomada_recente
from app.core.montagem import (
    FERRAMENTAS_EQUIPE, TODAS_AS_FERRAMENTAS, ferramentas_da_loja, montar_prompt,
    montar_prompt_equipe, fuso_da_loja,
)


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
TOOLS_COM_LOJA_ID = {f.name for f in TODAS_AS_FERRAMENTAS + FERRAMENTAS_EQUIPE}
TOOLS_COM_CANAL = {"registrar_interesse"}
TOOLS_COM_AUTOR = {"registrar_recado"}     # L3/L4: autor vem do cadastro, nunca do modelo

# Bloco S6: ferramenta fora desta loja (ou deste momento): o cliente não fica sabendo.
FERRAMENTA_FORA = ("NÃO conte isso ao cliente: nada de 'não consegui consultar', 'não consegui "
                   "buscar', erro, sistema ou falha. Responda com naturalidade, sem essa "
                   "informação (ex.: 'vou confirmar isso com o pessoal da equipe').")

# Cache do modelo já amarrado, por conjunto de ferramentas.
_modelos_amarrados: dict = {}


class EstadoConversa(TypedDict):
    messages: Annotated[list, add_messages]
    lead_id: str
    loja_id: int
    canal: str
    equipe: dict      # L3/L4: vazio = cliente; preenchido = dono ou gestor (modo equipe)
    sombra: bool      # L9: loja em modo sombra (ferramenta que grava não executa)


def _loja_do_estado(estado):
    loja_id = exigir_loja(estado.get("loja_id"))   # sem loja: erro, nunca loja 1
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

def _retomada_da_conversa(estado, loja_id, agora):
    """Etapa 2, Bloco 4: mandei retomada para este cliente? Se o banco falhar, segue normal."""
    lead_id = estado.get("lead_id") or ""
    if not lead_id:
        return None
    try:
        return retomada_recente(loja_id, lead_id, estado.get("canal") or "", agora)
    except Exception as erro:
        print(f"[Agente] Aviso: não consegui ler a retomada ({erro!r}).")
        return None


def _modelo_com(ferramentas_loja):
    # O LLM falso dos testes não tem bind_tools: usamos ele direto.
    if not hasattr(llm, "bind_tools"):
        return llm
    chave = (id(llm), tuple(f.name for f in ferramentas_loja))
    if chave not in _modelos_amarrados:
        _modelos_amarrados[chave] = llm.bind_tools(ferramentas_loja)
    return _modelos_amarrados[chave]


def _recados_da_loja(loja_id, loja, agora) -> list:
    """L3/L4: recados ativos para o prompt do cliente. Se o banco falhar, segue sem."""
    try:
        return recados_ativos(loja_id, dia_local(loja, agora))
    except Exception as erro:
        print(f"[Agente] Aviso: não consegui ler os recados ({erro!r}).")
        return []


def no_agente(estado: EstadoConversa):
    loja_id, loja = _loja_do_estado(estado)
    if estado.get("equipe"):
        agora = datetime.now(fuso_da_loja(loja))
        prompt = montar_prompt_equipe(loja, estado["equipe"], agora)
        resposta = _modelo_com(FERRAMENTAS_EQUIPE).invoke([("system", prompt)] + estado["messages"])
        return {"messages": [resposta]}
    momento = _momento_da_conversa(estado, loja_id)
    ferramentas_loja = ferramentas_da_loja(loja, em_espera=momento["em_espera"])
    agora = datetime.now(fuso_da_loja(loja))
    retomada = _retomada_da_conversa(estado, loja_id, agora)
    # Etapa 2, Bloco 5B: já comprou aqui? (falhou: segue como lead normal)
    compras = compras_do_cliente(loja, estado.get("lead_id") or "", estado.get("canal") or "")
    prompt = montar_prompt(loja, ferramentas_loja, agora, retomada=retomada,
                           compras=compras, recados=_recados_da_loja(loja_id, loja, agora),
                           **momento)
    resposta = _modelo_com(ferramentas_loja).invoke([("system", prompt)] + estado["messages"])
    return {"messages": [resposta]}


def no_ferramentas(estado: EstadoConversa):
    """Executa as tools pedidas pelo modelo, injetando lead_id, loja_id e canal.
    Só aceita tools LIGADAS na loja (e permitidas no momento). Erro vira ToolMessage."""
    ultima = estado["messages"][-1]
    lead_id = estado.get("lead_id", "")
    canal = estado.get("canal", "") or ""
    loja_id, loja = _loja_do_estado(estado)
    equipe = estado.get("equipe") or {}
    if equipe:      # L3/L4: modo equipe só tem registrar_recado
        permitidas = {f.name: f for f in FERRAMENTAS_EQUIPE}
    else:
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
                    motivo = f"Erro: a ferramenta '{nome}' não está disponível nesta loja agora. " + FERRAMENTA_FORA
                saidas.append(ToolMessage(
                    content=motivo,
                    tool_call_id=chamada["id"],
                    name=nome,
                ))
                continue

            if estado.get("sombra") and nome in FERRAMENTAS_QUE_GRAVAM:      # L9
                saidas.append(ToolMessage(content=RESPOSTA_DA_FERRAMENTA_SOMBRA,
                                          tool_call_id=chamada["id"], name=nome))
                continue

            chamada_ajustada = dict(chamada)
            chamada_ajustada["args"] = dict(chamada.get("args") or {})
            if nome in TOOLS_COM_LOJA_ID or "loja_id" in (getattr(tool, "args", None) or {}):
                chamada_ajustada["args"]["loja_id"] = loja_id   # sempre sobrescreve
            if nome in TOOLS_COM_LEAD_ID:
                chamada_ajustada["args"]["lead_id"] = lead_id
            if nome in TOOLS_COM_CANAL:
                chamada_ajustada["args"]["canal"] = canal
            if nome in TOOLS_COM_AUTOR:
                chamada_ajustada["args"]["autor"] = equipe.get("nome") or ""

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

class MemoriaLimitada(PostgresSaver):
    """Memória das conversas no PostgreSQL (PG2, Maratona Postgres): a conversa continua depois
    de reiniciar o processo. L12: a memória não cresce para sempre. Conversa parada há mais de
    HORAS_SEM_USO sai; acima de MAX_CONVERSAS, saem as mais antigas. Sem perda: com a memória
    vazia, o turno manda o histórico do banco (Bloco 4B). A poda roda no máximo a cada
    PODAR_A_CADA_S segundos (ela consulta o banco). Apagar uma conversa: delete_thread(thread).
    A conexão vem do banco.py (pool da memória), sempre o banco da BANCO_URL em uso."""

    HORAS_SEM_USO = 24
    MAX_CONVERSAS = 2000
    PODAR_A_CADA_S = 300

    def __init__(self, *, relogio=time.time):
        super().__init__(None)
        self._relogio = relogio
        self._ultima_poda: float | None = None

    @property
    def conn(self):
        import banco
        return banco.pool_da_memoria()

    @conn.setter
    def conn(self, _valor):            # o PostgresSaver tenta guardar a conexão: ela vem do banco.py
        pass

    def put(self, config, checkpoint, metadata, new_versions):
        salvo = super().put(config, checkpoint, metadata, new_versions)
        agora = self._relogio()
        if self._ultima_poda is None or agora - self._ultima_poda >= self.PODAR_A_CADA_S:
            self._ultima_poda = agora
            self.podar()
        return salvo

    def ultimos_usos(self) -> dict[str, float]:
        """Conversa -> último uso (segundos desde 1970), pela data da última fotografia salva."""
        with self._cursor() as cur:
            cur.execute("SELECT thread_id, MAX(checkpoint->>'ts') AS ts FROM checkpoints "
                        "WHERE checkpoint_ns = '' GROUP BY thread_id")
            linhas = cur.fetchall()
        return {l["thread_id"]: datetime.fromisoformat(l["ts"]).timestamp() for l in linhas if l["ts"]}

    def podar(self) -> int:
        """Tira da memória as conversas paradas e o excesso. Devolve quantas saíram."""
        agora = self._relogio()
        usos = self.ultimos_usos()
        sair = {t for t, quando in usos.items() if agora - quando > self.HORAS_SEM_USO * 3600}
        ficam = sorted((q, t) for t, q in usos.items() if t not in sair)
        excesso = len(ficam) - self.MAX_CONVERSAS
        if excesso > 0:
            sair |= {t for _, t in ficam[:excesso]}
        for thread in sair:
            self.delete_thread(thread)
        return len(sair)


# Memória das conversas no PostgreSQL (PG2). L12: com limite.
memoria = MemoriaLimitada()
agente_grafo = construtor.compile(checkpointer=memoria)

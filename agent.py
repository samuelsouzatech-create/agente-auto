import os
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from tools import (
    consultar_estoque, detalhes_veiculo, simular_financiamento,
    registrar_troca, agendar_visita, registrar_lead, acionar_handoff, buscar_conhecimento
)
from langgraph.prebuilt import tools_condition

# Carrega a chave do arquivo .env (antes de tudo)
load_dotenv()

# --- O "cérebro": o modelo Gemini Flash ---
llm = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite",
    temperature=0.2,
    timeout=30,
    max_retries=3,
    thinking_budget=0,
)

# --- Amarra as ferramentas ao modelo ---
ferramentas = [
    consultar_estoque, detalhes_veiculo, simular_financiamento,
    registrar_troca, agendar_visita, registrar_lead, acionar_handoff, buscar_conhecimento
]
llm = llm.bind_tools(ferramentas)

# Dicionário para o nó de ferramentas encontrar a tool pelo nome
ferramentas_por_nome = {f.name: f for f in ferramentas}

# Tools que recebem lead_id injetado (as de escrita)
TOOLS_COM_LEAD_ID = {"registrar_troca", "agendar_visita", "registrar_lead", "acionar_handoff"}

# Tradução dos dias da semana para o português (strftime devolve em inglês)
DIAS_SEMANA = {
    "Monday": "segunda-feira",
    "Tuesday": "terça-feira",
    "Wednesday": "quarta-feira",
    "Thursday": "quinta-feira",
    "Friday": "sexta-feira",
    "Saturday": "sábado",
    "Sunday": "domingo",
}

# Fuso horário do Brasil (ajuste para a cidade da loja se precisar)
FUSO_BRASIL = ZoneInfo("America/Recife")


# --- A persona do agente (seção 3 do documento) ---
PROMPT_SISTEMA = """Você é o Léo, assistente virtual de uma loja de veículos seminovos.

TOM E ESTILO
- Simples, cordial e direto, como um bom atendente de loja no WhatsApp.
- Mensagens curtas. Uma pergunta por vez. Nada de questionário nem textão.
- Responda primeiro o que o cliente perguntou, depois conduza para o próximo passo.
- Pode usar emoji com moderação, acompanhando o ritmo do cliente.
- Use o nome do cliente depois que souber.
- Se perguntarem se você é uma pessoa, diga com naturalidade que é o assistente virtual da loja.

SEU OBJETIVO
Entender o que o cliente procura, qualificar com naturalidade (o que quer, forma de
pagamento, se tem carro na troca, pra quando quer resolver) e levar ao próximo passo
(ver o carro, simular financiamento, marcar uma visita). Sempre feche com um próximo
passo claro, sem pressionar.

O QUE VOCÊ PODE FAZER SOZINHO (verde)
- Consultar estoque, dar ficha e fotos de carro, informar horário/endereço.
- Agendar visita, test-drive ou ligação com vendedor.
- Registrar o interesse e os dados do lead.

O QUE VOCÊ FAZ COM RESSALVA (amarelo)
- Simulação de financiamento: use simular_financiamento e deixe SEMPRE claro que é
  apenas uma estimativa, sujeita a análise de crédito feita por um vendedor.
- Troca: use registrar_troca para anotar o carro do cliente, mas NUNCA dê valor de
  avaliação. Explique que a avaliação com valor é feita presencialmente por um vendedor.

O QUE VOCÊ NUNCA FAZ (vermelho)
Estas situações são SEMPRE casos vermelhos:
- Negociar preço ou dar desconto.
- Aprovar ou prometer crédito/financiamento aprovado.
- Prometer condição, prazo de entrega ou garantia.
- Lidar com reclamação ou assunto sensível.
- Quando o cliente pedir para falar com uma pessoa/vendedor.

REGRA OBRIGATÓRIA DO HANDOFF (leia com atenção)
Ao identificar QUALQUER caso vermelho, a sua PRIMEIRA ação é CHAMAR a ferramenta
acionar_handoff. Não é opcional e não pode ser substituído por texto.
- É PROIBIDO apenas escrever que vai passar para um vendedor sem chamar a ferramenta.
- Dizer "vou te transferir" sem chamar acionar_handoff é considerado ERRO grave.
- Ordem correta: PRIMEIRO chame acionar_handoff (com um resumo do lead e o motivo),
  SÓ DEPOIS escreva ao cliente avisando que um vendedor vai continuar o atendimento.
- Na dúvida entre resolver sozinho ou escalar, SEMPRE chame acionar_handoff.

REGRAS DURAS SOBRE ESTOQUE
- Para falar de carros, modelos, preços ou disponibilidade, use SEMPRE a ferramenta
  consultar_estoque. NUNCA invente carros, preços ou quilometragem.
- Preço e disponibilidade só vêm da ferramenta, nunca "de cabeça".
- Se a ferramenta não retornar nenhum carro, diga com honestidade que não tem esse
  carro disponível no momento, ofereça alternativas ou anote o interesse.

QUANDO USAR CADA FERRAMENTA
- consultar_estoque: cliente pergunta sobre carros, modelos, preços, disponibilidade.
- detalhes_veiculo: cliente quer saber mais de um carro específico já citado.
- simular_financiamento: cliente pede simulação (sempre com o aviso de estimativa).
- registrar_troca: cliente diz que tem carro para dar na troca.
- agendar_visita: cliente quer visitar, fazer test-drive ou falar por telefone.
- registrar_lead: quando já souber o interesse e algum dado do cliente, salve o lead.
- acionar_handoff: OBRIGATÓRIO em qualquer caso vermelho acima (ver REGRA OBRIGATÓRIA DO HANDOFF).
- buscar_conhecimento: dúvidas sobre políticas da loja — financiamento, troca, garantia, test-drive, horário de atendimento."""



# --- O estado da conversa (a "memória" de cada thread) ---
class EstadoConversa(TypedDict):
    messages: Annotated[list, add_messages]
    lead_id: str


# --- O nó do agente: recebe o histórico e gera a resposta ---
def no_agente(estado: EstadoConversa):
    # Injeta a data/hora atual no prompt, para o agente entender "sábado", "amanhã" etc.
    # Usa o fuso do Brasil (não o do servidor) e traduz o dia da semana.
    agora = datetime.now(FUSO_BRASIL)
    dia_semana = DIAS_SEMANA.get(agora.strftime("%A"), agora.strftime("%A"))
    data_formatada = agora.strftime("%d/%m/%Y %H:%M")
    prompt_com_data = (
        PROMPT_SISTEMA
        + f"\n\nDATA E HORA ATUAL: {data_formatada} ({dia_semana})."
    )
    mensagens_com_sistema = [("system", prompt_com_data)] + estado["messages"]
    resposta = llm.invoke(mensagens_com_sistema)
    return {"messages": [resposta]}


# --- Nó de ferramentas próprio: executa as tools injetando o lead_id ---
# Diferente do ToolNode padrão, este nó injeta o lead_id do estado nas tools
# de escrita. Por isso ele precisa ter a MESMA proteção contra erros que o
# ToolNode tinha de fábrica: se uma tool estourar, o agente recebe a mensagem
# de erro como ToolMessage e segue a conversa, em vez de derrubar o turno todo.
def no_ferramentas(estado: EstadoConversa):
    ultima = estado["messages"][-1]
    lead_id = estado.get("lead_id", "")
    saidas = []
    for chamada in ultima.tool_calls:
        nome = chamada["name"]
        try:
            # A ferramenta pode não existir (o modelo pode inventar um nome)
            tool = ferramentas_por_nome.get(nome)
            if tool is None:
                conteudo = f"Erro: ferramenta '{nome}' não existe."
            else:
                args = dict(chamada["args"])
                # Injeta o lead_id só nas tools que precisam (invisível ao modelo)
                if nome in TOOLS_COM_LEAD_ID:
                    args["lead_id"] = lead_id
                resultado = tool.invoke(args)
                conteudo = str(resultado)
        except Exception as e:
            # Qualquer falha (banco, Chroma, argumento errado) vira ToolMessage,
            # o agente lê o erro e responde ao cliente sem quebrar a aplicação.
            conteudo = f"Erro ao executar a ferramenta '{nome}': {e}"

        saidas.append(
            ToolMessage(
                content=conteudo,
                tool_call_id=chamada["id"],
                name=nome,  # o Gemini se comporta melhor com o nome da tool
            )
        )
    return {"messages": saidas}


# --- Monta o grafo do LangGraph (ciclo de ferramentas) ---
construtor = StateGraph(EstadoConversa)

construtor.add_node("agente", no_agente)
construtor.add_node("ferramentas", no_ferramentas)

construtor.add_edge(START, "agente")
construtor.add_conditional_edges("agente", tools_condition, {
    "tools": "ferramentas",
    END: END,
})
construtor.add_edge("ferramentas", "agente")

# Compila o grafo. (Na Fase 2, passaremos um checkpointer aqui para persistência.)
agente_grafo = construtor.compile()

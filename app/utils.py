def extrair_texto(content):
    """Consolida o conteúdo de uma mensagem do agente em texto puro.

    O Gemini 3.x devolve o conteúdo como lista de blocos (dicts com 'text'),
    o formato antigo devolve string direto. Esta função é NEUTRA: não aplica
    nenhuma formatação específica de interface (ex.: escape de '$' do
    Streamlit fica por conta de quem exibe). Serve tanto para o Streamlit
    quanto para o WhatsApp na Fase 2.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        partes = []
        for bloco in content:
            if isinstance(bloco, dict):
                t = bloco.get("text") or bloco.get("Texto") or bloco.get("texto")
                if t:
                    partes.append(t)
            elif isinstance(bloco, str):
                partes.append(bloco)
        return "\n".join(partes)
    return str(content)

from langchain_core.messages import HumanMessage


def mensagens_do_turno(resultado) -> list:
    """Devolve só as mensagens geradas NESTE turno (resposta do Léo às tools
    da vez), não a conversa inteira que o MemorySaver guarda.

    O grafo roda com o histórico completo, mas a cada turno as mensagens novas
    ficam no FIM da lista. A última HumanMessage marca o começo do turno atual:
    tudo depois dela é resposta deste turno; tudo antes é histórico.

    Isso evita, por exemplo, reenviar fotos pedidas em turnos anteriores (cujos
    artifacts continuam na lista por causa da memória)."""
    mensagens = resultado["messages"]
    corte = 0
    for i in range(len(mensagens) - 1, -1, -1):
        if isinstance(mensagens[i], HumanMessage):
            corte = i
            break
    # Do primeiro item DEPOIS da última fala do cliente até o fim.
    return mensagens[corte + 1:]

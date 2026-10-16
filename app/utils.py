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

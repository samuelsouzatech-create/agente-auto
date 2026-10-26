from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma

# RAG com inicialização preguiçosa: o Chroma só é criado na primeira chamada.
_banco_conhecimento = None


def _get_banco_conhecimento():
    global _banco_conhecimento
    if _banco_conhecimento is None:
        embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
        _banco_conhecimento = Chroma(
            persist_directory="chroma_db",
            embedding_function=embeddings,
        )
    return _banco_conhecimento


@tool
def buscar_conhecimento(pergunta: str,
                        loja_id: Annotated[int, InjectedToolArg] = 1) -> str:
    """Busca informações sobre as POLÍTICAS da loja: formas de pagamento,
    regras de financiamento, regras de troca, garantia, test-drive e horário
    de atendimento. Use sempre que o cliente perguntar COMO a loja funciona
    (e NÃO sobre quais carros existem - para carros, use consultar_estoque).

    Parâmetros:
    - pergunta: a dúvida do cliente, em linguagem natural
    """
    banco = _get_banco_conhecimento()
    # Filtro por loja: a política de uma loja nunca aparece na conversa de outra.
    resultados = banco.similarity_search(pergunta, k=3, filter={"loja_id": int(loja_id)})
    if not resultados:
        return "Não encontrei essa informação nas políticas da loja."
    return "\n\n---\n\n".join(doc.page_content for doc in resultados)

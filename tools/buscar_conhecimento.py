from langchain_core.tools import tool
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma

# RAG: acesso ao conhecimento (inicialização preguiçosa).
# Criamos o Chroma só na primeira chamada, não no import.
_banco_conhecimento = None


def _get_banco_conhecimento():
    """Cria a conexão com o Chroma uma única vez, sob demanda (lazy)."""
    global _banco_conhecimento
    if _banco_conhecimento is None:
        embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
        _banco_conhecimento = Chroma(
            persist_directory="chroma_db",
            embedding_function=embeddings,
        )
    return _banco_conhecimento


@tool
def buscar_conhecimento(pergunta: str) -> str:
    """Busca informações sobre as POLÍTICAS da loja: formas de pagamento,
    regras de financiamento, regras de troca, garantia, test-drive e horário
    de atendimento. Use esta ferramenta sempre que o cliente perguntar sobre
    COMO a loja funciona (e NÃO sobre quais carros existem — para carros, use
    consultar_estoque).

    Parâmetros:
    - pergunta: a dúvida do cliente, em linguagem natural
    """
    banco = _get_banco_conhecimento()
    resultados = banco.similarity_search(pergunta, k=3)
    if not resultados:
        return "Não encontrei essa informação nas políticas da loja."
    trechos = [doc.page_content for doc in resultados]
    return "\n\n---\n\n".join(trechos)

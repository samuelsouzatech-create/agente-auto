"""
Ferramenta do Léo para as POLÍTICAS da loja (RAG com Chroma).

O9 (Fase 3): o índice era aberto uma vez por processo e ficava guardado na
memória. O painel e o bot são processos diferentes: quando o painel salvava
um texto, o bot continuava com a cópia antiga (e às vezes dava erro) até
ser reiniciado. Experimento O9 (Windows, dois processos abertos ao mesmo
tempo): só descartar a cópia NÃO basta, porque o Chroma guarda um cache
interno por pasta e devolve a cópia velha. O que funcionou: antes de cada
uso, conferir se o arquivo do banco do índice mudou desde a abertura; se
mudou, descartar a cópia, limpar o cache interno do Chroma e abrir de novo.
Conferimos chroma.sqlite3 e também o chroma.sqlite3-wal, se existir.
Se a busca der erro, reabre e tenta uma vez mais.
Registro da decisão: docs/decisoes/o9_conhecimento.md.
"""
import os
import threading
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma

PASTA_CHROMA = "chroma_db"
_ARQUIVOS_DO_INDICE = ("chroma.sqlite3", "chroma.sqlite3-wal")

_banco_conhecimento = None
_assinatura_aberta = None
_trava = threading.Lock()


def _assinatura():
    """Data e tamanho dos arquivos do índice. Mudou = alguém gravou."""
    partes = []
    for nome in _ARQUIVOS_DO_INDICE:
        try:
            info = os.stat(os.path.join(PASTA_CHROMA, nome))
            partes.append((nome, info.st_mtime_ns, info.st_size))
        except OSError:
            partes.append((nome, None, None))
    return tuple(partes)


def _limpar_cache_chroma():
    """Sem isto, reabrir devolve a cópia velha (experimento O9, rodada 2)."""
    try:
        from chromadb.api.shared_system_client import SharedSystemClient
    except ImportError:
        from chromadb.api.client import SharedSystemClient
    SharedSystemClient.clear_system_cache()


def descartar_indice():
    """Esquece a cópia aberta; a próxima busca abre de novo, do disco."""
    global _banco_conhecimento, _assinatura_aberta
    with _trava:
        if _banco_conhecimento is not None:
            _banco_conhecimento = None
            _limpar_cache_chroma()
        _assinatura_aberta = None


def _get_banco_conhecimento():
    global _banco_conhecimento, _assinatura_aberta
    with _trava:
        if _banco_conhecimento is not None and _assinatura() != _assinatura_aberta:
            _banco_conhecimento = None
            _limpar_cache_chroma()
        if _banco_conhecimento is None:
            embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
            _banco_conhecimento = Chroma(
                persist_directory=PASTA_CHROMA,
                embedding_function=embeddings,
            )
            _assinatura_aberta = _assinatura()
        return _banco_conhecimento


@tool
def buscar_conhecimento(pergunta: str,
                        *, loja_id: Annotated[int, InjectedToolArg]) -> str:
    """Busca informações sobre as POLÍTICAS da loja: formas de pagamento,
    regras de financiamento, regras de troca, garantia e test-drive (horário de atendimento não: ele vem do cadastro
    da loja e já está nas instruções). Use sempre que o cliente perguntar COMO a loja funciona
    (e NÃO sobre quais carros existem - para carros, use consultar_estoque).

    Parâmetros:
    - pergunta: a dúvida do cliente, em linguagem natural
    """
    # Filtro por loja: a política de uma loja nunca aparece na conversa de outra.
    filtro = {"loja_id": int(loja_id)}
    try:
        resultados = _get_banco_conhecimento().similarity_search(pergunta, k=3, filter=filtro)
    except Exception:
        descartar_indice()
        resultados = _get_banco_conhecimento().similarity_search(pergunta, k=3, filter=filtro)
    if not resultados:
        return "Não encontrei essa informação nas políticas da loja."
    return "\n\n---\n\n".join(doc.page_content for doc in resultados)
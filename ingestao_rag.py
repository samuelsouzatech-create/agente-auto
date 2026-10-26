"""Indexa as políticas no Chroma, marcando cada pedaço com o loja_id.

Organização da pasta:
  conhecimento/*.txt          -> loja 1 (como era antes)
  conhecimento/loja_2/*.txt   -> loja 2 (e assim por diante)
"""
import os
import shutil
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma

load_dotenv()

PASTA_CONHECIMENTO = "conhecimento"
PASTA_CHROMA = "chroma_db"
LOJA_PADRAO = 1


def _ler_txts(pasta: str, loja_id: int) -> list:
    documentos = []
    for nome in sorted(os.listdir(pasta)):
        caminho = os.path.join(pasta, nome)
        if os.path.isfile(caminho) and nome.endswith(".txt"):
            with open(caminho, "r", encoding="utf-8") as arquivo:
                texto = arquivo.read()
            documentos.append(Document(
                page_content=texto,
                metadata={"fonte": nome, "loja_id": loja_id, "documento_id": f"{loja_id}:{nome}"},
            ))
    return documentos


def coletar_documentos() -> list:
    documentos = _ler_txts(PASTA_CONHECIMENTO, LOJA_PADRAO)
    for nome in sorted(os.listdir(PASTA_CONHECIMENTO)):
        caminho = os.path.join(PASTA_CONHECIMENTO, nome)
        if os.path.isdir(caminho) and nome.startswith("loja_"):
            try:
                loja_id = int(nome.split("_", 1)[1])
            except ValueError:
                print(f"Pasta ignorada (nome deve ser loja_<número>): {nome}")
                continue
            documentos.extend(_ler_txts(caminho, loja_id))
    return documentos


def ingerir():
    if os.path.exists(PASTA_CHROMA):
        shutil.rmtree(PASTA_CHROMA)
        print(f"Base anterior em '{PASTA_CHROMA}' apagada (recriando do zero).")

    documentos = coletar_documentos()
    lojas = sorted({d.metadata["loja_id"] for d in documentos})
    print(f"Arquivos lidos: {len(documentos)} documento(s), lojas: {lojas}.")

    divisor = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
    pedacos = divisor.split_documents(documentos)   # os metadados vão junto
    print(f"Pedaços gerados: {len(pedacos)}.")

    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
    Chroma.from_documents(documents=pedacos, embedding=embeddings, persist_directory=PASTA_CHROMA)
    print(f"Pronto! Vetores salvos em '{PASTA_CHROMA}'.")


if __name__ == "__main__":
    ingerir()

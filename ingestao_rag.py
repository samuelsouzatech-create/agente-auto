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

def ingerir():
    # 0. LIMPAR a base anterior, para não duplicar os pedaços a cada execução
    if os.path.exists(PASTA_CHROMA):
        shutil.rmtree(PASTA_CHROMA)
        print(f"Base anterior em '{PASTA_CHROMA}' apagada (recriando do zero).")
        
    # 1. LER os arquivos de texto (Python puro, sem langchain_community)
    documentos = []
    for nome_arquivo in os.listdir(PASTA_CONHECIMENTO):
        if nome_arquivo.endswith(".txt"):
            caminho = os.path.join(PASTA_CONHECIMENTO, nome_arquivo)
            with open(caminho, "r", encoding="utf-8") as arquivo:
                texto = arquivo.read()
            documentos.append(
                Document(page_content=texto, metadata={"fonte": nome_arquivo})
            )
    print(f"Arquivos lidos: {len(documentos)} documento(s).")

    # 2. QUEBRAR cada documento em pedaços (chunks)
    divisor = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=100,
    )
    pedacos = divisor.split_documents(documentos)
    print(f"Pedaços gerados: {len(pedacos)}.")

    # 3. Preparar o modelo de EMBEDDINGS do Gemini
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")

    # 4. GERAR os vetores e SALVAR no Chroma (em disco)
    Chroma.from_documents(
        documents=pedacos,
        embedding=embeddings,
        persist_directory=PASTA_CHROMA,
    )
    print(f"Pronto! Vetores salvos em '{PASTA_CHROMA}'.")

if __name__ == "__main__":
    ingerir()

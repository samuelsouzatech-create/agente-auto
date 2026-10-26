"""
Recria o índice do Chroma a partir da tabela 'conhecimento' (Etapa 1, Bloco 5).

A tabela é a fonte da verdade (editada na tela Conhecimento).
Os .txt servem só de carga inicial:
  conhecimento/*.txt          -> loja 1
  conhecimento/loja_2/*.txt   -> loja 2
Um .txt só entra se a loja ainda não tem documento com aquele título,
então o que foi editado na tela nunca é sobrescrito.

Pare o bot e o painel antes de rodar (no Windows, a pasta chroma_db fica travada).
"""
import os
import shutil

from dotenv import load_dotenv

load_dotenv()

import banco  # noqa: E402
import tools.buscar_conhecimento as busca  # noqa: E402
from app import conhecimento  # noqa: E402

PASTA_CONHECIMENTO = "conhecimento"
PASTA_CHROMA = "chroma_db"
LOJA_PADRAO = 1


def _arquivos() -> list[tuple[int, str, str]]:
    """(loja_id, titulo, texto) de cada .txt encontrado."""
    achados = []

    def ler(pasta, loja_id):
        for nome in sorted(os.listdir(pasta)):
            caminho = os.path.join(pasta, nome)
            if os.path.isfile(caminho) and nome.endswith(".txt"):
                with open(caminho, "r", encoding="utf-8") as arquivo:
                    achados.append((loja_id, nome[:-4], arquivo.read()))

    if not os.path.isdir(PASTA_CONHECIMENTO):
        return achados
    ler(PASTA_CONHECIMENTO, LOJA_PADRAO)
    for nome in sorted(os.listdir(PASTA_CONHECIMENTO)):
        caminho = os.path.join(PASTA_CONHECIMENTO, nome)
        if os.path.isdir(caminho) and nome.startswith("loja_"):
            try:
                ler(caminho, int(nome.split("_", 1)[1]))
            except ValueError:
                print(f"Pasta ignorada (nome deve ser loja_<número>): {nome}")
    return achados


def importar_txts() -> int:
    conexao = banco.conectar()
    try:
        lojas = {linha["id"] for linha in conexao.execute("SELECT id FROM lojas")}
    finally:
        conexao.close()
    importados = 0
    for loja_id, titulo, texto in _arquivos():
        if loja_id not in lojas:
            print(f"Arquivo '{titulo}' ignorado: a loja {loja_id} não existe.")
            continue
        if conhecimento.existe_titulo(loja_id, titulo):
            continue
        conhecimento.gravar(loja_id, titulo, texto)
        importados += 1
    return importados


def ingerir():
    banco.criar_tabelas()
    print(f"Documentos novos importados dos .txt: {importar_txts()}.")
    if os.path.exists(PASTA_CHROMA):
        shutil.rmtree(PASTA_CHROMA)
        print(f"Índice anterior em '{PASTA_CHROMA}' apagado (recriando).")
    busca._banco_conhecimento = None
    documentos = conhecimento.todos_os_documentos()
    for doc in documentos:
        conhecimento.indexar(doc["loja_id"], doc["id"], doc["titulo"], doc["texto"])
    lojas = sorted({d["loja_id"] for d in documentos})
    print(f"Pronto! {len(documentos)} documento(s) indexado(s), lojas: {lojas}.")


if __name__ == "__main__":
    ingerir()

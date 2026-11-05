"""
Carrega os .txt de UMA loja e refaz a consulta do assistente SÓ dessa loja (S4c).

Uso (na raiz do projeto):
  python ingestao_rag.py --loja 2

Arquivos: conhecimento/loja_<n>/*.txt. Um .txt solto em conhecimento/ não
vai para loja nenhuma (sem loja padrão): o script avisa e ignora.
A tabela 'conhecimento' é a fonte da verdade: um .txt só entra se a loja
ainda não tem documento com aquele título.
Não apaga a pasta do índice: o bot e o painel podem continuar abertos (O9).
Quem age: OPERADOR_NOME do .env (vai para o Registro).
"""
import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()

import banco  # noqa: E402
from app import conhecimento  # noqa: E402
from app.ator import como  # noqa: E402
from app.identidade import SemNomeOperador, nome_do_operador  # noqa: E402

PASTA_CONHECIMENTO = "conhecimento"


def pasta_da_loja(loja_id: int) -> str:
    return os.path.join(PASTA_CONHECIMENTO, f"loja_{int(loja_id)}")


def soltos() -> list[str]:
    """.txt direto em conhecimento/: sem loja, ficam de fora."""
    if not os.path.isdir(PASTA_CONHECIMENTO):
        return []
    return sorted(n for n in os.listdir(PASTA_CONHECIMENTO)
                  if n.endswith(".txt") and os.path.isfile(os.path.join(PASTA_CONHECIMENTO, n)))


def arquivos_da_loja(loja_id: int) -> list[tuple[str, str]]:
    pasta = pasta_da_loja(loja_id)
    achados = []
    if os.path.isdir(pasta):
        for nome in sorted(os.listdir(pasta)):
            caminho = os.path.join(pasta, nome)
            if os.path.isfile(caminho) and nome.endswith(".txt"):
                with open(caminho, "r", encoding="utf-8") as arquivo:
                    achados.append((nome[:-4], arquivo.read()))
    return achados


def _loja_existe(loja_id: int) -> bool:
    conexao = banco.conectar()
    try:
        return conexao.execute("SELECT 1 FROM lojas WHERE id = ?", (loja_id,)).fetchone() is not None
    finally:
        conexao.close()


def importar_txts(loja_id: int) -> int:
    if not _loja_existe(loja_id):
        raise ValueError(f"A loja {loja_id} não existe.")
    importados = 0
    for titulo, texto in arquivos_da_loja(loja_id):
        if conhecimento.existe_titulo(loja_id, titulo):
            continue
        conhecimento.gravar(loja_id, titulo, texto)
        importados += 1
    return importados


def main(argumentos=None) -> int:
    leitor = argparse.ArgumentParser(description="Carrega e reindexa o conhecimento de UMA loja.")
    leitor.add_argument("--loja", type=int, required=True, help="número da loja")
    opcoes = leitor.parse_args(argumentos)
    banco.criar_tabelas()
    try:
        operador = nome_do_operador()
    except SemNomeOperador as erro:
        print(erro)
        return 1
    for nome in soltos():
        print(f"Arquivo solto ignorado (sem loja): {nome}. "
              f"Para usar, mova para {pasta_da_loja(opcoes.loja)}.")
    with como(operador, "operador", "painel"):
        try:
            novos = importar_txts(opcoes.loja)
        except ValueError as erro:
            print(erro)
            return 1
    print(f"Documentos novos importados dos .txt: {novos}.")
    total = conhecimento.reindexar_loja(opcoes.loja)
    print(f"Pronto! Loja {opcoes.loja}: {total} documento(s) em uso pelo assistente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

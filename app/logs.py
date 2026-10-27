"""
Log estruturado (Etapa 1, Bloco 6 - item 1.9).

Uma linha JSON por execução em logs/execucoes.jsonl, com o mesmo
execucao_id da linha em uso_custos. Nunca derruba a conversa.
"""
import json
import os

PASTA_LOGS = "logs"
ARQUIVO_EXECUCOES = "execucoes.jsonl"


def caminho_execucoes() -> str:
    return os.path.join(PASTA_LOGS, ARQUIVO_EXECUCOES)


def registrar_execucao(dados: dict) -> bool:
    try:
        os.makedirs(PASTA_LOGS, exist_ok=True)
        linha = json.dumps(dados, ensure_ascii=False, default=str)
        with open(caminho_execucoes(), "a", encoding="utf-8") as arquivo:
            arquivo.write(linha + "\n")
        return True
    except Exception as erro:
        print(f"[Logs] Não consegui gravar o log: {erro!r}")
        return False


def ler_execucoes(limite: int = 50) -> list[dict]:
    """As últimas execuções do log (mais recente por último)."""
    try:
        with open(caminho_execucoes(), "r", encoding="utf-8") as arquivo:
            linhas = arquivo.readlines()[-limite:]
    except FileNotFoundError:
        return []
    saida = []
    for linha in linhas:
        try:
            saida.append(json.loads(linha))
        except ValueError:
            continue
    return saida

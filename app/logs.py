"""
Log estruturado (Etapa 1, Bloco 6 - item 1.9; P1 do Plano Mestre).

- logs/execucoes.jsonl: uma linha JSON por execução, com o mesmo
  execucao_id da linha em uso_custos.
- logs/mensagens_recusadas.jsonl: mensagem de canal sem cadastro (P1).
  No P6 isso passa a gravar também na tabela de Registro.
Nada aqui derruba a conversa.
"""
import json
import os
from datetime import datetime, timezone

PASTA_LOGS = "logs"
ARQUIVO_EXECUCOES = "execucoes.jsonl"
ARQUIVO_RECUSADAS = "mensagens_recusadas.jsonl"


def caminho_execucoes() -> str:
    return os.path.join(PASTA_LOGS, ARQUIVO_EXECUCOES)


def caminho_recusadas() -> str:
    return os.path.join(PASTA_LOGS, ARQUIVO_RECUSADAS)


def _gravar_linha(caminho: str, dados: dict) -> bool:
    try:
        os.makedirs(PASTA_LOGS, exist_ok=True)
        linha = json.dumps(dados, ensure_ascii=False, default=str)
        with open(caminho, "a", encoding="utf-8") as arquivo:
            arquivo.write(linha + "\n")
        return True
    except Exception as erro:
        print(f"[Logs] Não consegui gravar o log: {erro!r}")
        return False


def registrar_execucao(dados: dict) -> bool:
    return _gravar_linha(caminho_execucoes(), dados)


def registrar_canal_desconhecido(tipo_canal: str, id_externo) -> bool:
    """Mensagem chegou por um canal não cadastrado ou desativado: ignorada e anotada."""
    print(f"[{tipo_canal}] Canal {id_externo} não cadastrado ou desativado. Mensagem ignorada.")
    return _gravar_linha(caminho_recusadas(), {
        "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "evento": "canal_sem_cadastro",
        "tipo_canal": tipo_canal,
        "id_externo": str(id_externo or ""),
    })


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

"""
Log estruturado (Etapa 1, Bloco 6 - item 1.9; P1 do Plano Mestre).

- logs/execucoes.jsonl: uma linha JSON por execução, com o mesmo
  execucao_id da linha em uso_custos.
- logs/mensagens_recusadas.jsonl: mensagem de canal sem cadastro (P1).
  P6: isso grava também no Registro (registro_acoes), sem loja, com ator
  de sistema. Erro no Registro é engolido.
Nada aqui derruba a conversa.
"""
import json
import os
from datetime import datetime, timezone

PASTA_LOGS = "logs"
ARQUIVO_EXECUCOES = "execucoes.jsonl"
ARQUIVO_RECUSADAS = "mensagens_recusadas.jsonl"

# P6: quem aparece no Registro quando a mensagem chega por canal sem cadastro.
# Telegram e WhatsApp usam a mesma origem ('webhook'), como combinado.
NOME_SISTEMA = "Sistema"
ORIGEM_SISTEMA = "webhook"


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


def _anotar_no_registro(tipo_canal: str, id_externo) -> None:
    """P6: também vai para o Registro. Nunca derruba quem chamou."""
    try:
        from app.ator import como_sistema      # aqui dentro: evita import circular
        from app.registro import registrar
        id_texto = str(id_externo or "")
        with como_sistema(NOME_SISTEMA, ORIGEM_SISTEMA):
            registrar("mensagem_canal_sem_cadastro", None, None,
                      {"tipo_canal": tipo_canal, "id_externo": id_texto},
                      alvo=f"canal:{tipo_canal}:{id_texto}")
    except Exception as erro:
        print(f"[Logs] Não consegui gravar no Registro: {erro!r}")


def registrar_canal_desconhecido(tipo_canal: str, id_externo) -> bool:
    """Mensagem chegou por um canal não cadastrado ou desativado: ignorada e anotada."""
    print(f"[{tipo_canal}] Canal {id_externo} não cadastrado ou desativado. Mensagem ignorada.")
    gravou = _gravar_linha(caminho_recusadas(), {
        "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "evento": "canal_sem_cadastro",
        "tipo_canal": tipo_canal,
        "id_externo": str(id_externo or ""),
    })
    _anotar_no_registro(tipo_canal, id_externo)
    return gravou


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

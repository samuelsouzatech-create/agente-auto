"""
Resultado do lead (Fase 3 - Bloco 6).

Funções para o vendedor marcar como a conversa terminou: compareceu,
comprou ou perdeu — sempre com um motivo. Grava na tabela 'resultados'.
Separa a lógica de banco da tela, igual app/handoff.py e app/estoque.py.

No documento (seções 6.1 e 7): "resultado do lead marcado pelo vendedor
(compareceu, comprou, perdeu) + motivo", feito na tela de Leads/Conversas.
Serve de base pra revisão semanal (seção 7).
"""
from banco import conectar


# Opções fixas de resultado, pra o painel usar num select.
OPCOES_RESULTADO = ["compareceu", "comprou", "perdeu"]


def registrar_resultado(lead_id, resultado, motivo="", vendedor="", loja_id=1):
    """Grava o resultado marcado pelo vendedor. Cada marcação é uma linha
    nova (mantém o histórico; a última é a mais recente)."""
    conexao = conectar()
    cursor = conexao.cursor()
    cursor.execute(
        """
        INSERT INTO resultados (lead_id, loja_id, resultado, motivo, vendedor)
        VALUES (?, ?, ?, ?, ?)
        """,
        (lead_id, loja_id, resultado, motivo, vendedor),
    )
    conexao.commit()
    conexao.close()
    return f"Resultado '{resultado}' registrado para o lead {lead_id}."


def resultado_do_lead(lead_id, loja_id=1):
    """Retorna o resultado mais recente de um lead, ou None se não houver."""
    conexao = conectar()
    cursor = conexao.cursor()
    cursor.execute(
        """
        SELECT * FROM resultados
        WHERE lead_id = ? AND loja_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (lead_id, loja_id),
    )
    linha = cursor.fetchone()
    conexao.close()
    return dict(linha) if linha else None


def listar_resultados(loja_id=1):
    """Lista todos os resultados marcados (mais recentes primeiro).
    Base pra revisão semanal e, no futuro, métricas."""
    conexao = conectar()
    cursor = conexao.cursor()
    cursor.execute(
        """
        SELECT * FROM resultados
        WHERE loja_id = ?
        ORDER BY id DESC
        """,
        (loja_id,),
    )
    linhas = cursor.fetchall()
    conexao.close()
    return [dict(linha) for linha in linhas]

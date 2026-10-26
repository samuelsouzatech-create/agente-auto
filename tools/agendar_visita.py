from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg
from banco import conectar


@tool
def agendar_visita(nome_cliente: str, tipo: str, data_hora: str,
                   lead_id: Annotated[str, InjectedToolArg] = "",
                   loja_id: Annotated[int, InjectedToolArg] = 1) -> str:
    """Agenda uma visita, test-drive ou ligação com vendedor.
    Se o cliente já tiver um agendamento desse tipo, ATUALIZA o horário
    (o cliente pode remarcar). Não cria agendamentos duplicados.

    Parâmetros:
    - nome_cliente: nome de quem está agendando
    - tipo: "visita", "test-drive" ou "ligacao"
    - data_hora: data e hora combinadas (ex: "sábado 10h", "12/10 às 15h")
    """
    conexao = conectar()
    try:
        if lead_id:
            existente = conexao.execute(
                "SELECT id FROM agendamentos WHERE loja_id = ? AND lead_id = ? AND tipo = ?",
                (loja_id, lead_id, tipo),
            ).fetchone()
            if existente:
                conexao.execute(
                    "UPDATE agendamentos SET nome_cliente = ?, data_hora = ?, status = 'agendado' WHERE id = ?",
                    (nome_cliente, data_hora, existente["id"]),
                )
                conexao.commit()
                return f"Agendamento atualizado: {tipo} para {nome_cliente} em {data_hora}."

        conexao.execute(
            "INSERT INTO agendamentos (loja_id, lead_id, nome_cliente, tipo, data_hora) VALUES (?, ?, ?, ?, ?)",
            (loja_id, lead_id, nome_cliente, tipo, data_hora),
        )
        conexao.commit()
    finally:
        conexao.close()
    return f"Agendamento confirmado: {tipo} para {nome_cliente} em {data_hora}."

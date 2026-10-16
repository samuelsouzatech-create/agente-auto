from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg
from banco import conectar


@tool
def agendar_visita(nome_cliente: str, tipo: str, data_hora: str,
                  lead_id: Annotated[str, InjectedToolArg] = "") -> str:
    """Agenda uma visita, test-drive ou ligação com vendedor.
    Se o cliente já tiver um agendamento desse tipo, ATUALIZA o horário
    (o cliente pode remarcar). Não cria agendamentos duplicados.

    Parâmetros:
    - nome_cliente: nome de quem está agendando
    - tipo: "visita", "test-drive" ou "ligacao"
    - data_hora: data e hora combinadas (ex: "sábado 10h", "12/10 às 15h")
    """
    conexao = conectar()
    cursor = conexao.cursor()

    # Upsert por lead + tipo: um cliente tem UM agendamento de cada tipo.
    if lead_id:
        cursor.execute(
            "SELECT id FROM agendamentos WHERE lead_id = ? AND tipo = ?",
            (lead_id, tipo),
        )
        existente = cursor.fetchone()
        if existente:
            cursor.execute(
                "UPDATE agendamentos SET nome_cliente = ?, data_hora = ?, status = 'agendado' WHERE id = ?",
                (nome_cliente, data_hora, existente["id"]),
            )
            conexao.commit()
            conexao.close()
            return f"Agendamento atualizado: {tipo} para {nome_cliente} em {data_hora}."

    cursor.execute(
        "INSERT INTO agendamentos (lead_id, nome_cliente, tipo, data_hora) VALUES (?, ?, ?, ?)",
        (lead_id, nome_cliente, tipo, data_hora),
    )
    conexao.commit()
    conexao.close()
    return f"Agendamento confirmado: {tipo} para {nome_cliente} em {data_hora}."

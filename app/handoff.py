"""
Handoff: o Léo passa a conversa para um vendedor; o vendedor assume e devolve.

P6: assumir e devolver são ações de PESSOA e exigem o ator (app/ator.py).
Cada uma grava no Registro (registro_acoes) na MESMA transação da mudança no
handoff. Sem ator (ou ator de outra loja), nada muda.
Tentativa que não muda nada (já estava com você, já assumido por outro,
nada aberto) não grava.
O Léo abrir um handoff (tools/acionar_handoff.py) e o encerrar_handoff
ficam como estavam.
"""
from banco import conectar
from app.registro import conferir_ator, registrar


def _handoff_aberto(cursor, lead_id, loja_id):
    """Busca o handoff mais recente que ainda não foi encerrado."""
    cursor.execute(
        """
        SELECT * FROM handoffs
        WHERE lead_id = ? AND loja_id = ? AND estado != 'encerrado'
        ORDER BY id DESC
        LIMIT 1
        """,
        (lead_id, loja_id),
    )
    return cursor.fetchone()


def estado_do_handoff(lead_id, loja_id):
    """Estado atual do lead. Sem handoff aberto, o agente está ativo."""
    conexao = conectar()
    cursor = conexao.cursor()
    aberto = _handoff_aberto(cursor, lead_id, loja_id)
    conexao.close()
    if aberto is None:
        return "ativo"
    return aberto["estado"]


def quem_assumiu(lead_id, loja_id):
    """Nome do vendedor no comando, ou None."""
    conexao = conectar()
    cursor = conexao.cursor()
    aberto = _handoff_aberto(cursor, lead_id, loja_id)
    conexao.close()
    if aberto is None or aberto["estado"] != "humano_assumiu":
        return None
    return aberto["vendedor"]


def assumir_handoff(lead_id, vendedor, loja_id):
    """Um vendedor assume um lead que o Léo passou (estado 'aguardando_humano').

    Trava para dois vendedores: o UPDATE só vale se o lead ainda estiver
    'aguardando_humano'. Se outro vendedor já assumiu, devolve quem está no comando.
    """
    conferir_ator(loja_id)          # P6: sem autor (ou autor de outra loja), nada muda
    conexao = conectar()
    try:
        cursor = conexao.cursor()
        aberto = _handoff_aberto(cursor, lead_id, loja_id)
        if aberto is None:
            return "Nenhum handoff aberto para assumir."

        if aberto["estado"] == "humano_assumiu" and aberto["vendedor"] == vendedor:
            return f"Lead já estava com você, {vendedor}."

        cursor.execute(
            """
            UPDATE handoffs
            SET estado = 'humano_assumiu',
                vendedor = ?,
                assumido_em = CURRENT_TIMESTAMP
            WHERE id = ? AND estado = 'aguardando_humano'
            """,
            (vendedor, aberto["id"]),
        )

        if cursor.rowcount == 0:
            conexao.commit()
            atual = _handoff_aberto(cursor, lead_id, loja_id)
            dono = atual["vendedor"] if atual and atual["vendedor"] else "outro vendedor"
            return f"Lead já assumido por {dono}."

        registrar("assumir_atendimento", loja_id,
                  {"estado": aberto["estado"], "vendedor": aberto["vendedor"]},
                  {"estado": "humano_assumiu", "vendedor": vendedor, "handoff_id": aberto["id"]},
                  conexao=conexao, alvo=f"lead:{lead_id}")
        conexao.commit()
    finally:
        conexao.close()
    return f"Lead assumido por {vendedor}."


def assumir_conversa(lead_id, vendedor, loja_id):
    """Assumir a QUALQUER momento (Bloco 7A), mesmo sem o Léo ter chamado.

    - Léo já chamou alguém: vale a regra do assumir_handoff.
    - Outro vendedor no comando: não toma a conversa dele.
    - Nada aberto: abre um handoff já assumido (origem 'painel'). O
      avisado_em fica preenchido para o 7B não avisar ninguém à toa.
    """
    conferir_ator(loja_id)          # P6: sem autor (ou autor de outra loja), nada muda
    conexao = conectar()
    try:
        cursor = conexao.cursor()
        aberto = _handoff_aberto(cursor, lead_id, loja_id)
        if aberto is None:
            novo_id = cursor.execute(
                """
                INSERT INTO handoffs (loja_id, lead_id, motivo, resumo, estado, vendedor,
                                      assumido_em, avisado_em, origem)
                VALUES (?, ?, 'Assumido pelo painel', '', 'humano_assumiu', ?,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'painel')
                """,
                (loja_id, lead_id, vendedor),
            ).lastrowid
            registrar("assumir_conversa", loja_id,
                      {"estado": "ativo"},
                      {"estado": "humano_assumiu", "vendedor": vendedor, "handoff_id": novo_id},
                      conexao=conexao, alvo=f"lead:{lead_id}")
            conexao.commit()
            return f"Lead assumido por {vendedor}."
    finally:
        conexao.close()

    if aberto["estado"] == "humano_assumiu" and aberto["vendedor"] != vendedor:
        return f"Lead já assumido por {aberto['vendedor'] or 'outro vendedor'}."
    return assumir_handoff(lead_id, vendedor, loja_id)


def devolver_ao_agente(lead_id, loja_id):
    """Encerra o handoff atual para que o Léo volte a responder o lead."""
    conferir_ator(loja_id)          # P6: sem autor (ou autor de outra loja), nada muda
    conexao = conectar()
    try:
        cursor = conexao.cursor()
        aberto = _handoff_aberto(cursor, lead_id, loja_id)
        if aberto is None:
            return "Nenhum handoff aberto para devolver."
        cursor.execute(
            "UPDATE handoffs SET estado = 'encerrado', encerrado_em = CURRENT_TIMESTAMP WHERE id = ?",
            (aberto["id"],),
        )
        registrar("devolver_ao_agente", loja_id,
                  {"estado": aberto["estado"], "vendedor": aberto["vendedor"]},
                  {"estado": "encerrado", "handoff_id": aberto["id"]},
                  conexao=conexao, alvo=f"lead:{lead_id}")
        conexao.commit()
    finally:
        conexao.close()
    return "Lead devolvido ao agente."


def encerrar_handoff(lead_id, loja_id):
    """Mesmo efeito no banco que devolver_ao_agente (separado por semântica)."""
    conexao = conectar()
    cursor = conexao.cursor()
    aberto = _handoff_aberto(cursor, lead_id, loja_id)
    if aberto is None:
        conexao.close()
        return "Nenhum handoff aberto para encerrar."
    cursor.execute(
        "UPDATE handoffs SET estado = 'encerrado', encerrado_em = CURRENT_TIMESTAMP WHERE id = ?",
        (aberto["id"],),
    )
    conexao.commit()
    conexao.close()
    return "Handoff encerrado."


def listar_handoffs(loja_id, apenas_abertos=True):
    """Handoffs da loja. Por padrão, só os abertos (fila do vendedor)."""
    conexao = conectar()
    cursor = conexao.cursor()
    if apenas_abertos:
        cursor.execute(
            "SELECT * FROM handoffs WHERE loja_id = ? AND estado != 'encerrado' ORDER BY criado_em ASC",
            (loja_id,),
        )
    else:
        cursor.execute(
            "SELECT * FROM handoffs WHERE loja_id = ? ORDER BY criado_em DESC",
            (loja_id,),
        )
    linhas = cursor.fetchall()
    conexao.close()
    return [dict(linha) for linha in linhas]

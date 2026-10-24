from banco import conectar


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


def estado_do_handoff(lead_id, loja_id=1):
    """Retorna o estado atual do lead.
    Se não houver handoff aberto, considera que o agente está ativo."""
    conexao = conectar()
    cursor = conexao.cursor()
    aberto = _handoff_aberto(cursor, lead_id, loja_id)
    conexao.close()
    if aberto is None:
        return "ativo"
    return aberto["estado"]

def assumir_handoff(lead_id, vendedor, loja_id=1):
    """Um vendedor assume o lead: estado vira 'humano_assumiu',
    grava o nome do vendedor e o carimbo de tempo.

    Trava para dois vendedores: o UPDATE só vale se o lead ainda estiver
    'aguardando_humano'. Se outro vendedor já assumiu entre o clique e aqui,
    nenhuma linha muda e devolvemos quem já está no comando — sem sobrescrever.
    """
    conexao = conectar()
    cursor = conexao.cursor()
    aberto = _handoff_aberto(cursor, lead_id, loja_id)
    if aberto is None:
        conexao.close()
        return "Nenhum handoff aberto para assumir."

    # Se o MESMO vendedor clicar de novo num lead que ele já assumiu,
    # é inofensivo: não troca nada e não dá erro.
    if aberto["estado"] == "humano_assumiu" and aberto["vendedor"] == vendedor:
        conexao.close()
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

    # Se nenhuma linha mudou, é porque outro vendedor já tinha assumido.
    if cursor.rowcount == 0:
        conexao.commit()
        # Relê pra descobrir quem está no comando agora.
        atual = _handoff_aberto(cursor, lead_id, loja_id)
        conexao.close()
        dono = atual["vendedor"] if atual and atual["vendedor"] else "outro vendedor"
        return f"Lead já assumido por {dono}."

    conexao.commit()
    conexao.close()
    return f"Lead assumido por {vendedor}."


def devolver_ao_agente(lead_id, loja_id=1):
    """Encerra o handoff atual para que o Léo volte a responder o lead."""
    conexao = conectar()
    cursor = conexao.cursor()
    aberto = _handoff_aberto(cursor, lead_id, loja_id)
    if aberto is None:
        conexao.close()
        return "Nenhum handoff aberto para devolver."
    cursor.execute(
        """
        UPDATE handoffs
        SET estado = 'encerrado',
            encerrado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (aberto["id"],),
    )
    conexao.commit()
    conexao.close()
    return "Lead devolvido ao agente."


def encerrar_handoff(lead_id, loja_id=1):
    """Encerra o handoff (mesmo efeito no banco que devolver_ao_agente;
    mantido separado por semântica e futura métrica)."""
    conexao = conectar()
    cursor = conexao.cursor()
    aberto = _handoff_aberto(cursor, lead_id, loja_id)
    if aberto is None:
        conexao.close()
        return "Nenhum handoff aberto para encerrar."
    cursor.execute(
        """
        UPDATE handoffs
        SET estado = 'encerrado',
            encerrado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (aberto["id"],),
    )
    conexao.commit()
    conexao.close()
    return "Handoff encerrado."


def listar_handoffs(loja_id=1, apenas_abertos=True):
    """Lista os handoffs da loja. Por padrão, só os que ainda não
    foram encerrados (fila do vendedor)."""
    conexao = conectar()
    cursor = conexao.cursor()
    if apenas_abertos:
        cursor.execute(
            """
            SELECT * FROM handoffs
            WHERE loja_id = ? AND estado != 'encerrado'
            ORDER BY criado_em ASC
            """,
            (loja_id,),
        )
    else:
        cursor.execute(
            """
            SELECT * FROM handoffs
            WHERE loja_id = ?
            ORDER BY criado_em DESC
            """,
            (loja_id,),
        )
    linhas = cursor.fetchall()
    conexao.close()
    return [dict(linha) for linha in linhas]

from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg
from banco import conectar


@tool
def registrar_lead(nome: str, interesse: str, forma_pagamento: str = "",
                   tem_troca: str = "", prazo: str = "",
                   lead_id: Annotated[str, InjectedToolArg] = "") -> str:
    """Registra/atualiza os dados de qualificação do lead ao longo da conversa.
    Use quando tiver coletado informações relevantes do cliente. Pode ser
    chamada várias vezes na mesma conversa — os dados vão sendo completados.

    Parâmetros:
    - nome: nome do cliente
    - interesse: o que ele procura (modelo, faixa de preço)
    - forma_pagamento: "à vista" ou "financiado" (se souber)
    - tem_troca: "sim" ou "não" (se souber)
    - prazo: urgência/quando quer resolver (se souber)
    """
    if not lead_id:
        return "Não registrei o lead: falta o identificador da conversa."

    conexao = conectar()
    cursor = conexao.cursor()

    cursor.execute("SELECT id FROM leads WHERE lead_id = ?", (lead_id,))
    existente = cursor.fetchone()

    if existente:
        cursor.execute("""
            UPDATE leads SET
                nome = COALESCE(NULLIF(?, ''), nome),
                interesse = COALESCE(NULLIF(?, ''), interesse),
                forma_pagamento = COALESCE(NULLIF(?, ''), forma_pagamento),
                tem_troca = COALESCE(NULLIF(?, ''), tem_troca),
                prazo = COALESCE(NULLIF(?, ''), prazo),
                atualizado_em = CURRENT_TIMESTAMP
            WHERE lead_id = ?
        """, (nome, interesse, forma_pagamento, tem_troca, prazo, lead_id))
    else:
        cursor.execute("""
            INSERT INTO leads (lead_id, nome, interesse, forma_pagamento, tem_troca, prazo)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (lead_id, nome, interesse, forma_pagamento, tem_troca, prazo))

    conexao.commit()
    conexao.close()
    return f"Lead registrado/atualizado: {nome} — {interesse}."

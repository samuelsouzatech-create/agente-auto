from typing import Annotated
from langchain_core.tools import tool, InjectedToolArg
from banco import conectar
import re


_DIA_FALADO = re.compile(r"\b(hoje|amanha|segunda|terca|quarta|quinta|sexta|sabado|domingo)\b")


def prazo_com_data(prazo, loja_id):
    """H15: 'quer visitar amanhã às 10h' vira 'quer visitar amanhã às 10h (terça-feira, 17/11)'.
    Usa o mesmo entender_dia do agendar_visita. Na dúvida, fica como veio."""
    texto = (prazo or "").strip()
    if not texto or "(" in texto:
        return prazo
    try:
        from app import relogio
        from app.lojas import carregar_loja
        from tools.agendar_visita import _normal, entender_dia
        if not _DIA_FALADO.search(_normal(texto)):
            return prazo
        loja = carregar_loja(loja_id)
        agora = relogio.hora_local(loja, relogio.agora_utc())
        dia, duvida = entender_dia(texto, agora)
    except Exception:
        return prazo
    if dia is None or duvida:
        return prazo
    return f"{texto} ({relogio.DIAS_COMPLETOS[dia.weekday()]}, {dia:%d/%m})"


@tool
def registrar_lead(nome: str, interesse: str, forma_pagamento: str = "",
                   tem_troca: str = "", prazo: str = "",
                   lead_id: Annotated[str, InjectedToolArg] = "",
                   *, loja_id: Annotated[int, InjectedToolArg]) -> str:
    """Registra/atualiza os dados de qualificação do lead ao longo da conversa.
    Use quando tiver coletado informações relevantes do cliente. Pode ser
    chamada várias vezes na mesma conversa - os dados vão sendo completados.

    Parâmetros:
    - nome: nome do cliente
    - interesse: o que ele procura (modelo, faixa de preço)
    - forma_pagamento: "à vista" ou "financiado" (se souber)
    - tem_troca: "sim" ou "não" (se souber)
    - prazo: urgência/quando quer resolver (se souber). Se ele quer visitar a
      loja, escreva a intenção com as palavras dele (ex.: "quer visitar sábado")
    """
    if not lead_id:
        return "Não registrei o lead: falta o identificador da conversa."

    prazo = prazo_com_data(prazo, loja_id)
    conexao = conectar()
    try:
        existente = conexao.execute(
            "SELECT id FROM leads WHERE loja_id = ? AND lead_id = ?", (loja_id, lead_id)
        ).fetchone()
        if existente:
            conexao.execute("""
                UPDATE leads SET
                    nome = COALESCE(NULLIF(?, ''), nome),
                    interesse = COALESCE(NULLIF(?, ''), interesse),
                    forma_pagamento = COALESCE(NULLIF(?, ''), forma_pagamento),
                    tem_troca = COALESCE(NULLIF(?, ''), tem_troca),
                    prazo = COALESCE(NULLIF(?, ''), prazo),
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (nome, interesse, forma_pagamento, tem_troca, prazo, existente["id"]))
        else:
            conexao.execute("""
                INSERT INTO leads (loja_id, lead_id, nome, interesse, forma_pagamento, tem_troca, prazo)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (loja_id, lead_id, nome, interesse, forma_pagamento, tem_troca, prazo))
        conexao.commit()
    finally:
        conexao.close()
    return f"Lead registrado/atualizado: {nome} - {interesse}."

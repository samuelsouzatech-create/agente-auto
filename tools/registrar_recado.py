"""L3/L4: ferramenta do MODO EQUIPE (só dono ou gestor). Nunca aparece para cliente."""
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from app.lojas import carregar_loja
from app.recados import RecadoInvalido, confirmacao, registrar_recado as gravar
from app.relogio import agora_utc, dia_local


@tool
def registrar_recado(texto: str, valido_ate: str = "", *,
                     loja_id: Annotated[int, InjectedToolArg],
                     autor: Annotated[str, InjectedToolArg] = "") -> str:
    """Anota um recado do dono ou gestor para comentar com os clientes.

    Parâmetros:
    - texto: o recado, curto, nas palavras de quem mandou
    - valido_ate: último dia do recado (AAAA-MM-DD) se ele disse; vazio se não disse
    """
    hoje = dia_local(carregar_loja(loja_id), agora_utc())
    try:
        recado = gravar(loja_id, autor, texto, valido_ate, hoje=hoje)
    except RecadoInvalido as erro:
        return f"Erro: {erro}. Pergunte a quem mandou e não diga que anotou."
    return confirmacao(recado)

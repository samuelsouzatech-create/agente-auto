"""Peças compartilhadas pelas páginas dos DOIS painéis.

Quem decide a loja é a ENTRADA, a cada rerun, antes de a página rodar:
  painel.py   (cliente)  -> loja fixa, vinda de LOJA_ID. Sem seletor.
  operador.py (operador) -> seletor de loja (paginas/operador_sessao.py).

Este arquivo NÃO importa nada do operador (custos, preços, lojas_admin,
canais). Um teste confere isso.
"""
import streamlit as st

PAPEL_CLIENTE = "cliente"
PAPEL_OPERADOR = "operador"


def para_streamlit(texto):
    """Escapa o '$' para não virar fórmula LaTeX no Streamlit."""
    return (texto or "").replace("$", "\\$")


def formatar_brl(valor):
    try:
        return "R$ " + f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "R$ —"


# ------------------------------------------------------------ sessão
def iniciar_sessao_cliente(loja_id: int) -> None:
    """Painel do cliente: papel e loja vêm da ENTRADA (LOJA_ID), nunca da tela."""
    st.session_state["_papel"] = PAPEL_CLIENTE
    st.session_state["_loja_cliente"] = int(loja_id)


def iniciar_sessao_operador() -> None:
    st.session_state["_papel"] = PAPEL_OPERADOR


def papel_atual() -> str:
    """Na dúvida, cliente (o papel com menos poder)."""
    return PAPEL_OPERADOR if st.session_state.get("_papel") == PAPEL_OPERADOR else PAPEL_CLIENTE


def loja_atual() -> int:
    if papel_atual() == PAPEL_CLIENTE:
        loja = st.session_state.get("_loja_cliente")
        if loja is None:
            st.error("🔒 Loja não definida. Abra pelo painel.py com LOJA_ID.")
            st.stop()
        return loja
    return st.session_state["loja_id"]


def exigir_operador() -> None:
    """Primeira linha de toda tela do operador (defesa extra, além do menu)."""
    if papel_atual() != PAPEL_OPERADOR:
        st.error("🔒 Esta tela é só do operador.")
        st.stop()


def campo_nome(padrao: str) -> None:
    st.sidebar.text_input("Seu nome", value=padrao, key="usuario_nome")


def usuario_atual() -> str:
    padrao = "Operador" if papel_atual() == PAPEL_OPERADOR else "Vendedor"
    return (st.session_state.get("usuario_nome") or "").strip() or padrao


def trocar_loja(loja_id: int) -> None:
    """Pede a troca de loja (vale no próximo rerun). Só tem efeito no operador."""
    st.session_state["_trocar_para_loja"] = loja_id


# ------------------------------------------------------------ avisos
def avisar(mensagem: str, tipo: str = "success") -> None:
    """Guarda um aviso para mostrar depois do st.rerun()."""
    st.session_state["_aviso"] = (tipo, mensagem)


def mostrar_aviso() -> None:
    aviso = st.session_state.pop("_aviso", None)
    if aviso:
        getattr(st, aviso[0])(aviso[1])

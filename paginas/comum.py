"""Peças compartilhadas pelas páginas do painel."""
import streamlit as st

from app.lojas_admin import listar_lojas


def para_streamlit(texto):
    """Escapa o '$' para não virar fórmula LaTeX no Streamlit."""
    return (texto or "").replace("$", "\\$")


def formatar_brl(valor):
    try:
        return "R$ " + f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "R$ —"


def escolher_loja():
    """Seletor de loja e nome de quem está usando, na barra lateral."""
    lojas = listar_lojas()
    if not lojas:
        st.error('Nenhuma loja cadastrada. Rode: python -c "import banco; banco.criar_tabelas()"')
        st.stop()
    rotulos = {l["id"]: f'{l["nome"]} (id {l["id"]})' for l in lojas}

    pedida = st.session_state.pop("_trocar_para_loja", None)
    if pedida in rotulos:
        st.session_state["loja_id"] = pedida
    if st.session_state.get("loja_id") not in rotulos:
        st.session_state["loja_id"] = next(iter(rotulos))

    st.sidebar.selectbox("Loja", list(rotulos), format_func=rotulos.get, key="loja_id")
    st.sidebar.text_input("Seu nome", value="Operador", key="usuario_nome")
    st.sidebar.caption("Login de verdade chega na Etapa 5. Por enquanto, "
                       "quem abre o painel vê todas as lojas.")


def loja_atual() -> int:
    return st.session_state["loja_id"]


def usuario_atual() -> str:
    return (st.session_state.get("usuario_nome") or "").strip() or "Operador"


def trocar_loja(loja_id: int) -> None:
    """Pede a troca de loja (vale no próximo rerun)."""
    st.session_state["_trocar_para_loja"] = loja_id


def avisar(mensagem: str, tipo: str = "success") -> None:
    """Guarda um aviso para mostrar depois do st.rerun()."""
    st.session_state["_aviso"] = (tipo, mensagem)


def mostrar_aviso() -> None:
    aviso = st.session_state.pop("_aviso", None)
    if aviso:
        getattr(st, aviso[0])(aviso[1])

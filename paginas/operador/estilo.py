"""Visual do painel do operador (S10b): cartões, bordas e selos.

Aplicado UMA vez, pelo operador.py (decisão 7A). O painel do cliente
(painel.py) e as telas dele NÃO importam este arquivo (um teste confere).
Selos: st.badge do Streamlit (decisão 9A). Ele existe a partir da versão
1.44; o requirements.txt fixa a 1.65.0 e um teste confere que a versão
instalada é a mesma.
"""
import streamlit as st

from paginas.comum import exigir_operador

CSS = """
<style>
/* Cartões: os números das telas (métricas) */
div[data-testid="stMetric"] {
    border: 1px solid rgba(128, 128, 128, 0.25);
    border-radius: 0.75rem;
    padding: 0.75rem 1rem;
    background-color: rgba(128, 128, 128, 0.06);
}
/* Bordas: tabelas */
div[data-testid="stDataFrame"] {
    border: 1px solid rgba(128, 128, 128, 0.20);
    border-radius: 0.5rem;
}
/* Bordas: caixas que abrem e fecham, e formulários */
div[data-testid="stExpander"] details,
div[data-testid="stForm"] {
    border-radius: 0.75rem;
}
</style>
"""

# Selos dos tipos de mensagem automática (chaves iguais a app/painel_envios.TIPOS).
ROTULO_SELO = {"remarketing": "Retomada", "pos_venda": "Pós-venda", "reativacao": "Reativação"}
COR_SELO = {"remarketing": "blue", "pos_venda": "green", "reativacao": "orange"}


def aplicar_estilo() -> None:
    """Chamada uma vez pelo operador.py, a cada execução, antes das telas."""
    exigir_operador()
    st.markdown(CSS, unsafe_allow_html=True)


def textos_dos_selos(tipos) -> list[tuple[str, str]]:
    """Conta por tipo: ['remarketing', 'pos_venda', 'remarketing'] vira
    [('Retomada · 2', 'blue'), ('Pós-venda · 1', 'green')]."""
    contagem = {}
    for tipo in tipos:
        contagem[tipo] = contagem.get(tipo, 0) + 1
    ordem = ([t for t in ROTULO_SELO if t in contagem]
             + [t for t in contagem if t not in ROTULO_SELO])
    return [(f"{ROTULO_SELO.get(t, t)} · {contagem[t]}", COR_SELO.get(t, "gray")) for t in ordem]


def mostrar_selos(tipos) -> None:
    """Uma fileira de selos, um por tipo, com a quantidade."""
    selos = textos_dos_selos(tipos)
    if not selos:
        return
    colunas = st.columns([1] * len(selos) + [max(1, 6 - len(selos))])
    for coluna, (texto, cor) in zip(colunas, selos):
        coluna.badge(texto, color=cor)

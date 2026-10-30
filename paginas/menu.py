"""Quais telas cada painel mostra. Uma lista só, usada pelas duas entradas."""
import streamlit as st

# (arquivo, título, ícone)
CLIENTE = {
    "Atendimento": [
        ("paginas/handoff.py", "Fila de handoff", "🧑‍💼"),
        ("paginas/conversas.py", "Conversas", "💬"),
        ("paginas/resultados.py", "Resultados", "📊"),
        ("paginas/envios.py", "Retomadas e pós-venda", "📣"),
    ],
    "Loja": [
        ("paginas/estoque.py", "Estoque", "🚗"),
        ("paginas/configuracao.py", "Configuração", "⚙️"),
        ("paginas/conhecimento.py", "Conhecimento", "📚"),
        ("paginas/usuarios.py", "Usuários", "👥"),
    ],
}

OPERADOR = {
    "Operador": [
        ("paginas/lojas_canais.py", "Lojas e canais", "🏬"),
        ("paginas/plano.py", "Plano e limites", "📦"),
        ("paginas/custos.py", "Custos", "💰"),
        ("paginas/importar_base.py", "Importar base", "📥"),
    ],
}


def arquivos(grupos: dict) -> list[str]:
    return [arquivo for itens in grupos.values() for arquivo, _, _ in itens]


def montar(grupos: dict, prefixo: str = "", com_padrao: bool = True) -> dict:
    """Vira o dicionário que o st.navigation espera. Só a 1ª página é a padrão."""
    paginas, primeira = {}, com_padrao
    for grupo, itens in grupos.items():
        lista = []
        for arquivo, titulo, icone in itens:
            lista.append(st.Page(arquivo, title=titulo, icon=icone, default=primeira))
            primeira = False
        paginas[f"{prefixo}{grupo}"] = lista
    return paginas

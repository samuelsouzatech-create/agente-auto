"""Quais telas cada painel mostra. Uma lista só, usada pelas duas entradas.

CLIENTE:  as 8 telas do painel do cliente (painel.py).
OPERADOR: as 4 telas antigas só do operador.
GERAL e LOJA (S1 da Fase 3): o painel novo do operador, em dois níveis.
No operador, OPERADOR + CLIENTE formam o grupo "Antigas (serão removidas)",
que sai no S10.

Este arquivo só monta a navegação: NÃO importa nada de paginas/operador/
(um teste confere).
"""
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

# Painel novo do operador: (arquivo, título, ícone, endereço).
# O endereço é próprio porque, sem ele, paginas/operador/configuracao.py
# pegaria o mesmo endereço da tela antiga paginas/configuracao.py.
GERAL = {
    "Geral": [
        ("paginas/operador/visao_geral.py", "Visão geral", "🌐", "visao-geral"),
        ("paginas/operador/custos_precos.py", "Custos e preços", "💰", "custos-e-precos"),
    ],
}

LOJA = {
    "Loja": [
        ("paginas/operador/resumo.py", "Resumo", "🏁", "resumo"),
        ("paginas/operador/ver_como.py", "Ver como a loja", "👀", "ver-como-a-loja"),
        ("paginas/operador/configuracao.py", "Configuração", "⚙️", "configuracao-da-loja"),
        ("paginas/operador/mensagens_automaticas.py", "Mensagens automáticas", "📨",
         "mensagens-automaticas"),
        ("paginas/operador/base_clientes.py", "Base de clientes", "📇", "base-de-clientes"),
        ("paginas/operador/registro.py", "Registro", "📜", "registro"),
    ],
}

GRUPO_ANTIGAS = "Antigas (serão removidas)"

# Tela que abre primeiro: a Visão geral, desde o S9 (decisão 11A).
PAGINA_INICIAL = "paginas/operador/visao_geral.py"


def arquivos(grupos: dict) -> list[str]:
    return [item[0] for itens in grupos.values() for item in itens]


def _pagina(item: tuple, padrao: bool):
    """Uma página do st.navigation. A página padrão fica na raiz, sem endereço."""
    arquivo, titulo, icone = item[:3]
    if len(item) > 3 and not padrao:
        return st.Page(arquivo, title=titulo, icon=icone, url_path=item[3], default=False)
    return st.Page(arquivo, title=titulo, icon=icone, default=padrao)


def montar(grupos: dict, prefixo: str = "", com_padrao: bool = True) -> dict:
    """Vira o dicionário que o st.navigation espera. Só a 1ª página é a padrão."""
    paginas, primeira = {}, com_padrao
    for grupo, itens in grupos.items():
        lista = []
        for item in itens:
            lista.append(_pagina(item, primeira))
            primeira = False
        paginas[f"{prefixo}{grupo}"] = lista
    return paginas


def montar_operador() -> dict:
    """Painel do operador: Geral, Loja e o grupo das telas antigas."""
    antigas = [item for grupos in (OPERADOR, CLIENTE)
               for itens in grupos.values() for item in itens]
    grupos = {**GERAL, **LOJA, GRUPO_ANTIGAS: antigas}
    return {grupo: [_pagina(item, item[0] == PAGINA_INICIAL) for item in itens]
            for grupo, itens in grupos.items()}

"""
S1 (Fase 3): esqueleto do painel do operador em dois níveis.
Sem rede. As telas novas são abertas com o AppTest do Streamlit.
"""
import ast
import py_compile
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import paginas.menu as menu
from paginas.menu import (
    CLIENTE, GERAL, LOJA, OPERADOR, PAGINA_INICIAL, arquivos,
)

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "paginas" / "operador"
ARQUIVOS_DA_PASTA = sorted(p.relative_to(RAIZ).as_posix()
                           for p in PASTA.glob("*.py") if p.name != "__init__.py")
TELAS_DO_MENU = arquivos(GERAL) + arquivos(LOJA)
NOVA_LOJA = "paginas/operador/nova_loja.py"


class PaginaFalsa:
    """Troca o st.Page para ver o que o menu montaria, sem o Streamlit rodando."""

    def __init__(self, arquivo, **opcoes):
        self.arquivo, self.opcoes = arquivo, opcoes


def _imports(caminho: Path) -> set[str]:
    nomes = set()
    for no in ast.walk(ast.parse(caminho.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            nomes |= {a.name for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes.add(no.module)
            nomes |= {f"{no.module}.{a.name}" for a in no.names}
    return nomes


# ============================================ menu
def test_dois_niveis_com_as_8_telas():
    assert list(GERAL) == ["Geral"] and list(LOJA) == ["Loja"]
    assert [i[1] for i in GERAL["Geral"]] == ["Visão geral", "Custos e preços"]
    assert [i[1] for i in LOJA["Loja"]] == [
        "Resumo", "Ver como a loja", "Configuração", "Mensagens automáticas",
        "Base de clientes", "Registro"]


def test_telas_novas_ficam_na_pasta_do_operador():
    for arquivo in TELAS_DO_MENU + [NOVA_LOJA]:
        assert arquivo.startswith("paginas/operador/")
        assert (RAIZ / arquivo).is_file(), arquivo


def test_nova_loja_e_janela_e_nao_pagina_do_menu():
    assert NOVA_LOJA not in TELAS_DO_MENU


def test_menu_novo_nao_repete_tela_antiga():
    assert not set(TELAS_DO_MENU) & set(arquivos(CLIENTE) + arquivos(OPERADOR))


def test_enderecos_nao_se_repetem():
    enderecos = [i[3] if len(i) > 3 else Path(i[0]).stem
                 for grupos in (GERAL, LOJA, OPERADOR, CLIENTE)
                 for itens in grupos.values() for i in itens]
    assert len(enderecos) == len(set(enderecos))


def test_tela_inicial_e_a_visao_geral():
    # S9 (decisão 11A): a tela inicial passou do Resumo para a Visão geral.
    assert PAGINA_INICIAL == "paginas/operador/visao_geral.py"
    assert PAGINA_INICIAL in arquivos(GERAL)


def test_montar_operador_tem_so_geral_e_loja(monkeypatch):
    """S10b: o grupo das telas antigas saiu; nenhuma tela do cliente no operador."""
    monkeypatch.setattr(menu.st, "Page", PaginaFalsa)
    paginas = menu.montar_operador()
    assert list(paginas) == ["Geral", "Loja"]
    assert not hasattr(menu, "GRUPO_ANTIGAS")
    assert [p.arquivo for lista in paginas.values() for p in lista] == TELAS_DO_MENU
    padroes = [p.arquivo for lista in paginas.values() for p in lista if p.opcoes["default"]]
    assert padroes == [PAGINA_INICIAL]
    for p in paginas["Geral"] + paginas["Loja"]:
        if p.arquivo != PAGINA_INICIAL:
            assert p.opcoes.get("url_path"), p.arquivo


def test_montar_do_cliente_continua_igual(monkeypatch):
    monkeypatch.setattr(menu.st, "Page", PaginaFalsa)
    paginas = [p for lista in menu.montar(CLIENTE).values() for p in lista]
    assert [p.arquivo for p in paginas] == arquivos(CLIENTE)
    assert [p.opcoes["default"] for p in paginas] == [True] + [False] * (len(paginas) - 1)
    assert all("url_path" not in p.opcoes for p in paginas)


# ============================================ arquivos
@pytest.mark.parametrize("arquivo", ARQUIVOS_DA_PASTA)
def test_tela_nova_se_protege(arquivo):
    assert "exigir_operador()" in (RAIZ / arquivo).read_text(encoding="utf-8")


@pytest.mark.parametrize("arquivo", ARQUIVOS_DA_PASTA + ["operador.py", "paginas/menu.py"])
def test_compila(arquivo):
    py_compile.compile(str(RAIZ / arquivo), doraise=True)


def test_nao_existe_campo_seu_nome():
    for arquivo in ARQUIVOS_DA_PASTA + ["operador.py", "paginas/menu.py"]:
        assert "seu nome" not in (RAIZ / arquivo).read_text(encoding="utf-8").lower(), arquivo


def test_nova_loja_cria_pela_camada_app():
    """S2: a janela cria a loja só por app.lojas_admin.criar_loja (regra em app/)."""
    fonte = (RAIZ / NOVA_LOJA).read_text(encoding="utf-8")
    assert "criar_loja(" in fonte
    usados = _imports(RAIZ / NOVA_LOJA)
    assert "app.lojas_admin.criar_loja" in usados
    assert not {n for n in usados if n.split(".")[0] in ("banco", "sqlite3")}, usados


def test_entrada_do_operador():
    fonte = (RAIZ / "operador.py").read_text(encoding="utf-8")
    assert "montar_operador()" in fonte and "escolher_loja()" in fonte
    assert "abrir_nova_loja()" in fonte
    assert fonte.index("definir_ator_da_sessao()") < fonte.index("navegacao.run()")


def test_painel_do_cliente_nao_ve_o_painel_novo():
    fonte = (RAIZ / "painel.py").read_text(encoding="utf-8")
    assert "montar_operador" not in fonte and "paginas.operador" not in fonte


# ============================================ as telas abrem
@pytest.mark.parametrize("arquivo", TELAS_DO_MENU)
def test_tela_abre_sem_erro_para_o_operador(arquivo):
    at = AppTest.from_file(str(RAIZ / arquivo), default_timeout=30)
    at.session_state["_papel"] = "operador"
    at.session_state["loja_id"] = 1
    at.run()
    assert not at.exception, at.exception
    assert len(at.title) == 1


@pytest.mark.parametrize("arquivo", TELAS_DO_MENU)
def test_tela_recusa_quem_nao_e_operador(arquivo):
    at = AppTest.from_file(str(RAIZ / arquivo), default_timeout=30)
    at.run()
    assert not at.exception
    assert any("só do operador" in e.value for e in at.error)
    assert len(at.title) == 0

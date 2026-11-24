"""S10b: limpeza das telas antigas, migração 14, visual e paginação.
Prova pedida pelo analista: o painel do cliente (painel.py) continua abrindo
e todas as telas dele existem. Tudo offline, banco temporário do conftest.
O banco é sempre fechado no fim (no Windows, banco aberto não pode ser apagado)."""
import re
from contextlib import closing
from pathlib import Path

import streamlit
from streamlit.testing.v1 import AppTest

from app.paginacao import pagina_de, texto_da_pagina
from banco import conectar
from paginas.menu import CLIENTE, OPERADOR, arquivos

RAIZ = Path(__file__).resolve().parent.parent
REMOVIDAS = ["paginas/lojas_canais.py", "paginas/plano.py",
             "paginas/custos.py", "paginas/importar_base.py"]


def test_telas_antigas_sairam():
    for arq in REMOVIDAS:
        assert not (RAIZ / arq).exists(), arq
    assert OPERADOR == {}


def test_painel_do_cliente_tem_todas_as_telas():
    texto = (RAIZ / "painel.py").read_text(encoding="utf-8")
    assert "CLIENTE" in texto
    for arq in arquivos(CLIENTE):
        assert (RAIZ / arq).exists(), arq
        assert arq not in REMOVIDAS
    assert "paginas/envios.py" in arquivos(CLIENTE)


def test_painel_do_cliente_abre(monkeypatch):
    monkeypatch.setenv("LOJA_ID", "1")
    at = AppTest.from_file(str(RAIZ / "painel.py"), default_timeout=60).run()
    assert not at.exception


def test_cliente_nao_usa_estilo_do_operador():
    for arq in ["painel.py"] + arquivos(CLIENTE):
        texto = (RAIZ / arq).read_text(encoding="utf-8")
        assert "estilo" not in texto, arq
    assert "aplicar_estilo()" in (RAIZ / "operador.py").read_text(encoding="utf-8")


def test_versao_do_streamlit_igual_ao_requirements():
    req = (RAIZ / "requirements.txt").read_text(encoding="utf-8")
    pedida = re.search(r"^streamlit==([\d.]+)", req, re.M).group(1)
    assert streamlit.__version__ == pedida


def _plano(sql, args=()):
    # PG1: no PostgreSQL, tabela vazia é lida inteira (mais barato). Desligar a leitura inteira
    # nesta conexão mostra se o índice SERVE para a consulta, que é o que a decisão 3A pede.
    with closing(conectar()) as c:
        c.execute("SET LOCAL enable_seqscan = off")
        linhas = c.execute("EXPLAIN " + sql, args).fetchall()
    return " ".join(str(tuple(r)) for r in linhas)


def test_excecoes_usam_o_indice():
    """Decisão 3A: se isto falhar, as duas exceções saem da migração."""
    assert "idx_mensagens_direcao_canal" in _plano(
        "SELECT canal, MAX(criado_em) FROM mensagens WHERE direcao = ? GROUP BY canal", ("x",))
    assert "idx_custos_data" in _plano(
        "SELECT AVG(latencia_ms) FROM uso_custos WHERE criado_em >= ?", ("2026-01-01",))


def test_paginacao():
    p = pagina_de(range(320), 2)
    assert p["paginas"] == 7 and p["itens"][0] == 50
    assert texto_da_pagina(p) == "página 2 de 7 · 51 a 100 de 320"
    assert pagina_de(range(10), 99)["pagina"] == 1
    assert pagina_de([], 1)["de"] == 0

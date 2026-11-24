"""S10b: limpeza das telas antigas, migração 14, visual e paginação.
AR (Maratona 4): o painel Streamlit do cliente (painel.py) foi aposentado. Tudo offline, banco temporário do conftest.
O banco é sempre fechado no fim (no Windows, banco aberto não pode ser apagado)."""
import re
from contextlib import closing
from pathlib import Path

import streamlit

from app.paginacao import pagina_de, texto_da_pagina
from banco import conectar
from paginas.menu import OPERADOR

RAIZ = Path(__file__).resolve().parent.parent
REMOVIDAS = ["paginas/lojas_canais.py", "paginas/plano.py",
             "paginas/custos.py", "paginas/importar_base.py"]


def test_telas_antigas_sairam():
    for arq in REMOVIDAS:
        assert not (RAIZ / arq).exists(), arq
    assert OPERADOR == {}


APOSENTADAS_NO_AR = ["painel.py", "app/acesso.py", "paginas/handoff.py", "paginas/conversas.py",
                     "paginas/resultados.py", "paginas/envios.py", "paginas/estoque.py",
                     "paginas/configuracao.py", "paginas/conhecimento.py", "paginas/usuarios.py"]


def test_painel_do_cliente_aposentado():
    """AR: o painel Streamlit do cliente saiu (D11: no piloto o operador faz Configuração,
    Conhecimento e Equipe pelo lojista)."""
    for arq in APOSENTADAS_NO_AR:
        assert not (RAIZ / arq).exists(), arq


def test_operador_nao_usa_nada_do_painel_aposentado():
    textos = [(RAIZ / "operador.py").read_text(encoding="utf-8")]
    textos += [p.read_text(encoding="utf-8") for p in (RAIZ / "paginas").rglob("*.py")]
    for arq in APOSENTADAS_NO_AR:
        modulo = arq[:-3].replace("/", ".")
        for texto in textos:
            assert f'"{arq}"' not in texto and f"'{arq}'" not in texto, arq   # st.Page("...")
            assert not re.search(rf"import {re.escape(modulo)}(?!_)|from {re.escape(modulo)} ", texto), arq


def test_operador_continua_com_estilo():
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


def _indices_aceitos_de_mensagens() -> set[str]:
    """O índice da exceção (direcao, canal) ou QUALQUER índice de mensagens que comece por
    loja_id. AR (Maratona 4): o PostgreSQL às vezes escolhe outro índice que também serve
    (ex.: idx_mensagens_loja_direcao), conforme as estatísticas do banco naquela hora; o teste
    falhava de vez em quando sem nada estar errado."""
    with closing(conectar()) as c:
        linhas = c.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'mensagens'").fetchall()
    aceitos = {"idx_mensagens_direcao_canal"}
    for linha in linhas:
        nome, definicao = linha[0], linha[1]
        colunas = definicao.split("(", 1)[1]
        if colunas.replace(" ", "").startswith("loja_id"):
            aceitos.add(nome)
    return aceitos


def test_excecoes_usam_o_indice():
    """Decisão 3A: se isto falhar, as duas exceções saem da migração."""
    aceitos = _indices_aceitos_de_mensagens()
    assert {"idx_mensagens_loja", "idx_mensagens_loja_direcao"} <= aceitos
    plano = _plano("SELECT canal, MAX(criado_em) FROM mensagens WHERE direcao = ? GROUP BY canal", ("x",))
    assert any(nome in plano for nome in aceitos), plano
    assert "idx_custos_data" in _plano(
        "SELECT AVG(latencia_ms) FROM uso_custos WHERE criado_em >= ?", ("2026-01-01",))


def test_paginacao():
    p = pagina_de(range(320), 2)
    assert p["paginas"] == 7 and p["itens"][0] == 50
    assert texto_da_pagina(p) == "página 2 de 7 · 51 a 100 de 320"
    assert pagina_de(range(10), 99)["pagina"] == 1
    assert pagina_de([], 1)["de"] == 0

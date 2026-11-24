"""
PG2 (Maratona Postgres): scripts/importar_sqlite.py copia o loja.db para o PostgreSQL.

Testado com um loja.db FICTÍCIO (montado aqui com o esquema da v20 do SQLite):
- ensaio só conta e não grava; a importação traz todas as linhas com os mesmos ids;
- rodar duas vezes não duplica; o próximo id continua depois do maior;
- contagem diferente (o PostgreSQL já tinha outros dados) para com erro e não grava NADA;
- versão errada ou coluna que não existe no PostgreSQL: recusa antes de gravar.
"""
import sqlite3
from pathlib import Path

import pytest

import banco
from scripts import importar_sqlite as imp

ESQUEMA = Path(__file__).resolve().parent / "dados" / "esquema_sqlite_v20.sql"


@pytest.fixture
def loja_db(tmp_path) -> Path:
    caminho = tmp_path / "loja.db"
    c = sqlite3.connect(caminho)
    c.executescript(ESQUEMA.read_text(encoding="utf-8"))
    c.executescript("""
        INSERT INTO lojas (id, nome, segmento, config) VALUES (1, 'Seminovos Teste', 'veiculos', '{"tom": "leve"}');
        INSERT INTO lojas (id, nome, segmento, config) VALUES (3, 'Loja Três', 'veiculos', '{}');
        INSERT INTO estado_lojas (loja_id, estado, no_ar_em, alterado_por) VALUES (1, 'no_ar', '2026-01-01 10:00:00', 'Sistema');
        INSERT INTO estado_lojas (loja_id, estado) VALUES (3, 'em_teste');
        INSERT INTO estoque (id, loja_id, marca, modelo, ano, km, cor, cambio, preco, status, fotos)
            VALUES (7, 1, 'Fiat', 'Doblò', 2016, 110000, 'Prata', 'Manual', 52000.5, 'disponivel', '');
        INSERT INTO estoque (id, loja_id, marca, modelo, ano, km, cor, cambio, preco)
            VALUES (9, 3, 'Honda', 'Civic', 2019, 48000, 'Branco', 'Automático', 98000);
        INSERT INTO leads (id, lead_id, loja_id, nome, criado_em) VALUES (1, '5581999998888', 1, 'Ana Conceição', '2026-02-03 12:00:00');
        INSERT INTO leads (id, lead_id, loja_id, nome) VALUES (2, '5581999998888', 3, NULL);
        INSERT INTO mensagens (id, lead_id, loja_id, canal, direcao, tipo, conteudo, autor, criado_em)
            VALUES (1, '5581999998888', 1, 'whatsapp', 'cliente', 'texto', 'Oi, o Doblò ainda está aí?', NULL, '2026-02-03 12:00:00');
        INSERT INTO mensagens (id, lead_id, loja_id, canal, direcao, tipo, conteudo, autor, criado_em)
            VALUES (5, '5581999998888', 1, 'whatsapp', 'leo', 'texto', 'Está sim!', NULL, '2026-02-03 12:00:05');
        INSERT INTO usuarios (id, loja_id, nome, papel, email, senha_hash, ativo)
            VALUES (4, 1, 'Dona Teste', 'dono', 'dona@teste.exemplo', 'hash-ficticio', 1);
        INSERT INTO usuarios (id, loja_id, nome, papel) VALUES (6, NULL, 'Operador', 'operador');
        INSERT INTO uso_custos (id, loja_id, execucao_id, custo_llm, tokens_entrada, tipo)
            VALUES (3, 1, 'x1', 0.00123, 900, 'turno');
        PRAGMA user_version = 20;
    """)
    c.commit()
    c.close()
    return caminho


def _contar(tabela):
    c = banco.conectar()
    try:
        return c.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
    finally:
        c.close()


def _um(sql, parametros=()):
    c = banco.conectar()
    try:
        return c.execute(sql, parametros).fetchone()
    finally:
        c.close()


def test_ensaio_so_conta_e_nao_grava(loja_db):
    linhas = []
    resultado = imp.importar(loja_db, ensaio=True, saida=linhas.append)
    assert resultado["estoque"] == (2, 0) and resultado["mensagens"] == (2, 0)
    assert resultado["lojas"] == (2, 1)                    # o PostgreSQL só tem a loja 1 de fábrica
    assert len(resultado) == 40                            # todas as tabelas conferidas
    assert _contar("estoque") == 0 and _contar("lojas") == 1
    assert any("40 tabelas" in l for l in linhas)


def test_importa_tudo_com_os_mesmos_ids_e_dados(loja_db):
    resultado = imp.importar(loja_db, ensaio=False, saida=lambda _t: None)
    assert all(antes == depois for antes, depois in resultado.values())
    assert _um("SELECT nome, config FROM lojas WHERE id = 1") == ("Seminovos Teste", '{"tom": "leve"}')
    carro = _um("SELECT modelo, preco, loja_id FROM estoque WHERE id = 7")
    assert carro == ("Doblò", 52000.5, 1)
    assert _um("SELECT conteudo FROM mensagens WHERE id = 1")[0] == "Oi, o Doblò ainda está aí?"
    assert _um("SELECT nome FROM leads WHERE id = 2")[0] is None
    assert _um("SELECT custo_llm FROM uso_custos WHERE id = 3")[0] == pytest.approx(0.00123)
    assert _um("SELECT estado FROM estado_lojas WHERE loja_id = 3")[0] == "em_teste"
    # a busca sem acento funciona nos dados importados
    assert _um("SELECT COUNT(*) FROM estoque WHERE sem_acento(modelo) LIKE ?", ("%doblo%",))[0] == 1


def test_rodar_duas_vezes_nao_duplica_e_o_proximo_id_continua(loja_db):
    imp.importar(loja_db, ensaio=False, saida=lambda _t: None)
    imp.importar(loja_db, ensaio=False, saida=lambda _t: None)
    assert _contar("mensagens") == 2 and _contar("usuarios") == 2 and _contar("lojas") == 2
    c = banco.conectar()
    try:
        novo = c.execute("INSERT INTO mensagens (lead_id, loja_id, direcao) VALUES ('x', 1, 'cliente')").lastrowid
        nova_loja = c.execute("INSERT INTO lojas (nome) VALUES ('Nova')").lastrowid
        c.commit()
    finally:
        c.close()
    assert novo == 6 and nova_loja == 4


def test_contagem_diferente_para_e_nao_grava_nada(loja_db):
    c = banco.conectar()
    try:
        c.execute("INSERT INTO estoque (id, loja_id, marca, modelo, ano, km, cor, cambio, preco) "
                  "VALUES (500, 1, 'VW', 'Gol', 2018, 1, 'Branco', 'Manual', 40000)")
        c.commit()
    finally:
        c.close()
    with pytest.raises(imp.ImportacaoRecusada, match="estoque"):
        imp.importar(loja_db, ensaio=False, saida=lambda _t: None)
    assert _contar("estoque") == 1 and _contar("mensagens") == 0     # nada entrou
    assert _um("SELECT nome FROM lojas WHERE id = 1")[0] == "Loja 1"


def test_versao_errada_e_recusada(loja_db):
    c = sqlite3.connect(loja_db)
    c.execute("PRAGMA user_version = 19")
    c.commit()
    c.close()
    with pytest.raises(imp.ImportacaoRecusada, match="versão 19"):
        imp.importar(loja_db, ensaio=True, saida=lambda _t: None)


def test_coluna_que_nao_existe_no_postgres_e_recusada(loja_db):
    c = sqlite3.connect(loja_db)
    c.execute("ALTER TABLE estoque ADD COLUMN coluna_estranha TEXT")
    c.commit()
    c.close()
    with pytest.raises(imp.ImportacaoRecusada, match="coluna_estranha"):
        imp.importar(loja_db, ensaio=False, saida=lambda _t: None)
    assert _contar("estoque") == 0


def test_arquivo_que_nao_existe(tmp_path):
    with pytest.raises(imp.ImportacaoRecusada, match="Não achei"):
        imp.importar(tmp_path / "nada.db", ensaio=True, saida=lambda _t: None)


def test_origem_aberta_so_para_leitura(loja_db):
    antes = loja_db.stat().st_mtime_ns
    imp.importar(loja_db, ensaio=False, saida=lambda _t: None)
    assert loja_db.stat().st_mtime_ns == antes


def test_main_do_ensaio_devolve_zero(loja_db, capsys):
    assert imp.main(["--origem", str(loja_db), "--ensaio"]) == 0
    saida = capsys.readouterr().out
    assert "ENSAIO" in saida and "Ensaio conferido" in saida
    assert "***" in saida or "@" not in saida.split("Destino:")[1].split("\n")[0]   # sem senha

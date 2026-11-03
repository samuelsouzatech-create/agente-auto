"""
P8a do Plano Mestre: migração 12 (usuarios_login).
- recria a tabela usuarios com os cinco papéis, e-mail único (é o login) e
  último acesso, SEM perder ninguém: mesmos ids, mesmos dados, mesmo contador;
- operador e suporte sem loja; vendedor, gestor e dono com loja;
- tabela acessos (tentativas de login);
- pode rodar de novo (testes antigos voltam o user_version) sem perder e-mail;
- se algo der errado no meio, nada muda (o banco continua na v11).
Tudo offline, banco temporário do conftest.
"""
import sqlite3

import pytest

import banco
from banco import conectar

COLUNAS_ANTIGAS = ("id, loja_id, nome, papel, contato_telegram, contato_whatsapp, "
                   "senha_hash, ativo, criado_em")
ANTIGOS = [
    (1, 1, "Ana Souza", "vendedor", "111111", "5581999990001", None, 1, "2026-01-10 12:00:00"),
    (2, 1, "Bruno Lima", "gestor", None, None, "hash-antigo", 0, "2026-02-11 13:00:00"),
    (3, None, "Samuel", "operador", "999999", None, None, 1, "2026-03-12 14:00:00"),
]


def _um(sql, parametros=()):
    conexao = conectar()
    try:
        return conexao.execute(sql, parametros).fetchone()[0]
    finally:
        conexao.close()


def _executar(sql, parametros=()):
    conexao = conectar()
    try:
        novo = conexao.execute(sql, parametros).lastrowid
        conexao.commit()
        return novo
    finally:
        conexao.close()


def _colunas(tabela):
    conexao = conectar()
    try:
        return [l[1] for l in conexao.execute(f"PRAGMA table_info({tabela})")]
    finally:
        conexao.close()


@pytest.fixture
def banco_v11(monkeypatch, tmp_path):
    """Um banco parado na v11, com usuários antigos e um buraco no id 4 (apagado)."""
    monkeypatch.setattr(banco, "CAMINHO_BANCO", str(tmp_path / "v11.db"))
    completas = dict(banco.MIGRACOES)
    monkeypatch.setattr(banco, "MIGRACOES", {v: s for v, s in completas.items() if v <= 11})
    banco.criar_tabelas()
    conexao = conectar()
    try:
        conexao.executemany(
            f"INSERT INTO usuarios ({COLUNAS_ANTIGAS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", ANTIGOS)
        conexao.execute("INSERT INTO usuarios (id, loja_id, nome, papel) VALUES (4, 1, 'Apagado', 'vendedor')")
        conexao.execute("DELETE FROM usuarios WHERE id = 4")
        conexao.commit()
        assert conexao.execute("PRAGMA user_version").fetchone()[0] == 11
    finally:
        conexao.close()
    monkeypatch.setattr(banco, "MIGRACOES", completas)


# ------------------------------------------------------------ estrutura

def test_estrutura_da_v12():
    assert banco.VERSAO_SCHEMA >= 12
    colunas = _colunas("usuarios")
    for coluna in ("email", "ultimo_acesso", "criado_em", "senha_hash", "loja_id"):
        assert coluna in colunas
    assert {"usuario_id", "email", "quando", "resultado"} <= set(_colunas("acessos"))


def test_nenhuma_tabela_aponta_para_usuarios():
    assert _um("SELECT COUNT(*) FROM sqlite_master WHERE sql LIKE '%REFERENCES usuarios%'") == 0


# ------------------------------------------------------------ subir da v11

def test_sobe_da_v11_com_os_mesmos_ids_e_dados(banco_v11):
    banco.migrar()
    assert _um("PRAGMA user_version") == banco.VERSAO_SCHEMA
    conexao = conectar()
    try:
        linhas = [tuple(l) for l in conexao.execute(
            f"SELECT {COLUNAS_ANTIGAS} FROM usuarios ORDER BY id")]
        novos = conexao.execute("SELECT email, ultimo_acesso FROM usuarios").fetchall()
    finally:
        conexao.close()
    assert linhas == ANTIGOS
    assert all(l["email"] is None and l["ultimo_acesso"] is None for l in novos)


def test_contador_de_ids_continua(banco_v11):
    banco.migrar()
    novo = _executar("INSERT INTO usuarios (loja_id, nome, papel) VALUES (1, 'Nova', 'dono')")
    assert novo == 5            # o 4 foi apagado antes e não volta a ser usado


def test_rodar_de_novo_nao_perde_email():
    """Testes antigos voltam o user_version para 3, 4, 10 ou 11 e rodam tudo de novo."""
    uid = _executar("INSERT INTO usuarios (loja_id, nome, papel, email, senha_hash) "
                    "VALUES (1, 'Ana', 'vendedor', 'ana@loja.com', 'h')")
    for versao in (3, 4, 10, 11):
        _executar(f"PRAGMA user_version = {versao}")
        banco.migrar()                                   # não pode quebrar
        assert _um("PRAGMA user_version") == banco.VERSAO_SCHEMA
        assert _um("SELECT email FROM usuarios WHERE id = ?", (uid,)) == "ana@loja.com"
    assert _um("SELECT COUNT(*) FROM usuarios") == 1


def test_migracao_recusa_dado_que_nao_combina_e_nao_muda_nada(banco_v11):
    _executar("INSERT INTO usuarios (loja_id, nome, papel) VALUES (1, 'Op', 'operador')")
    with pytest.raises(banco.MigracaoRecusada):
        banco.migrar()
    assert _um("PRAGMA user_version") == 11
    assert "email" not in _colunas("usuarios")
    assert _um("SELECT COUNT(*) FROM usuarios") == 4


def test_erro_no_meio_desfaz_tudo(banco_v11, monkeypatch):
    monkeypatch.setattr(banco, "_TABELA_ACESSOS_V12", "CREATE TABLE acessos (")   # SQL quebrado
    with pytest.raises(sqlite3.Error):
        banco.migrar()
    assert _um("PRAGMA user_version") == 11
    assert "email" not in _colunas("usuarios")           # a recriação foi desfeita
    assert _um("SELECT COUNT(*) FROM usuarios") == 3


# ------------------------------------------------------------ regras no banco

@pytest.mark.parametrize("loja, papel", [
    (1, "operador"), (1, "suporte"), (None, "vendedor"), (None, "gestor"), (None, "dono"),
    (1, "gerente"), (1, "cliente"),
])
def test_banco_recusa_papel_e_loja_errados(loja, papel):
    with pytest.raises(sqlite3.IntegrityError):
        _executar("INSERT INTO usuarios (loja_id, nome, papel) VALUES (?, 'X', ?)", (loja, papel))


def test_papeis_validos_entram():
    for loja, papel in ((1, "vendedor"), (1, "gestor"), (1, "dono"), (None, "operador"), (None, "suporte")):
        _executar("INSERT INTO usuarios (loja_id, nome, papel) VALUES (?, 'X', ?)", (loja, papel))
    assert _um("SELECT COUNT(*) FROM usuarios") == 5


def test_email_unico_sem_diferenca_de_maiusculas_e_vazio_pode_repetir():
    sql = "INSERT INTO usuarios (loja_id, nome, papel, email) VALUES (1, 'X', 'vendedor', ?)"
    _executar(sql, ("ana@loja.com",))
    with pytest.raises(sqlite3.IntegrityError):
        _executar(sql, ("ANA@loja.com",))
    _executar(sql, (None,))
    _executar(sql, (None,))                              # usuários antigos: vários sem e-mail
    assert _um("SELECT COUNT(*) FROM usuarios WHERE email IS NULL") == 2
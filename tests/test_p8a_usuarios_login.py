"""
P8a do Plano Mestre: migração 12 (usuarios_login).
- recria a tabela usuarios com os cinco papéis, e-mail único (é o login) e
  último acesso, SEM perder ninguém: mesmos ids, mesmos dados, mesmo contador;
- operador e suporte sem loja; vendedor, gestor e dono com loja;
- tabela acessos (tentativas de login);
Tudo offline, banco temporário do conftest.
PG1 (Maratona Postgres): os testes de SUBIDA do SQLite (da v11 para a v12, rodar de novo, erro
no meio) saíram: o banco agora nasce da migração-base do PostgreSQL, que já tem a v12. O que
vale para o PostgreSQL (tudo ou nada, rodar de novo) está em tests/test_pg1_banco.py.
"""

import pytest

import banco
from banco import conectar



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
    return banco.colunas(tabela)


# ------------------------------------------------------------ estrutura

def test_estrutura_da_v12():
    assert banco.VERSAO_SCHEMA >= 12
    colunas = _colunas("usuarios")
    for coluna in ("email", "ultimo_acesso", "criado_em", "senha_hash", "loja_id"):
        assert coluna in colunas
    assert {"usuario_id", "email", "quando", "resultado"} <= set(_colunas("acessos"))


def test_nenhuma_tabela_aponta_para_usuarios():
    assert _um("SELECT COUNT(*) FROM information_schema.constraint_column_usage "
               "WHERE table_name = 'usuarios' AND constraint_name LIKE '%fkey%'") == 0


# ------------------------------------------------------------ regras no banco

@pytest.mark.parametrize("loja, papel", [
    (1, "operador"), (1, "suporte"), (None, "vendedor"), (None, "gestor"), (None, "dono"),
    (1, "gerente"), (1, "cliente"),
])
def test_banco_recusa_papel_e_loja_errados(loja, papel):
    with pytest.raises(banco.ErroDeIntegridade):
        _executar("INSERT INTO usuarios (loja_id, nome, papel) VALUES (?, 'X', ?)", (loja, papel))


def test_papeis_validos_entram():
    for loja, papel in ((1, "vendedor"), (1, "gestor"), (1, "dono"), (None, "operador"), (None, "suporte")):
        _executar("INSERT INTO usuarios (loja_id, nome, papel) VALUES (?, 'X', ?)", (loja, papel))
    assert _um("SELECT COUNT(*) FROM usuarios") == 5


def test_email_unico_sem_diferenca_de_maiusculas_e_vazio_pode_repetir():
    sql = "INSERT INTO usuarios (loja_id, nome, papel, email) VALUES (1, 'X', 'vendedor', ?)"
    _executar(sql, ("ana@loja.com",))
    with pytest.raises(banco.ErroDeIntegridade):
        _executar(sql, ("ANA@loja.com",))
    _executar(sql, (None,))
    _executar(sql, (None,))                              # usuários antigos: vários sem e-mail
    assert _um("SELECT COUNT(*) FROM usuarios WHERE email IS NULL") == 2
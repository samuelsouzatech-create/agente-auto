"""
Maratona do painel (P5a): scripts/criar_usuarios_demo.py cria dono, gerente e vendedor de teste.
- a senha é gerada, devolvida para aparecer só no terminal, e o banco guarda só o hash;
- cada pessoa entra com a senha e fica na loja certa (duas lojas: a A nunca recebe gente da B);
- rodar de novo pula quem já existe e não troca a senha;
- sem loja de demonstração, o script avisa e não cria nada.
Tudo offline, banco temporário do conftest.
"""
import json

from app import autenticacao
from banco import conectar
from scripts import criar_usuarios_demo as script


def _executar(sql, parametros=()):
    conexao = conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


def _linhas(sql, parametros=()):
    conexao = conectar()
    try:
        return [tuple(l) for l in conexao.execute(sql, parametros).fetchall()]
    finally:
        conexao.close()


def _loja_demo(loja_id=2, nome="Recife Seminovos Demo"):
    _executar("INSERT INTO lojas (id, nome, segmento, config) VALUES (?, ?, 'veiculos', ?)",
              (loja_id, nome, json.dumps({"demo": True})))


def test_cria_tres_pessoas_que_entram_com_a_senha_gerada():
    feitos = script.criar_usuarios(1)
    assert [p["papel"] for p in feitos] == ["dono", "gestor", "vendedor"]
    for p in feitos:
        assert p["senha"] and len(p["senha"]) >= 10
        pessoa = autenticacao.autenticar(p["email"], p["senha"])
        assert pessoa is not None
        assert pessoa["loja_id"] == 1
        assert pessoa["papel"] == p["papel"]
    guardadas = [l[0] for l in _linhas("SELECT senha_hash FROM usuarios WHERE loja_id = 1")]
    for p in feitos:
        assert p["senha"] not in guardadas      # o banco só tem o hash


def test_rodar_de_novo_nao_troca_a_senha():
    primeira = script.criar_usuarios(1)
    segunda = script.criar_usuarios(1)
    assert all(p["senha"] is None for p in segunda)
    for p in primeira:
        assert autenticacao.autenticar(p["email"], p["senha"]) is not None
    assert _linhas("SELECT COUNT(*) FROM usuarios WHERE loja_id = 1") == [(3,)]


def test_duas_lojas_cada_uma_com_a_sua_gente():
    _loja_demo(2)
    a = script.criar_usuarios(1)
    b = script.criar_usuarios(2)
    assert {p["email"] for p in a}.isdisjoint({p["email"] for p in b})
    assert _linhas("SELECT DISTINCT loja_id FROM usuarios WHERE email LIKE '%.loja1@%'") == [(1,)]
    assert _linhas("SELECT DISTINCT loja_id FROM usuarios WHERE email LIKE '%.loja2@%'") == [(2,)]
    dono_b = autenticacao.autenticar(b[0]["email"], b[0]["senha"])
    assert dono_b["loja_id"] == 2


def test_sem_loja_de_demonstracao_avisa_e_nao_cria(capsys):
    assert script.main([]) == 1
    assert "loja de demonstração" in capsys.readouterr().out
    assert _linhas("SELECT COUNT(*) FROM usuarios") == [(0,)]


def test_com_loja_de_demonstracao_imprime_as_senhas_so_no_terminal(capsys, tmp_path, monkeypatch):
    _loja_demo(3)
    monkeypatch.chdir(tmp_path)
    assert script.main([]) == 0
    saida = capsys.readouterr().out
    assert "Recife Seminovos Demo" in saida
    assert saida.count("senha:") == 3
    assert list(tmp_path.iterdir()) == []       # nada gravado em arquivo


def test_loja_que_nao_existe(capsys):
    assert script.main(["--loja", "99"]) == 1
    assert "não existe" in capsys.readouterr().out

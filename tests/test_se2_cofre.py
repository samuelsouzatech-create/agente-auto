"""
SE2 (Maratona Segurança), item 1: cofre dos tokens (migração 22). OFFLINE, duas lojas.
A chave mestra dos testes é gerada na hora (nunca a do .env).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app import canais, cofre, credenciais
from app.estado_loja import colocar_no_ar
from app.lojas import criar_loja
from banco import conectar

TOKEN_A = "EAAfalso-token-da-loja-A-0123456789"
TOKEN_B = "EAAfalso-token-da-loja-B-9876543210"
RAIZ = Path(__file__).resolve().parent.parent


def _ler(sql, args=()):
    c = conectar()
    try:
        return [dict(l) for l in c.execute(sql, args).fetchall()]
    finally:
        c.close()


@pytest.fixture
def chave(monkeypatch):
    k = cofre.nova_chave()
    monkeypatch.setenv("LEO_CHAVE_MESTRA", k)
    return k


@pytest.fixture
def loja_b():
    loja = criar_loja("Loja B Cofre")
    colocar_no_ar(loja)
    return loja


def test_migracao_22_cria_o_cofre():
    import banco
    assert banco.VERSAO_SCHEMA >= 22
    colunas = {l["column_name"] for l in _ler(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'cofre_credenciais'")}
    assert {"loja_id", "tipo_canal", "conta", "token_cifrado", "chave_id"} <= colunas


def test_banco_so_guarda_o_texto_cifrado(chave):
    cofre.guardar_token(1, "whatsapp", "phone-a", TOKEN_A)
    [linha] = _ler("SELECT * FROM cofre_credenciais")
    tudo = json.dumps(linha, default=str)
    assert TOKEN_A not in tudo and "falso-token" not in tudo
    assert linha["token_cifrado"].startswith("v1:") and chave not in tudo
    assert cofre.ler_token(1, "whatsapp", "phone-a") == TOKEN_A


def test_chave_errada_nao_abre(chave, monkeypatch):
    cofre.guardar_token(1, "whatsapp", "phone-a", TOKEN_A)
    monkeypatch.setenv("LEO_CHAVE_MESTRA", cofre.nova_chave())
    with pytest.raises(cofre.ErroCofre):
        cofre.ler_token(1, "whatsapp", "phone-a")
    assert cofre.situacao()[0]["abre_com_a_chave_do_env"] is False
    monkeypatch.delenv("LEO_CHAVE_MESTRA")
    with pytest.raises(cofre.ErroCofre):
        cofre.ler_token(1, "whatsapp", "phone-a")


def test_duas_lojas_e_texto_copiado_de_outra_loja_nao_abre(chave, loja_b):
    cofre.guardar_token(1, "whatsapp", "phone-a", TOKEN_A)
    cofre.guardar_token(loja_b, "whatsapp", "phone-b", TOKEN_B)
    assert cofre.ler_token(1, "whatsapp", "phone-a") == TOKEN_A
    assert cofre.ler_token(loja_b, "whatsapp", "phone-b") == TOKEN_B
    assert cofre.ler_token(loja_b, "whatsapp", "phone-a") is None          # a B não vê a conta da A
    c = conectar()                                                         # alguém copia o cifrado da A para a B
    c.execute("UPDATE cofre_credenciais SET token_cifrado = (SELECT token_cifrado FROM cofre_credenciais "
              "WHERE loja_id = 1) WHERE loja_id = ?", (loja_b,))
    c.commit()
    c.close()
    with pytest.raises(cofre.ErroCofre):
        cofre.ler_token(loja_b, "whatsapp", "phone-b")


def test_trocar_token(chave):
    cofre.guardar_token(1, "instagram", "conta-a", "token-velho")
    cofre.guardar_token(1, "instagram", "conta-a", "token-novo")
    assert cofre.ler_token(1, "instagram", "conta-a") == "token-novo"
    assert len(_ler("SELECT id FROM cofre_credenciais")) == 1


def test_trocar_a_chave_mestra_recifra_tudo(chave, loja_b, monkeypatch):
    cofre.guardar_token(1, "whatsapp", "phone-a", TOKEN_A)
    cofre.guardar_token(loja_b, "telegram", "123", TOKEN_B)
    antes = {l["id"]: l["token_cifrado"] for l in _ler("SELECT id, token_cifrado FROM cofre_credenciais")}
    nova = cofre.nova_chave()
    assert cofre.trocar_chave_mestra(chave, nova) == 2
    depois = {l["id"]: l["token_cifrado"] for l in _ler("SELECT id, token_cifrado FROM cofre_credenciais")}
    assert all(antes[i] != depois[i] for i in antes)
    with pytest.raises(cofre.ErroCofre):                                    # a velha não abre mais
        cofre.ler_token(1, "whatsapp", "phone-a")
    monkeypatch.setenv("LEO_CHAVE_MESTRA", nova)
    assert cofre.ler_token(1, "whatsapp", "phone-a") == TOKEN_A
    assert cofre.ler_token(loja_b, "telegram", "123") == TOKEN_B


def test_trocar_com_a_chave_atual_errada_nao_muda_nada(chave):
    cofre.guardar_token(1, "whatsapp", "phone-a", TOKEN_A)
    antes = _ler("SELECT token_cifrado FROM cofre_credenciais")
    with pytest.raises(cofre.ErroCofre):
        cofre.trocar_chave_mestra(cofre.nova_chave(), cofre.nova_chave())
    assert _ler("SELECT token_cifrado FROM cofre_credenciais") == antes


# ------------------------------------------------------------------ o envio usa o cofre
def test_envio_usa_o_cofre_antes_do_token_ref(chave, monkeypatch):
    monkeypatch.setenv("WA_TOKEN_RESERVA", "token-do-env")
    canais.cadastrar_canal(1, "whatsapp", "phone-a", "WA_TOKEN_RESERVA")
    assert credenciais.credencial_whatsapp(1).token == "token-do-env"       # sem cofre: reserva
    cofre.guardar_token(1, "whatsapp", "phone-a", TOKEN_A)
    assert credenciais.credencial_whatsapp(1).token == TOKEN_A               # com cofre: o cofre


def test_envio_instagram_e_sem_token_ref(chave):
    canais.cadastrar_canal(1, "instagram", "conta-ig", None)
    with pytest.raises(credenciais.SemCredencial):
        credenciais.credencial_instagram(1)
    cofre.guardar_token(1, "instagram", "conta-ig", "token-ig-falso")
    assert credenciais.credencial_instagram(1).token == "token-ig-falso"


def test_chave_errada_no_envio_falha_fechado(chave, monkeypatch):
    monkeypatch.setenv("WA_TOKEN_RESERVA", "token-do-env")
    canais.cadastrar_canal(1, "whatsapp", "phone-a", "WA_TOKEN_RESERVA")
    cofre.guardar_token(1, "whatsapp", "phone-a", TOKEN_A)
    monkeypatch.setenv("LEO_CHAVE_MESTRA", cofre.nova_chave())
    with pytest.raises(credenciais.SemCredencial):        # não cai para a reserva sem avisar
        credenciais.credencial_whatsapp(1)


def test_token_nunca_aparece_em_repr_nem_na_situacao(chave):
    canais.cadastrar_canal(1, "whatsapp", "phone-a", None)
    cofre.guardar_token(1, "whatsapp", "phone-a", TOKEN_A)
    cred = credenciais.credencial_whatsapp(1)
    assert TOKEN_A not in repr(cred) and TOKEN_A not in str(cred)
    assert TOKEN_A not in json.dumps(cofre.situacao(), default=str)
    assert credenciais.situacao_da_chave(canais.canal_ativo_da_loja(1, "whatsapp")) == credenciais.ENCONTRADA


def test_api_do_painel_nunca_devolve_o_cofre():
    for arquivo in (RAIZ / "app" / "api_painel").rglob("*.py"):
        texto = arquivo.read_text(encoding="utf-8")
        assert "cofre" not in texto and "token_cifrado" not in texto, arquivo.name


# ------------------------------------------------------------------ o script
class _Saida:
    def __init__(self, returncode, stdout, stderr):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _script(*args, entrada="", env=None, capsys=None):
    """Roda o scripts/cofre.py AQUI DENTRO (no banco de teste). Rodar como outro programa usaria
    a BANCO_URL do .env, que é o banco de uso."""
    import importlib.util
    import io
    import os
    spec = importlib.util.spec_from_file_location("script_cofre", RAIZ / "scripts" / "cofre.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    antes = {k: os.environ.get(k) for k in (env or {})}
    os.environ.update(env or {})
    try:
        codigo = modulo.main(list(args), entrada=io.StringIO(entrada))
    finally:
        for k, v in antes.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    saida = capsys.readouterr()
    return _Saida(codigo, saida.out, saida.err)


def test_script_cadastra_sem_mostrar_o_token(chave, capsys):
    r = _script("cadastrar", "--loja", "1", "--canal", "whatsapp", "--conta", "phone-s", entrada=TOKEN_A + "\n",
                capsys=capsys)
    assert r.returncode == 0, r.stderr
    assert TOKEN_A not in r.stdout + r.stderr
    assert cofre.ler_token(1, "whatsapp", "phone-s") == TOKEN_A
    r = _script("situacao", capsys=capsys)
    assert "phone-s" in r.stdout and TOKEN_A not in r.stdout


def test_script_troca_a_chave(chave, monkeypatch, capsys):
    cofre.guardar_token(1, "whatsapp", "phone-a", TOKEN_A)
    nova = cofre.nova_chave()
    r = _script("trocar-chave", env={"LEO_CHAVE_MESTRA_NOVA": nova}, capsys=capsys)
    assert r.returncode == 0, r.stderr
    assert nova not in r.stdout + r.stderr and chave not in r.stdout + r.stderr
    monkeypatch.setenv("LEO_CHAVE_MESTRA", nova)
    assert cofre.ler_token(1, "whatsapp", "phone-a") == TOKEN_A


def test_chave_mestra_nunca_no_git_nem_no_banco(chave):
    exemplo = (RAIZ / ".env.example").read_text(encoding="utf-8")
    assert "LEO_CHAVE_MESTRA=" in exemplo
    linha = next(l for l in exemplo.splitlines() if l.startswith("LEO_CHAVE_MESTRA="))
    assert linha.strip() == "LEO_CHAVE_MESTRA="                       # sem valor no exemplo
    cofre.guardar_token(1, "whatsapp", "phone-a", TOKEN_A)
    c = conectar()
    try:
        colunas = c.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = current_schema() "
                            "AND data_type = 'text'").fetchall()
        for l in colunas:
            n = c.execute(f"SELECT COUNT(*) AS n FROM {l['table_name']} WHERE strpos({l['column_name']}, ?) > 0",
                          (chave,)).fetchone()["n"]
            assert n == 0, f"{l['table_name']}.{l['column_name']}"
    finally:
        c.close()


def test_migracao_22_sobe_da_21_sem_apagar_dado(tmp_path, monkeypatch):
    """Banco novo com a 20 e a 21, dados dentro, depois a 22: tudo continua lá."""
    import psycopg
    from psycopg import sql
    import banco
    url_app, url = banco.url_do_banco(), banco.url_do_dono()     # SE3: criar banco é coisa do dono
    nome = banco.nome_do_banco(url) + "_m22"
    admin = banco.trocar_nome_do_banco(url, "postgres")
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(nome)))
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nome)))
    ate_21 = tmp_path / "ate21"
    ate_21.mkdir()
    for arquivo in ("020_base_postgres.sql", "021_instagram.sql"):
        (ate_21 / arquivo).write_text((banco.PASTA_MIGRACOES / arquivo).read_text(encoding="utf-8"), encoding="utf-8")
    original = banco.PASTA_MIGRACOES
    try:
        banco.apontar_para(banco.trocar_nome_do_banco(url, nome))
        monkeypatch.setattr(banco, "PASTA_MIGRACOES", ate_21)
        assert banco.migrar() == [20, 21]
        c = conectar()
        c.execute("INSERT INTO canais (loja_id, tipo, id_externo, token_ref) VALUES (1, 'whatsapp', 'phone-m22', 'WA_X')")
        c.commit()
        c.close()
        monkeypatch.setattr(banco, "PASTA_MIGRACOES", original)
        assert banco.migrar()[0] == 22
        assert _ler("SELECT id_externo, token_ref FROM canais WHERE id_externo = 'phone-m22'") == \
            [{"id_externo": "phone-m22", "token_ref": "WA_X"}]                # o token_ref antigo fica
        assert _ler("SELECT COUNT(*) AS n FROM cofre_credenciais") == [{"n": 0}]
        assert banco.migrar() == []
    finally:
        banco.fechar_pools()
        banco.apontar_para(url_app, dono=url)
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(nome)))

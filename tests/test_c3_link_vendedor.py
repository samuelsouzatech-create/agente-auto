"""
C3a: link do vendedor (migração 17 e GET /v/{token}).
- migração 17: tabela links_vendedor, só com o hash; pode rodar de novo;
- link certo: 302 para a conversa no front, sem token; sessão de escopo "link"
  que abre só aquela conversa; anotado em acessos;
- uso único; vencido; anulado por um mais novo; pessoa desativada; desconhecido;
- só dono, gestor ou vendedor da própria loja recebem link;
- links errados demais = 429;
- token nunca em log nem no banco; log mostra /v/***.
Tudo offline, banco temporário do conftest.
"""
import json
import logging

import pytest

import banco
from banco import conectar, migrar
from app import autenticacao, links_vendedor
from app.api_painel import logs
from app.api_painel.dependencias import COOKIE
from app.api_painel.main import PREFIXO
from app.lojas import criar_loja
from tests.test_c2a_api_acesso import EU, SENHA, _executar, _novo, _pessoa, _um, _validar
from tests.test_c2c_conversas import LEAD1, LEAD2, _conversa_basica

V = PREFIXO + "/v/"
FRONT = "https://painel.exemplo.com"
API = "https://api.exemplo.com"


@pytest.fixture(autouse=True)
def enderecos(monkeypatch):
    monkeypatch.setenv("PAINEL_URL", FRONT + "/")
    monkeypatch.setenv("API_PUBLICA_URL", API)


def _token(link):
    return link.rsplit("/v/", 1)[1]


def _abrir(cliente, token):
    return cliente.get(V + token, follow_redirects=False)


def _motivo(r):
    assert r.status_code == 302, r.text
    return r.headers["location"].rsplit("motivo=", 1)[1]


def _cookie(r):
    for parte in r.headers.get_list("set-cookie"):
        if parte.startswith(COOKIE + "="):
            return parte.split(";", 1)[0].split("=", 1)[1]
    return None


def _tudo(*tabelas):
    conexao = conectar()
    try:
        return json.dumps([dict(l) for t in tabelas for l in conexao.execute(f"SELECT * FROM {t}")],
                          default=str)
    finally:
        conexao.close()


def test_migracao_17_so_hash_e_pode_rodar_de_novo():
    assert 17 in banco.MIGRACOES
    conexao = conectar()
    try:
        colunas = {l[1] for l in conexao.execute("PRAGMA table_info(links_vendedor)")}
    finally:
        conexao.close()
    assert {"token_hash", "loja_id", "usuario_id", "lead_id", "expira_em", "usado_em",
            "revogado_em"} <= colunas
    assert "token" not in colunas
    _executar("PRAGMA user_version = 16")
    migrar()
    assert _um("PRAGMA user_version") == banco.VERSAO_SCHEMA


def test_link_certo_abre_so_aquela_conversa():
    uid = _pessoa()
    _conversa_basica(lead=LEAD1)
    link = links_vendedor.gerar_link(1, uid, LEAD1)
    assert link.startswith(API + "/api/v1/v/")
    token = _token(link)
    with _novo() as c:
        r = _abrir(c, token)
    assert r.status_code == 302
    assert r.headers["location"] == f"{FRONT}/conversas/{LEAD1}"
    assert token not in r.headers["location"]
    sessao = _cookie(r)
    assert sessao
    cab = {"Cookie": f"{COOKIE}={sessao}"}
    with _novo() as c:
        eu = c.get(EU, headers=cab)
        assert eu.status_code == 200, eu.text
        _validar("/auth/eu", "get", eu)
        assert eu.json()["escopo"] == "link" and eu.json()["conversa_do_link"] == LEAD1
        assert c.get(PREFIXO + f"/conversas/{LEAD1}", headers=cab).status_code == 200
        assert c.get(PREFIXO + f"/conversas/{LEAD2}", headers=cab).status_code == 403
        assert c.get(PREFIXO + "/leads", headers=cab).status_code == 403
    assert _um("SELECT COUNT(*) FROM acessos WHERE resultado = 'link_vendedor'") == 1


def test_link_so_vale_uma_vez():
    uid = _pessoa()
    token = _token(links_vendedor.gerar_link(1, uid, LEAD1))
    with _novo() as c:
        assert _abrir(c, token).status_code == 302
        de_novo = _abrir(c, token)
    assert _motivo(de_novo) == "usado"
    assert _cookie(de_novo) is None


def test_vencido_anulado_desativado_e_desconhecido():
    uid = _pessoa()
    velho = _token(links_vendedor.gerar_link(1, uid, LEAD1))
    novo = _token(links_vendedor.gerar_link(1, uid, LEAD1))
    outro = _token(links_vendedor.gerar_link(1, uid, LEAD2))
    with _novo() as c:
        assert _motivo(_abrir(c, velho)) == "revogado"          # o mais novo anula
        _executar("UPDATE links_vendedor SET expira_em = '2000-01-01 00:00:00' "
                  "WHERE lead_id = ? AND revogado_em IS NULL", (LEAD1,))
        assert _motivo(_abrir(c, novo)) == "vencido"
        _executar("UPDATE usuarios SET ativo = 0 WHERE id = ?", (uid,))
        assert _motivo(_abrir(c, outro)) == "revogado"          # pessoa desativada
        assert _motivo(_abrir(c, "x" * 43)) == "vencido"        # nunca existiu
        assert _motivo(_abrir(c, "curto")) == "vencido"
    assert _um("SELECT COUNT(*) FROM links_vendedor WHERE usado_em IS NOT NULL") == 0
    assert _um("SELECT COUNT(*) FROM sessoes") == 0


def test_so_quem_entra_no_painel_desta_loja_recebe_link():
    operador = autenticacao.criar_usuario_com_login(None, "Samuel", "operador", "samuel@leo.com", SENHA)
    outra = criar_loja("Garagem Dois")
    de_outra = _pessoa(loja=outra, email="caio@dois.com", nome="Caio")
    for uid in (operador, de_outra, 999999):
        with pytest.raises(links_vendedor.SemAcesso):
            links_vendedor.gerar_link(1, uid, LEAD1)
    with pytest.raises(links_vendedor.SemAcesso):
        links_vendedor.gerar_link(1, _pessoa(), "   ")
    assert _um("SELECT COUNT(*) FROM links_vendedor") == 0


def test_links_errados_demais_dao_429():
    with _novo() as c:
        for _ in range(links_vendedor.MAX_LINK_ERRADO):
            assert _abrir(c, "x" * 43).status_code == 302
        r = _abrir(c, "x" * 43)
    assert r.status_code == 429
    _validar("/v/{token}", "get", r)
    assert r.json()["codigo"] == "muitas_tentativas"


def test_token_nunca_em_log_nem_no_banco(caplog, capsys):
    caplog.set_level(logging.DEBUG)
    uid = _pessoa()
    token = _token(links_vendedor.gerar_link(1, uid, LEAD1))
    with _novo() as c:
        _abrir(c, token)
    saida = capsys.readouterr()
    # httpx e o navegador do teste: ele ja conhece o link de qualquer jeito.
    # O que importa e o log do servidor, o terminal e o banco.
    do_servidor = chr(10).join(r.getMessage() for r in caplog.records
                               if not r.name.startswith('httpx'))
    for texto in (do_servidor, saida.out, saida.err):
        assert token not in texto
    assert token not in _tudo("links_vendedor", "acessos", "sessoes")
    assert logs.esconder(f"GET /api/v1/v/{token} HTTP/1.1") == "GET /api/v1/v/*** HTTP/1.1"
    assert logs.esconder("/conversas/5581999990001") == "/conversas/***"

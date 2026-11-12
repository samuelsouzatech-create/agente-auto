"""
C3c (correção do analista): a sessão do link do vendedor vale 12 h.
- no banco: expira_em = criado_em + 12 h; o login continua com 7 dias;
- no cookie: Max-Age de 12 h quando entra pelo link; 7 dias no login;
- depois de 12 h a sessão do link não vale mais.
Tudo offline, banco temporário do conftest.
"""
from datetime import datetime, timedelta

from fastapi import Response

from banco import conectar
from app import links_vendedor, sessoes
from app.relogio import agora_utc
from app.api_painel.dependencias import COOKIE
from app.api_painel.rotas_auth import _gravar_cookie
from tests.test_c2a_api_acesso import _novo, _pessoa
from tests.test_c2c_conversas import LEAD1
from tests.test_c3_link_vendedor import V, _token, enderecos  # noqa: F401

DOZE_HORAS = 12 * 3600
SETE_DIAS = 7 * 24 * 3600


def _duracao(token):
    conexao = conectar()
    try:
        linha = conexao.execute("SELECT criado_em, expira_em FROM sessoes WHERE token_hash = ?",
                                (sessoes._hash(token),)).fetchone()
    finally:
        conexao.close()
    return datetime.fromisoformat(linha["expira_em"]) - datetime.fromisoformat(linha["criado_em"])


def _papel(uid):
    conexao = conectar()
    try:
        return conexao.execute("SELECT papel FROM usuarios WHERE id = ?", (uid,)).fetchone()[0]
    finally:
        conexao.close()


def test_sessao_do_link_vale_12h_e_login_7_dias():
    uid = _pessoa()
    agora = agora_utc()
    link = sessoes.criar_sessao(uid, 1, sessoes.PAPEL_LINK, lead_id=LEAD1, agora=agora)
    login = sessoes.criar_sessao(uid, 1, _papel(uid), agora=agora)
    assert _duracao(link) == timedelta(hours=12)
    assert _duracao(login) == timedelta(days=7)
    assert sessoes.ler_sessao(link, agora=agora + timedelta(hours=11, minutes=59)) is not None
    assert sessoes.ler_sessao(link, agora=agora + timedelta(hours=12, minutes=1)) is None
    assert sessoes.ler_sessao(login, agora=agora + timedelta(hours=12, minutes=1)) is not None


def test_cookie_do_link_vale_12h():
    uid = _pessoa()
    token = _token(links_vendedor.gerar_link(1, uid, LEAD1))
    with _novo() as c:
        r = c.get(V + token, follow_redirects=False)
    assert r.status_code == 302
    cookies = [p for p in r.headers.get_list("set-cookie") if p.startswith(COOKIE + "=")]
    assert len(cookies) == 1
    assert f"max-age={DOZE_HORAS}" in cookies[0].lower()
    sessao = cookies[0].split(";", 1)[0].split("=", 1)[1]
    assert _duracao(sessao) == timedelta(hours=12)


def test_cookie_por_escopo():
    for escopo, segundos in ((None, SETE_DIAS), (sessoes.COMPLETO, SETE_DIAS),
                             (sessoes.ATENDIMENTO, SETE_DIAS), (sessoes.LINK, DOZE_HORAS)):
        resposta = Response()
        _gravar_cookie(resposta, "x" * 43, escopo)
        assert f"max-age={segundos}" in resposta.headers["set-cookie"].lower()

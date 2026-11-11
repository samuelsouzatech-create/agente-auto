"""
C2f: criar e recuperar senha pelo link (migração 16).
- migração 16: tabela links_senha, só com o hash do token; pode rodar de novo;
- esqueci-senha: sempre 202 e a mesma mensagem (e-mail que existe, que não existe,
  operador, pessoa desativada, loja desligada, vazio); só quem entra no painel ganha link;
- limite de pedidos por e-mail (429), igual para quem existe e quem não existe;
- criar-senha: sucesso encerra todas as sessões e grava no Registro; uso único;
  vencido, anulado por um mais novo e de pessoa desativada = link_invalido;
  senha fraca não gasta o link; links errados demais = 429;
- o operador gera o link (só ele), com Registro e sem o token no Registro;
- token e senha nunca em log nem no banco; o envio padrão só escreve no terminal.
Tudo offline, banco temporário do conftest.
"""
import json
import logging

import pytest

import banco
from banco import conectar, migrar
from app import autenticacao, links_senha
from app.api_painel.main import PREFIXO
from app.ator import como
from app.estado_loja import SoOperador
from app.lojas import criar_loja
from tests.test_c2a_api_acesso import (EU, LOGIN, SENHA, _executar, _linha, _mock, _novo,
                                       _pessoa, _um, _validar)

ESQUECI = PREFIXO + "/auth/esqueci-senha"
CRIAR = PREFIXO + "/auth/criar-senha"
EMAIL = "ana@loja.com"
NOVA = "Cafe-Com-Leite-2026"


@pytest.fixture
def enviados(monkeypatch):
    """Troca o envio (terminal) por uma lista: cada item é (email, link, tipo)."""
    lista = []
    monkeypatch.setattr(links_senha, "ENVIADOR",
                        lambda email, link, tipo: lista.append((email, link, tipo)))
    return lista


def _token(link):
    return link.split("#token=", 1)[1]


def _tudo(*tabelas):
    conexao = conectar()
    try:
        return json.dumps([dict(l) for t in tabelas for l in conexao.execute(f"SELECT * FROM {t}")],
                          default=str)
    finally:
        conexao.close()


def _criar(cliente, token, senha=NOVA):
    return cliente.post(CRIAR, json={"token": token, "senha_nova": senha})


def test_migracao_16_links_senha_so_com_hash_e_pode_rodar_de_novo():
    assert 16 in banco.MIGRACOES
    conexao = conectar()
    try:
        colunas = {l[1] for l in conexao.execute("PRAGMA table_info(links_senha)")}
    finally:
        conexao.close()
    assert {"token_hash", "usuario_id", "loja_id", "tipo", "expira_em", "usado_em",
            "revogado_em"} <= colunas
    assert "token" not in colunas and "senha" not in colunas
    _executar("PRAGMA user_version = 15")
    migrar()
    assert _um("PRAGMA user_version") == banco.VERSAO_SCHEMA


def test_esqueci_responde_sempre_igual(enviados):
    _pessoa()
    autenticacao.criar_usuario_com_login(None, "Samuel", "operador", "samuel@leo.com", SENHA)
    inativa = _pessoa(email="bia@loja.com", nome="Bia")
    _executar("UPDATE usuarios SET ativo = 0 WHERE id = ?", (inativa,))
    desligada = criar_loja("Garagem Desligada")
    _pessoa(loja=desligada, email="caio@desligada.com", nome="Caio")
    _executar("UPDATE lojas SET ativo = 0 WHERE id = ?", (desligada,))
    pedidos = [{"email": "  ANA@loja.com "}, {"email": "ninguem@loja.com"},
               {"email": "samuel@leo.com"}, {"email": "bia@loja.com"},
               {"email": "caio@desligada.com"}, {}]
    with _novo() as c:
        respostas = [c.post(ESQUECI, json=p) for p in pedidos]
    for r in respostas:
        assert r.status_code == 202, r.text
        assert "set-cookie" not in r.headers
        _validar("/auth/esqueci-senha", "post", r)
    assert all(r.json() == _mock("auth_esqueci_senha__ok.json") for r in respostas)
    assert [(e, t) for e, _, t in enviados] == [(EMAIL, links_senha.REDEFINIR)]
    assert _um("SELECT COUNT(*) FROM links_senha") == 1


def test_esqueci_tem_limite_por_email_mesmo_para_quem_nao_existe(enviados):
    _pessoa()
    with _novo() as c:
        for email in (EMAIL, "ninguem@loja.com"):
            for _ in range(links_senha.MAX_PEDIDOS):
                assert c.post(ESQUECI, json={"email": email}).status_code == 202
            r = c.post(ESQUECI, json={"email": email})
            assert r.status_code == 429
            _validar("/auth/esqueci-senha", "post", r)
            assert r.json()["codigo"] == _mock("auth_esqueci_senha__muitas_tentativas.json")["codigo"]
    assert len(enviados) == links_senha.MAX_PEDIDOS
    assert autenticacao.autenticar(EMAIL, SENHA)          # pedir link não mexe no login


def test_criar_senha_pelo_link(enviados):
    uid = _pessoa()
    with _novo() as a, _novo() as b:
        assert a.post(LOGIN, json={"email": EMAIL, "senha": SENHA}).status_code == 200
        b.post(ESQUECI, json={"email": EMAIL})
        token = _token(enviados[-1][1])
        r = _criar(b, token)
        assert r.status_code == 204, r.text
        _validar("/auth/criar-senha", "post", r)
        assert a.get(EU).status_code == 401               # todas as sessões da pessoa caem
        de_novo = _criar(b, token, "Outra-Senha-Boa-1")
        assert de_novo.status_code == 422
        _validar("/auth/criar-senha", "post", de_novo)
        assert de_novo.json() == _mock("auth_criar_senha__link_invalido.json")
    assert autenticacao.autenticar(EMAIL, SENHA) is None
    assert autenticacao.autenticar(EMAIL, NOVA)["id"] == uid
    assert _linha("SELECT pessoa, origem, loja_id FROM registro_acoes "
                  "WHERE acao = 'criar_senha_por_link'") == ("Ana Lima", "api", 1)


def test_link_anulado_vencido_ou_de_quem_nao_entra_mais(enviados):
    uid = _pessoa()
    with _novo() as c:
        c.post(ESQUECI, json={"email": EMAIL})
        velho = _token(enviados[-1][1])
        c.post(ESQUECI, json={"email": EMAIL})
        novo = _token(enviados[-1][1])
        assert _criar(c, velho).json()["codigo"] == "link_invalido"     # o mais novo anula
        _executar("UPDATE links_senha SET expira_em = '2000-01-01 00:00:00'")
        assert _criar(c, novo).json()["codigo"] == "link_invalido"      # vencido
        c.post(ESQUECI, json={"email": EMAIL})
        terceiro = _token(enviados[-1][1])
        _executar("UPDATE usuarios SET ativo = 0 WHERE id = ?", (uid,))
        assert _criar(c, terceiro).json()["codigo"] == "link_invalido"  # desativada
        for token in ("", "curto", "x" * 300):
            assert _criar(c, token).status_code == 422
    assert _um("SELECT COUNT(*) FROM links_senha WHERE usado_em IS NOT NULL") == 0


def test_senha_fraca_nao_gasta_o_link(enviados):
    _pessoa()
    with _novo() as c:
        c.post(ESQUECI, json={"email": EMAIL})
        token = _token(enviados[-1][1])
        fraca = _criar(c, token, "1234567890")
        assert fraca.status_code == 422
        _validar("/auth/criar-senha", "post", fraca)
        esperado = _mock("auth_criar_senha__senha_fraca.json")
        assert fraca.json()["codigo"] == esperado["codigo"]
        assert set(fraca.json()["campos"]) == set(esperado["campos"])
        assert _criar(c, token).status_code == 204
    assert autenticacao.autenticar(EMAIL, NOVA)


def test_links_errados_demais_dao_429():
    with _novo() as c:
        for _ in range(links_senha.MAX_LINK_ERRADO):
            assert _criar(c, "x" * 43).status_code == 422
        r = _criar(c, "x" * 43)
    assert r.status_code == 429
    _validar("/auth/criar-senha", "post", r)


def test_operador_gera_o_link_e_so_ele(enviados):
    dona = _pessoa(papel="dono", email="dona@loja.com", nome="Dona")
    gerado = links_senha.gerar_link_pelo_operador(dona)
    assert gerado["tipo"] == links_senha.REDEFINIR and "#token=" in gerado["link"]
    token = _token(gerado["link"])
    assert _linha("SELECT pessoa, papel, loja_id FROM registro_acoes "
                  "WHERE acao = 'gerar_link_senha'") == ("Teste", "operador", 1)
    assert token not in _tudo("links_senha", "registro_acoes")

    with como("Dona", "cliente", "painel", loja_id=1), pytest.raises(SoOperador):
        links_senha.gerar_link_pelo_operador(dona)
    operador = autenticacao.criar_usuario_com_login(None, "Samuel", "operador", "samuel@leo.com", SENHA)
    _executar("INSERT INTO usuarios (loja_id, nome, papel) VALUES (1, 'Davi', 'vendedor')")
    sem_email = _um("SELECT id FROM usuarios WHERE nome = 'Davi'")
    for uid in (operador, sem_email):
        with pytest.raises(links_senha.SemAcesso):
            links_senha.gerar_link_pelo_operador(uid)

    _executar("INSERT INTO usuarios (loja_id, nome, papel, email) "
              "VALUES (1, 'Caio', 'vendedor', 'caio@loja.com')")
    caio = _um("SELECT id FROM usuarios WHERE email = 'caio@loja.com'")
    primeiro = links_senha.gerar_link_pelo_operador(caio)
    assert primeiro["tipo"] == links_senha.CRIAR           # primeiro acesso: ainda sem senha
    with _novo() as c:
        assert _criar(c, token).status_code == 204
        assert _criar(c, _token(primeiro["link"])).status_code == 204
    assert autenticacao.autenticar("dona@loja.com", NOVA)["id"] == dona
    assert autenticacao.autenticar("caio@loja.com", NOVA)["id"] == caio
    assert enviados == []                                  # o operador copia; nada é "enviado"


def test_token_e_senha_nunca_em_log_nem_no_banco(caplog, capsys, enviados):
    caplog.set_level(logging.DEBUG)
    _pessoa()
    with _novo() as c:
        c.post(ESQUECI, json={"email": EMAIL})
        token = _token(enviados[-1][1])
        _criar(c, token, "1234567890")
        assert _criar(c, token).status_code == 204
    saida = capsys.readouterr()
    for texto in (caplog.text, saida.out, saida.err):
        assert token not in texto and NOVA not in texto
    guardado = _tudo("links_senha", "acessos", "registro_acoes", "sessoes")
    assert token not in guardado and NOVA not in guardado


def test_envio_padrao_so_escreve_no_terminal(capsys, monkeypatch):
    monkeypatch.setenv("PAINEL_URL", "https://painel.exemplo.com/")
    _pessoa()
    links_senha.pedir_link(EMAIL)
    erro = capsys.readouterr().err
    assert EMAIL in erro and "https://painel.exemplo.com/criar-senha#token=" in erro

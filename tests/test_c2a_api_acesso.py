"""
C2a (Plano Mestre, bloco C2), parte HTTP: a API do painel do cliente.
- login certo e errado (mesma resposta para qualquer falha), limite de tentativas;
- cookie HttpOnly, Secure e SameSite; sair; sessão vencida e revogada;
- rota que escreve sem CSRF recusada; loja_id no pedido ignorado; duas lojas;
- trocar senha (sucesso, atual errada, fraca, limite; a própria sessão fica);
- operador e suporte: 401 no login, 403 com sessão criada direto no banco;
- 'Eu' e erros iguais ao openapi.yaml e aos dados falsos de docs/api/mocks/;
- só as 4 rotas do C2a, todas em /api/v1 e todas (menos login) exigem login;
- /docs desligado, CORS só para PAINEL_ORIGEM, token nunca em log.
Tudo offline, banco temporário do conftest.
"""
import json
import logging
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from banco import conectar
from app import autenticacao, sessoes
from app.api_painel import erros
from app.api_painel.dependencias import CABECALHO_CSRF, COOKIE
from app.api_painel.main import PREFIXO, criar_app
from app.lojas import criar_loja, salvar_config

RAIZ = Path(__file__).resolve().parent.parent
API = RAIZ / "docs" / "api"
DOC = yaml.safe_load((API / "openapi.yaml").read_text(encoding="utf-8"))
TEXTO_CONTRATO = ((API / "openapi.yaml").read_text(encoding="utf-8")
                  + (API / "contrato_v1.md").read_text(encoding="utf-8"))
INDICE = json.loads((API / "mocks" / "_indice.json").read_text(encoding="utf-8"))
ROTAS_C2A = {"/auth/login", "/auth/logout", "/auth/eu", "/auth/trocar-senha"}
BASE = "https://testserver"
SENHA = "Carro-Azul-2026"
NOVA = "Moto-Verde-2027"
ERRADA = "Errada-Demais-1"
LOGIN, SAIR, EU, TROCAR = (PREFIXO + r for r in
                           ("/auth/login", "/auth/logout", "/auth/eu", "/auth/trocar-senha"))


# ------------------------------------------------------------ ajudantes

def _um(sql, parametros=()):
    conexao = conectar()
    try:
        return conexao.execute(sql, parametros).fetchone()[0]
    finally:
        conexao.close()


def _linha(sql, parametros=()):
    conexao = conectar()
    try:
        linha = conexao.execute(sql, parametros).fetchone()
        return tuple(linha) if linha else None
    finally:
        conexao.close()


def _executar(sql, parametros=()):
    conexao = conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


def _mock(nome):
    return json.loads((API / "mocks" / nome).read_text(encoding="utf-8"))


def _nome_loja(loja_id):
    return _um("SELECT nome FROM lojas WHERE id = ?", (loja_id,))


def _pessoa(loja=1, papel="gestor", email="ana@loja.com", nome="Ana Lima"):
    return autenticacao.criar_usuario_com_login(loja, nome, papel, email, SENHA)


def _novo():
    return TestClient(criar_app(), base_url=BASE)


def _logar(cliente, email="ana@loja.com", senha=SENHA):
    r = cliente.post(LOGIN, json={"email": email, "senha": senha})
    assert r.status_code == 200, r.text
    return r


def _com_token(token):
    return {"Cookie": f"{COOKIE}={token}", CABECALHO_CSRF: sessoes.csrf_da(token)}


def _abas(lista):
    return [a["codigo"] if isinstance(a, dict) else a for a in lista]


def _rotas_da_app():
    """(MÉTODO, caminho) de cada rota real, lido de app.openapi().
    No FastAPI 0.143 o router incluído fica num objeto só e app.routes não o abre;
    a descrição da API abre. Ela continua desligada para fora (openapi_url=None)."""
    caminhos = criar_app().openapi()["paths"]
    return {(m.upper(), p) for p, ops in caminhos.items() for m in ops
            if m in ("get", "post", "put", "patch", "delete")}


def _rotas_protegidas():
    return sorted((m, p) for m, p in _rotas_da_app() if p != LOGIN)


def _esquema(rota, metodo, status):
    resp = DOC["paths"][rota][metodo]["responses"][status]
    while "$ref" in resp:
        resp = DOC["components"]["responses"][resp["$ref"].split("/")[-1]]
    return resp.get("content", {}).get("application/json", {}).get("schema")


def _validar(rota, metodo, resposta, exigir_status=True):
    """A resposta real obedece ao openapi.yaml (mesma ideia do conferir_mocks.py)."""
    status = str(resposta.status_code)
    if status not in DOC["paths"][rota][metodo]["responses"]:
        assert not exigir_status, f"{metodo.upper()} {rota} não prevê {status} no contrato"
        outras = [(r, m) for r, ops in DOC["paths"].items() for m, op in ops.items()
                  if isinstance(op, dict) and status in op.get("responses", {})]
        assert outras, f"nenhuma rota do contrato prevê {status}"
        rota, metodo = outras[0]
    esquema = _esquema(rota, metodo, status)
    if esquema is None:
        assert not resposta.content, f"{metodo.upper()} {rota} {status} devia vir sem corpo"
        return
    raiz = {**esquema, "components": DOC["components"]}
    problemas = [f"{'/'.join(map(str, e.path)) or '$'}: {e.message}"
                 for e in Draft202012Validator(raiz).iter_errors(resposta.json())]
    assert not problemas, f"{metodo.upper()} {rota} {status} fora do contrato: {problemas}"


@pytest.fixture
def cliente():
    with _novo() as c:
        yield c


# ------------------------------------------------------------ login

def test_login_certo_devolve_eu_cookie_e_csrf(cliente):
    _pessoa()
    r = _logar(cliente, email="  ANA@loja.com ")
    _validar("/auth/login", "post", r)
    eu = r.json()
    assert (eu["papel"], eu["escopo"], eu["nome"]) == ("gestor", "completo", "Ana Lima")
    assert eu["loja"]["nome"] == _nome_loja(1)
    biscoito = r.headers["set-cookie"].lower()
    assert biscoito.startswith(COOKIE + "=")
    assert "httponly" in biscoito and "secure" in biscoito and "samesite=lax" in biscoito
    token = cliente.cookies.get(COOKIE)
    assert token and sessoes.conferir_csrf(token, eu["csrf"])
    assert cliente.get(EU).status_code == 200


def test_login_errado_responde_sempre_igual(cliente):
    _pessoa()
    autenticacao.criar_usuario_com_login(None, "Samuel", "operador", "samuel@leo.com", SENHA)
    autenticacao.criar_usuario_com_login(None, "Suporte", "suporte", "suporte@leo.com", SENHA)
    desligada = criar_loja("Garagem Desligada")
    _pessoa(loja=desligada, email="bia@desligada.com", nome="Bia")
    _executar("UPDATE lojas SET ativo = 0 WHERE id = ?", (desligada,))
    tentativas = [
        {"email": "ana@loja.com", "senha": ERRADA},
        {"email": "ninguem@loja.com", "senha": SENHA},
        {},
        {"email": "samuel@leo.com", "senha": SENHA},
        {"email": "suporte@leo.com", "senha": SENHA},
        {"email": "bia@desligada.com", "senha": SENHA},
    ]
    respostas = [cliente.post(LOGIN, json=t) for t in tentativas]
    for r in respostas:
        assert r.status_code == 401 and "set-cookie" not in r.headers, r.text
        _validar("/auth/login", "post", r)
    assert all(r.json() == respostas[0].json() for r in respostas)
    assert respostas[0].json()["codigo"] == _mock("auth_login__credenciais_invalidas.json")["codigo"]
    assert _um("SELECT COUNT(*) FROM sessoes WHERE revogada_em IS NULL") == 0


def test_limite_de_tentativas_no_login(cliente):
    _pessoa()
    assert cliente.post(LOGIN, json={"email": "ana@loja.com", "senha": ERRADA}).status_code == 401
    for _ in range(autenticacao.MAX_TENTATIVAS - 1):
        cliente.post(LOGIN, json={"email": "ana@loja.com", "senha": ERRADA})
    r = cliente.post(LOGIN, json={"email": "ana@loja.com", "senha": SENHA})
    assert r.status_code == 429 and "set-cookie" not in r.headers
    _validar("/auth/login", "post", r)
    assert r.json()["codigo"] == _mock("auth_login__muitas_tentativas.json")["codigo"]


# ------------------------------------------------------------ sessão

def test_eu_sem_cookie_e_401(cliente):
    r = cliente.get(EU)
    assert r.status_code == 401
    _validar("/auth/eu", "get", r)
    assert r.json()["codigo"] == _mock("auth_eu__nao_autenticado.json")["codigo"]


def test_sessao_vencida_ou_revogada_e_recusada(cliente):
    _pessoa()
    _logar(cliente)
    _executar("UPDATE sessoes SET expira_em = '2000-01-01 00:00:00'")
    assert cliente.get(EU).status_code == 401
    _logar(cliente)
    assert cliente.get(EU).status_code == 200
    _executar("UPDATE sessoes SET revogada_em = '2026-01-01 00:00:00' WHERE revogada_em IS NULL")
    assert cliente.get(EU).status_code == 401


def test_sair_encerra_a_sessao_e_apaga_o_cookie(cliente):
    _pessoa()
    eu = _logar(cliente).json()
    token = cliente.cookies.get(COOKIE)
    r = cliente.post(SAIR, headers={CABECALHO_CSRF: eu["csrf"]})
    assert r.status_code == 204, r.text
    _validar("/auth/logout", "post", r)
    assert "max-age=0" in r.headers["set-cookie"].lower()
    assert sessoes.ler_sessao(token) is None
    with _novo() as outro:
        assert outro.get(EU, headers={"Cookie": f"{COOKIE}={token}"}).status_code == 401


def test_rota_que_escreve_sem_csrf_e_recusada(cliente):
    _pessoa()
    _logar(cliente)
    token = cliente.cookies.get(COOKIE)
    for cabecalho in ({}, {CABECALHO_CSRF: ""}, {CABECALHO_CSRF: "x" * 64}, {CABECALHO_CSRF: token}):
        r = cliente.post(SAIR, headers=cabecalho)
        assert r.status_code == 403 and r.json()["codigo"] == "csrf_invalido"
        _validar("/auth/logout", "post", r, exigir_status=False)
        r = cliente.post(TROCAR, json={"senha_atual": SENHA, "senha_nova": NOVA}, headers=cabecalho)
        assert r.status_code == 403
    assert sessoes.ler_sessao(token)
    assert autenticacao.autenticar("ana@loja.com", SENHA)


def test_loja_id_no_corpo_ou_na_url_e_ignorado(cliente):
    loja2 = criar_loja("Garagem Dois")
    _pessoa()
    r = cliente.post(f"{LOGIN}?loja_id={loja2}",
                     json={"email": "ana@loja.com", "senha": SENHA, "loja_id": loja2})
    assert r.status_code == 200 and r.json()["loja"]["nome"] == _nome_loja(1)
    assert "loja_id" not in json.dumps(r.json())
    assert cliente.get(EU, params={"loja_id": loja2}).json()["loja"]["nome"] == _nome_loja(1)
    assert _um("SELECT loja_id FROM sessoes") == 1


def test_duas_lojas_cada_sessao_ve_so_a_sua():
    loja2 = criar_loja("Garagem Dois")
    _pessoa()
    _pessoa(loja=loja2, email="bia@loja2.com", nome="Bia Costa")
    salvar_config(loja2, {"modulos.estoque": False}, "teste")
    with _novo() as a, _novo() as b:
        _logar(a)
        _logar(b, email="bia@loja2.com")
        ea, eb = a.get(EU).json(), b.get(EU).json()
    assert (ea["nome"], ea["loja"]["nome"]) == ("Ana Lima", _nome_loja(1))
    assert (eb["nome"], eb["loja"]["nome"]) == ("Bia Costa", "Garagem Dois")
    assert ea["modulos"]["estoque"] is True and eb["modulos"]["estoque"] is False
    assert "estoque" in _abas(ea["abas"]) and "estoque" not in _abas(eb["abas"])


# ------------------------------------------------------------ trocar senha

def test_trocar_senha_pela_api():
    uid = _pessoa()
    with _novo() as a, _novo() as b:
        eu = _logar(a).json()
        _logar(b)
        r = a.post(TROCAR, json={"senha_atual": SENHA, "senha_nova": NOVA},
                   headers={CABECALHO_CSRF: eu["csrf"]})
        _validar("/auth/trocar-senha", "post", r)
        assert r.status_code in (200, 204), r.text
        assert a.get(EU).status_code == 200        # a sessão de quem trocou continua
        assert b.get(EU).status_code == 401        # as outras caem
    assert autenticacao.autenticar("ana@loja.com", NOVA)["id"] == uid
    assert _linha("SELECT pessoa, origem, loja_id FROM registro_acoes "
                  "WHERE acao = 'trocar_senha'") == ("Ana Lima", "api", 1)


def test_trocar_senha_atual_errada_fraca_e_limite(cliente):
    _pessoa()
    cabecalho = {CABECALHO_CSRF: _logar(cliente).json()["csrf"]}

    fraca = cliente.post(TROCAR, json={"senha_atual": SENHA, "senha_nova": "1234567890"},
                         headers=cabecalho)
    _validar("/auth/trocar-senha", "post", fraca)
    esperado = _mock("auth_trocar_senha__senha_fraca.json")
    assert fraca.json()["codigo"] == esperado["codigo"]
    assert set(fraca.json().get("campos", {})) == set(esperado.get("campos", {}))

    nome = "auth_trocar_senha__senha_atual_errada.json"
    errada = cliente.post(TROCAR, json={"senha_atual": ERRADA, "senha_nova": NOVA}, headers=cabecalho)
    _validar("/auth/trocar-senha", "post", errada)
    assert errada.status_code == int(INDICE[nome]["status"])
    assert errada.json()["codigo"] == _mock(nome)["codigo"]
    assert set(errada.json().get("campos", {})) == set(_mock(nome).get("campos", {}))

    for _ in range(autenticacao.MAX_TENTATIVAS - 1):
        cliente.post(TROCAR, json={"senha_atual": ERRADA, "senha_nova": NOVA}, headers=cabecalho)
    limite = cliente.post(TROCAR, json={"senha_atual": SENHA, "senha_nova": NOVA}, headers=cabecalho)
    assert limite.status_code == 429
    _validar("/auth/trocar-senha", "post", limite)
    assert limite.json()["codigo"] == _mock("auth_trocar_senha__muitas_tentativas.json")["codigo"]


def test_vendedor_do_link_nao_troca_senha():
    uid = _pessoa(papel="vendedor")
    token = sessoes.criar_sessao(uid, 1, "vendedor_link", escopo="link", lead_id="5581999990001")
    with _novo() as c:
        r = c.post(TROCAR, json={"senha_atual": SENHA, "senha_nova": NOVA}, headers=_com_token(token))
    assert r.status_code == 403
    assert autenticacao.autenticar("ana@loja.com", SENHA)["id"] == uid


# ------------------------------------------------------------ quem não usa este painel

@pytest.mark.parametrize("papel_pessoa, papel_sessao",
                         [("operador", "operador"), ("suporte", "suporte"), ("operador", "gestor")])
def test_sessao_de_operador_ou_suporte_no_banco_recebe_403(papel_pessoa, papel_sessao):
    uid = autenticacao.criar_usuario_com_login(None, "Pessoa", papel_pessoa,
                                               f"{papel_pessoa}@leo.com", SENHA)
    token = "t" * 43
    _executar("INSERT INTO sessoes (token_hash, usuario_id, loja_id, papel, escopo, expira_em) "
              "VALUES (?, ?, 1, ?, 'completo', '2999-01-01 00:00:00')",
              (sessoes._hash(token), uid, papel_sessao))
    with _novo() as c:
        for metodo, rota in _rotas_protegidas():
            r = c.request(metodo, rota, headers=_com_token(token), json={})
            assert r.status_code == 403, f"{metodo} {rota}: {r.status_code}"
            assert r.json()["codigo"] == "sem_permissao"


def test_toda_rota_exige_login():
    rotas = _rotas_protegidas()
    assert rotas
    with _novo() as c:
        for metodo, rota in rotas:
            r = c.request(metodo, rota, json={})
            assert r.status_code == 401, f"{metodo} {rota}: {r.status_code}"
            _validar(rota.removeprefix(PREFIXO), metodo.lower(), r, exigir_status=False)


def test_so_as_rotas_do_c2a_todas_em_api_v1():
    rotas = _rotas_da_app()
    assert rotas == {("POST", LOGIN), ("POST", SAIR), ("GET", EU), ("POST", TROCAR),
                     ("GET", PREFIXO + "/saude"), ("GET", PREFIXO + "/atender")}   # C2b
    assert {r.removeprefix(PREFIXO) for _, r in rotas} <= set(DOC["paths"])


def test_documentacao_automatica_desligada(cliente):
    for caminho in ("/docs", "/redoc", "/openapi.json", PREFIXO + "/docs"):
        r = cliente.get(caminho)
        assert r.status_code == 404
        assert {"codigo", "mensagem"} <= set(r.json())


def test_cors_so_para_a_origem_do_painel(monkeypatch):
    monkeypatch.setenv("PAINEL_ORIGEM", "https://painel.exemplo.com")
    with TestClient(criar_app(), base_url=BASE) as c:
        ok = c.options(LOGIN, headers={"Origin": "https://painel.exemplo.com",
                                       "Access-Control-Request-Method": "POST",
                                       "Access-Control-Request-Headers": "content-type,x-csrf-token"})
        ruim = c.options(LOGIN, headers={"Origin": "https://malicioso.exemplo",
                                         "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "https://painel.exemplo.com"
    assert ok.headers.get("access-control-allow-credentials") == "true"
    assert "access-control-allow-origin" not in ruim.headers


def test_sem_painel_origem_nenhuma_origem_liberada(monkeypatch):
    monkeypatch.delenv("PAINEL_ORIGEM", raising=False)
    with TestClient(criar_app(), base_url=BASE) as c:
        r = c.options(LOGIN, headers={"Origin": "https://painel.exemplo.com",
                                      "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers


# ------------------------------------------------------------ igual aos dados falsos

MOCKS_EU = ["auth_eu__dono.json", "auth_eu__modulos_desligados.json",
            "auth_eu__vendedor_com_login.json", "auth_eu__vendedor_do_link.json",
            "auth_eu__loja_em_teste.json"]


@pytest.mark.parametrize("nome", MOCKS_EU)
def test_eu_igual_ao_dado_falso(nome):
    m = _mock(nome)
    salvar_config(1, {"modulos.remarketing": bool(m["modulos"]["acompanhamento"]),
                      "modulos.pos_venda": False,
                      "modulos.estoque": bool(m["modulos"]["estoque"])}, "teste")
    papel_pessoa = "vendedor" if m["papel"] == "vendedor_link" else m["papel"]
    uid = _pessoa(papel=papel_pessoa)
    if m["escopo"] == "link":
        token = sessoes.criar_sessao(uid, 1, "vendedor_link", escopo="link",
                                     lead_id=m["conversa_do_link"])
    else:
        token = sessoes.criar_sessao(uid, 1, m["papel"])
    with _novo() as c:
        r = c.get(EU, headers={"Cookie": f"{COOKIE}={token}"})
    assert r.status_code == 200, r.text
    _validar("/auth/eu", "get", r)
    eu = r.json()
    assert sorted(eu) == sorted(m), f"{nome}: campos diferentes"
    for campo in ("papel", "papel_rotulo", "escopo", "conversa_do_link", "modulos", "abas"):
        assert eu[campo] == m[campo], f"{nome}: {campo} = {eu[campo]!r}, contrato = {m[campo]!r}"


def test_codigos_de_erro_iguais_aos_dados_falsos():
    conferidos = 0
    for nome, info in INDICE.items():
        if info["rota"] in ROTAS_C2A and info["tipo"] == "resposta" and not info["status"].startswith("2"):
            codigo = _mock(nome)["codigo"]
            assert codigo in erros.CODIGOS, f"{nome}: código {codigo!r} não existe na API"
            assert erros.CODIGOS[codigo][0] == int(info["status"]), nome
            conferidos += 1
    assert conferidos >= 4


def test_codigos_da_api_existem_no_contrato():
    faltam = [c for c in erros.CODIGOS_DO_C2A if c not in TEXTO_CONTRATO]
    assert not faltam, f"códigos que o contrato não conhece: {faltam}"


# ------------------------------------------------------------ token fora de log

def test_token_nunca_aparece_em_log(caplog, capsys):
    caplog.set_level(logging.DEBUG)
    _pessoa()
    with _novo() as c:
        eu = _logar(c).json()
        token = c.cookies.get(COOKIE)
        c.get(EU)
        c.post(TROCAR, json={"senha_atual": ERRADA, "senha_nova": NOVA},
               headers={CABECALHO_CSRF: eu["csrf"]})
        c.post(SAIR, headers={CABECALHO_CSRF: eu["csrf"]})
    saida = capsys.readouterr()
    for texto in (caplog.text, saida.out, saida.err):
        assert token not in texto and sessoes._hash(token) not in texto
    conexao = conectar()
    try:
        guardado = json.dumps([dict(l) for l in conexao.execute("SELECT * FROM acessos")]
                              + [dict(l) for l in conexao.execute("SELECT * FROM registro_acoes")],
                              default=str)
    finally:
        conexao.close()
    assert token not in guardado

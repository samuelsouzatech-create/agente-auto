"""
C2e: o contrato nunca fica velho.
- docs/api/openapi.json commitado = descrição real da API (python -m app.api_painel.exportar);
- as rotas da API = as do openapi.yaml, menos a lista AINDA_NAO_IMPLEMENTADAS (que só encolhe);
- os parâmetros de cada rota (URL e caminho) = os do contrato; nenhum loja_id;
- só login, esqueci-senha, criar-senha e /v/{token} são públicas; as outras exigem login;
- o papel de cada rota bate com o x-papeis do contrato (403 para quem não está na lista);
- cada rota real responde no formato do openapi.yaml, num caminho completo de uso;
- todo código de erro da API existe no contrato.
Tudo offline, banco temporário do conftest.
"""
import json

from app import autenticacao, interesse, sessoes
from app.api_painel import erros
from app.api_painel.dependencias import CABECALHO_CSRF, COOKIE
from app.api_painel.exportar import ARQUIVO, descricao_real
from app.api_painel.main import PREFIXO, criar_app
from app.lojas import carregar_loja, salvar_config
from app.relogio import agora_utc, hora_local
from tests.test_c2a_api_acesso import DOC, _novo, _rotas_da_app, _validar
from tests.test_c2c_conversas import (LEAD1, LEAD2, _carro, _conversa_basica, _ha, _handoff,
                                      _msg, _no_ar, envios)

SENHA, NOVA = "Carro-Azul-2026", "Moto-Verde-2027"
LEAD3 = "5581999990003"
METODOS = ("get", "post", "put", "patch", "delete")
PAPEIS = ("dono", "gestor", "vendedor", "vendedor_link")
PUBLICAS = {("POST", "/auth/login"), ("POST", "/auth/esqueci-senha"),
            ("POST", "/auth/criar-senha"), ("GET", "/v/{token}")}
# Rotas do contrato que ainda não existem. Cada parte que entrega tira as suas daqui.
AINDA_NAO_IMPLEMENTADAS = {
    ("GET", "/v/{token}"): "C3",
}
CARRO = {"marca": "Hyundai", "modelo": "HB20 Comfort", "ano": 2020, "km": 48000,
         "cor": "Prata", "cambio": "Manual", "preco": 62900, "status": "disponivel",
         "fotos": ["https://fotos.exemplo.example/hb20-1.jpg"]}


# ------------------------------------------------------------ ajudantes

def _do_contrato():
    return {(m.upper(), p): op for p, ops in DOC["paths"].items()
            for m, op in ops.items() if m in METODOS}


def _da_api():
    """(MÉTODO, rota sem o /api/v1) de cada rota real."""
    return {(m, p.removeprefix(PREFIXO)) for m, p in _rotas_da_app()}


def _preencher(rota):
    return rota.replace("{lead}", LEAD1).replace("{id}", "999999")


def _parametros(op, componentes):
    saida = set()
    for p in op.get("parameters", []):
        if "$ref" in p:
            p = componentes[p["$ref"].split("/")[-1]]
        if p["in"] in ("query", "path"):
            saida.add((p["in"], p["name"]))
    return saida


def _sessao(uid, papel):
    if papel == sessoes.PAPEL_LINK:
        token = sessoes.criar_sessao(uid, 1, papel, escopo="link", lead_id=LEAD1)
    else:
        token = sessoes.criar_sessao(uid, 1, papel)
    return {"Cookie": f"{COOKIE}={token}", CABECALHO_CSRF: sessoes.csrf_da(token)}


def _modulos_ligados():
    salvar_config(1, {"modulos.remarketing": True, "modulos.estoque": True}, "teste")


# ------------------------------------------------------------ o contrato não fica velho

def test_openapi_json_commitado_igual_a_api_real():
    assert ARQUIVO.exists(), "Falta docs/api/openapi.json. Rode: python -m app.api_painel.exportar"
    gravado = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    assert gravado == descricao_real(), (
        "A API mudou e docs/api/openapi.json ficou velho. "
        "Rode: python -m app.api_painel.exportar e commite o arquivo.")


def test_rotas_da_api_iguais_as_do_contrato():
    contrato, api = set(_do_contrato()), _da_api()
    pendentes = set(AINDA_NAO_IMPLEMENTADAS)
    assert pendentes <= contrato, f"na lista, mas fora do contrato: {sorted(pendentes - contrato)}"
    assert not (api - contrato), f"rotas da API fora do contrato: {sorted(api - contrato)}"
    faltam = contrato - api - pendentes
    assert not faltam, f"rotas do contrato que a API não tem: {sorted(faltam)}"
    feitas = pendentes & api
    assert not feitas, f"já existem, tire de AINDA_NAO_IMPLEMENTADAS: {sorted(feitas)}"


def test_parametros_de_cada_rota_iguais_ao_contrato():
    real = criar_app().openapi()["paths"]
    componentes = DOC["components"]["parameters"]
    diferentes = []
    for metodo, rota in sorted(_da_api()):
        na_api = _parametros(real[PREFIXO + rota][metodo.lower()], {})
        no_contrato = _parametros(DOC["paths"][rota][metodo.lower()], componentes)
        if na_api != no_contrato:
            diferentes.append(f"{metodo} {rota}: API {sorted(na_api)} x contrato {sorted(no_contrato)}")
        assert all(nome != "loja_id" for _, nome in na_api), f"{metodo} {rota} recebe loja_id"
    assert not diferentes, "\n".join(diferentes)


def test_so_as_quatro_rotas_publicas():
    publicas = {k for k, op in _do_contrato().items() if op.get("x-papeis") == ["publico"]}
    assert publicas == PUBLICAS
    for chave, op in _do_contrato().items():
        assert (op.get("security") == []) == (chave in PUBLICAS), chave


def test_toda_rota_nao_publica_exige_login():
    with _novo() as c:
        for metodo, rota in sorted(_da_api() - PUBLICAS):
            r = c.request(metodo, PREFIXO + _preencher(rota), json={})
            assert r.status_code == 401, f"{metodo} {rota}: {r.status_code}"
            assert r.json()["codigo"] == "nao_autenticado", f"{metodo} {rota}"


def test_papel_de_cada_rota_bate_com_x_papeis():
    _modulos_ligados()
    uids = {p: autenticacao.criar_usuario_com_login(
                1, f"Pessoa {p}", "vendedor" if p == sessoes.PAPEL_LINK else p, f"{p}@c2e.com", SENHA)
            for p in PAPEIS}
    errados = []
    with _novo() as c:
        for metodo, rota in sorted(_da_api() - PUBLICAS):
            pode = set(_do_contrato()[(metodo, rota)]["x-papeis"])
            for papel in PAPEIS:
                r = c.request(metodo, PREFIXO + _preencher(rota), json={},
                              headers=_sessao(uids[papel], papel))
                barrado = r.status_code == 403 and r.json().get("codigo") == "sem_permissao"
                if r.status_code == 401 or barrado == (papel in pode):
                    errados.append(f"{metodo} {rota} como {papel}: {r.status_code} {r.text[:120]}")
    assert not errados, "\n".join(errados)


def test_codigos_de_erro_da_api_existem_no_contrato():
    enum = set(DOC["components"]["schemas"]["Erro"]["properties"]["codigo"]["enum"])
    assert set(erros.CODIGOS) <= enum, f"fora do contrato: {sorted(set(erros.CODIGOS) - enum)}"


# ------------------------------------------------------------ cada resposta real no formato

def test_cada_rota_real_responde_no_formato_do_contrato(envios):
    _modulos_ligados()
    _no_ar()
    autenticacao.criar_usuario_com_login(1, "Dona Teste", "dono", "dona@c2e.com", SENHA)
    hoje = hora_local(carregar_loja(1), agora_utc()).date().isoformat()
    conversa = "/conversas/{lead}"
    vistos = set()

    with _novo() as c:
        def chamar(metodo, rota, esperado, url=None, **kw):
            r = c.request(metodo, PREFIXO + (url or rota), **kw)
            assert r.status_code in esperado, f"{metodo} {url or rota}: {r.status_code} {r.text[:200]}"
            _validar(rota, metodo.lower(), r)
            vistos.add((metodo, rota))
            return r

        eu = chamar("POST", "/auth/login", (200,), json={"email": "dona@c2e.com", "senha": SENHA})
        h = {CABECALHO_CSRF: eu.json()["csrf"]}
        chamar("GET", "/auth/eu", (200,))
        chamar("GET", "/saude", (200,))

        _conversa_basica(lead=LEAD1)
        _handoff(1, LEAD1, "aguardando_humano", _ha(20), motivo="Quer ver o carro")
        chamar("GET", "/atender", (200,))
        chamar("GET", conversa, (200,), url=f"/conversas/{LEAD1}")
        chamar("POST", conversa + "/assumir", (200,), url=f"/conversas/{LEAD1}/assumir", headers=h)
        chamar("POST", conversa + "/responder", (200,), url=f"/conversas/{LEAD1}/responder",
               headers=h, json={"texto": "Oi, aqui é a Dona."})
        chamar("POST", conversa + "/devolver", (200,), url=f"/conversas/{LEAD1}/devolver", headers=h)
        chamar("POST", conversa + "/registrar-venda", (200,), url=f"/conversas/{LEAD1}/registrar-venda",
               headers=h, json={"carro_id": _carro(), "data_venda": hoje, "forma_pagamento": "avista"})

        _msg(1, LEAD2, "cliente", "Para de me mandar mensagem", _ha(5))
        interesse.registrar_situacao(1, LEAD2, "nao_contatar", canal="whatsapp")
        chamar("POST", conversa + "/reativar-contato", (200,),
               url=f"/conversas/{LEAD2}/reativar-contato", headers=h)

        chamar("GET", "/leads", (200,))
        chamar("GET", "/leads", (422,), url="/leads?periodo=abc")
        chamar("GET", "/resultado", (200,))
        chamar("GET", "/resultado", (422,), url="/resultado?visao=ano")

        chamar("GET", "/acompanhamento", (200,))
        chamar("POST", "/acompanhamento/pausar", (200,), headers=h, json={"motivo": "Feriado"})
        chamar("POST", "/acompanhamento/retomar", (200,), headers=h)
        _msg(1, LEAD3, "cliente", "Oi, tem Onix?", _ha(15))
        b = chamar("POST", "/bloqueios", (201,), headers=h, json={"lead": LEAD3, "tipo": "todos"})
        chamar("DELETE", "/bloqueios/{id}", (204,), url=f"/bloqueios/{b.json()['id']}", headers=h)

        chamar("GET", "/estoque", (200,))
        chamar("GET", "/estoque", (422,), url="/estoque?pagina=abc")
        novo = chamar("POST", "/estoque", (201,), headers=h, json=CARRO)
        chamar("PUT", "/estoque/{id}", (200,), url=f"/estoque/{novo.json()['id']}", headers=h,
               json={"dados": {**CARRO, "preco": 61900}})

        chamar("POST", "/auth/trocar-senha", (200, 204), headers=h,
               json={"senha_atual": SENHA, "senha_nova": NOVA})
        chamar("POST", "/auth/esqueci-senha", (202,), json={"email": "dona@c2e.com"})
        chamar("POST", "/auth/criar-senha", (422,), json={"token": "x" * 43, "senha_nova": NOVA})
        chamar("POST", "/auth/logout", (204,), headers=h)

    faltou = _da_api() - vistos
    assert not faltou, f"rotas sem cenário neste teste (acrescente): {sorted(faltou)}"

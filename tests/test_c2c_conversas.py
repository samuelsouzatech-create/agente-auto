"""
C2c (Plano Mestre, bloco C2): uma conversa e as ações do vendedor.
- conversa igual aos dados falsos (aguardando, assumida, janela fechada, loja em teste);
- assumir (com Registro), já assumida por outra pessoa (409), responder (vazia, sem
  assumir, janela fechada), devolver (quem pode), registrar venda (com Registro);
- D6: em loja Em teste o vendedor responde pelo painel, e o Léo só fala com número de teste;
- vendedor do link só a conversa dele; outra loja 404; CSRF; sem login 401;
- D3: o número do cliente não aparece no log de acesso.
Tudo offline: o envio de verdade é trocado por um falso. Banco temporário do conftest.
"""
import itertools
import json
import logging
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from banco import conectar
from app import autenticacao, envio_painel, estado_loja, sessoes
from app.api_painel import erros, logs
from app.api_painel.dependencias import CABECALHO_CSRF, COOKIE
from app.api_painel.main import PREFIXO, criar_app
from app.lojas import criar_loja, salvar_config
from app.relogio import agora_utc, para_banco

RAIZ = Path(__file__).resolve().parent.parent
API = RAIZ / "docs" / "api"
DOC = yaml.safe_load((API / "openapi.yaml").read_text(encoding="utf-8"))
INDICE = json.loads((API / "mocks" / "_indice.json").read_text(encoding="utf-8"))
SENHA = "Carro-Azul-2026"
LEAD1, LEAD2, LEAD_REAL = "5581999990001", "5581999990002", "5581988887777"
CONVERSA = PREFIXO + "/conversas/"
ROTA = "/conversas/{lead}"
_contador = itertools.count(1)


# ------------------------------------------------------------ ajudantes

@pytest.fixture(autouse=True)
def envios(monkeypatch):
    """Troca o envio de verdade (WhatsApp/Telegram) por um falso que só anota."""
    enviados = []

    async def falso(loja_id, canal, lead_id, texto):
        enviados.append((loja_id, canal, lead_id, texto))
        return True

    monkeypatch.setattr(envio_painel, "_despachar", falso)
    return enviados


@pytest.fixture
def cliente():
    with TestClient(criar_app(), base_url="https://testserver") as c:
        yield c


def _url(lead, acao=""):
    return f"{CONVERSA}{lead}" + (f"/{acao}" if acao else "")


def _ha(minutos):
    return para_banco(agora_utc() - timedelta(minutes=minutos))


def _executar(sql, parametros=()):
    conexao = conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


def _linha(sql, parametros=()):
    conexao = conectar()
    try:
        linha = conexao.execute(sql, parametros).fetchone()
        return tuple(linha) if linha else None
    finally:
        conexao.close()


def _um(sql, parametros=()):
    linha = _linha(sql, parametros)
    return linha[0] if linha else None


def _mock(nome):
    return json.loads((API / "mocks" / nome).read_text(encoding="utf-8"))


def _entrar(loja=1, papel="gestor", nome=None, lead_link=LEAD1):
    n = next(_contador)
    nome = nome or f"Pessoa {n}"
    papel_pessoa = "vendedor" if papel == sessoes.PAPEL_LINK else papel
    uid = autenticacao.criar_usuario_com_login(loja, nome, papel_pessoa, f"pessoa{n}@loja.com", SENHA)
    if papel == sessoes.PAPEL_LINK:
        token = sessoes.criar_sessao(uid, loja, papel, escopo="link", lead_id=lead_link)
    else:
        token = sessoes.criar_sessao(uid, loja, papel)
    return {"Cookie": f"{COOKIE}={token}", CABECALHO_CSRF: sessoes.csrf_da(token)}


def _no_ar(loja=1):
    _executar("INSERT INTO estado_lojas (loja_id, estado, no_ar_em, alterado_por, atualizado_em) "
              "VALUES (?, 'no_ar', '2026-11-01 12:00:00', 'Teste', '2026-11-01 12:00:00') "
              "ON CONFLICT (loja_id) DO UPDATE SET estado = 'no_ar'", (loja,))


def _em_teste(loja=1):
    _executar("DELETE FROM estado_lojas WHERE loja_id = ?", (loja,))


def _msg(loja, lead, direcao, texto, quando, canal="whatsapp"):
    _executar("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo, autor, "
              "criado_em) VALUES (?, ?, ?, ?, 'texto', ?, NULL, ?)",
              (lead, loja, canal, direcao, texto, quando))


def _handoff(loja, lead, estado, quando, vendedor=None, motivo=""):
    _executar("INSERT INTO handoffs (loja_id, lead_id, motivo, resumo, estado, vendedor, "
              "criado_em, assumido_em) VALUES (?, ?, ?, '', ?, ?, ?, ?)",
              (loja, lead, motivo, estado, vendedor, quando,
               quando if estado == "humano_assumiu" else None))


def _conversa_basica(loja=1, lead=LEAD1, minutos=30):
    _msg(loja, lead, "cliente", "Oi, o HB20 2020 ainda está disponível?", _ha(minutos))
    _msg(loja, lead, "leo", "Está sim! Quer ver ele pessoalmente?", _ha(minutos - 1))


def _carro(loja=1):
    conexao = conectar()
    try:
        novo = conexao.execute(
            "INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) "
            "VALUES (?, 'Hyundai', 'HB20 Comfort', 2020, 48000, 'Prata', 'Manual', 62900, 'disponivel')",
            (loja,)).lastrowid
        conexao.commit()
    finally:
        conexao.close()
    return novo


def _esquema(rota, metodo, status):
    resp = DOC["paths"][rota][metodo]["responses"][status]
    while "$ref" in resp:
        resp = DOC["components"]["responses"][resp["$ref"].split("/")[-1]]
    return resp.get("content", {}).get("application/json", {}).get("schema")


def _validar(rota, metodo, resposta):
    """A resposta real obedece ao openapi.yaml (mesma ideia do conferir_mocks.py)."""
    status = str(resposta.status_code)
    assert status in DOC["paths"][rota][metodo]["responses"], f"{metodo} {rota} não prevê {status}"
    esquema = _esquema(rota, metodo, status)
    raiz = {**esquema, "components": DOC["components"]}
    problemas = [f"{'/'.join(map(str, e.path)) or '$'}: {e.message}"
                 for e in Draft202012Validator(raiz).iter_errors(resposta.json())]
    assert not problemas, f"{metodo.upper()} {rota} {status} fora do contrato: {problemas}"


# ------------------------------------------------------------ ver a conversa

def test_conversa_aguardando_igual_ao_dado_falso(cliente):
    _no_ar()
    _conversa_basica()
    _handoff(1, LEAD1, "aguardando_humano", _ha(20), motivo="Quer ver o carro e fechar a entrada")
    r = cliente.get(_url(LEAD1), headers=_entrar())
    assert r.status_code == 200, r.text
    _validar(ROTA, "get", r)
    corpo, m = r.json(), _mock("conversas_lead__aguardando.json")
    assert sorted(corpo) == sorted(m)
    assert sorted(corpo["cliente"]) == sorted(m["cliente"])
    assert sorted(corpo["mensagens"][0]) == sorted(m["mensagens"][0])
    assert [x["de"] for x in corpo["mensagens"]] == ["cliente", "leo"]
    assert (corpo["estado_do_chamado"], corpo["assumido_por"], corpo["aviso"]) == ("aguardando", None, None)
    assert corpo["acoes"] == m["acoes"]
    assert corpo["atualizar_em_segundos"] == m["atualizar_em_segundos"] == 10
    assert corpo["cliente"]["motivo_do_chamado"] == "Quer ver o carro e fechar a entrada"
    assert corpo["janela"]["aberta"] is True


def test_conversa_assumida_por_mim_igual_ao_dado_falso(cliente):
    _no_ar()
    _conversa_basica()
    _handoff(1, LEAD1, "humano_assumiu", _ha(20), vendedor="Ricardo Alves")
    r = cliente.get(_url(LEAD1), headers=_entrar(papel="vendedor", nome="Ricardo Alves"))
    assert r.status_code == 200, r.text
    _validar(ROTA, "get", r)
    corpo, m = r.json(), _mock("conversas_lead__assumida.json")
    assert (corpo["estado_do_chamado"], corpo["assumido_por"]) == ("humano_assumiu", "Ricardo Alves")
    assert corpo["acoes"] == m["acoes"]


def test_janela_fechada_igual_ao_dado_falso_e_responder_recusa(cliente, envios):
    _no_ar()
    _conversa_basica(minutos=2 * 24 * 60)
    _handoff(1, LEAD1, "humano_assumiu", _ha(60), vendedor="Ricardo Alves")
    h = _entrar(papel="vendedor", nome="Ricardo Alves")
    corpo = cliente.get(_url(LEAD1), headers=h).json()
    m = _mock("conversas_lead__janela_fechada.json")
    assert corpo["janela"] == m["janela"]
    assert corpo["acoes"] == m["acoes"]
    r = cliente.post(_url(LEAD1, "responder"), json={"texto": "Oi!"}, headers=h)
    assert r.status_code == 409
    _validar(ROTA + "/responder", "post", r)
    assert r.json() == _mock("conversas_responder__janela_fechada.json")
    assert envios == []


def test_loja_em_teste_aviso_e_vendedor_responde_d6(cliente, envios):
    _em_teste()
    _conversa_basica()
    _handoff(1, LEAD1, "aguardando_humano", _ha(20))
    h = _entrar(papel="vendedor", nome="Ricardo Alves")
    corpo = cliente.get(_url(LEAD1), headers=h).json()
    m = _mock("conversas_lead__loja_em_teste.json")
    assert corpo["aviso"] == m["aviso"]
    assert corpo["acoes"] == m["acoes"]
    # D6 = A: em teste, o vendedor continua respondendo pelo painel, como hoje
    assert cliente.post(_url(LEAD1, "assumir"), headers=h).status_code == 200
    r = cliente.post(_url(LEAD1, "responder"), json={"texto": "Oi, aqui é o Ricardo."}, headers=h)
    assert r.status_code == 200, r.text
    assert envios == [(1, "whatsapp", LEAD1, "Oi, aqui é o Ricardo.")]
    # ... e o Léo só fala com número de teste: cliente real não passa da porta
    estado_loja.cadastrar_numero_de_teste(1, "whatsapp", LEAD1, "Celular de teste")
    assert estado_loja.pode_responder(1, "whatsapp", LEAD1) is True
    assert estado_loja.pode_responder(1, "whatsapp", LEAD_REAL) is False


# ------------------------------------------------------------ assumir e responder

def test_assumir_responder_e_registro(cliente, envios):
    _no_ar()
    _conversa_basica()
    h = _entrar(papel="vendedor", nome="Bruno Lima")
    r = cliente.post(_url(LEAD1, "assumir"), headers=h)
    assert r.status_code == 200, r.text
    _validar(ROTA + "/assumir", "post", r)
    assert (r.json()["estado_do_chamado"], r.json()["assumido_por"]) == ("humano_assumiu", "Bruno Lima")
    assert r.json()["acoes"]["responder"] == {"permitida": True, "motivo": None}
    assert _linha("SELECT pessoa, origem FROM registro_acoes WHERE acao = 'assumir_conversa'") == (
        "Bruno Lima", "api")
    assert cliente.post(_url(LEAD1, "assumir"), headers=h).status_code == 200   # continua com você

    vazia = cliente.post(_url(LEAD1, "responder"), json={"texto": "   "}, headers=h)
    assert vazia.status_code == 422
    _validar(ROTA + "/responder", "post", vazia)
    assert vazia.json() == _mock("conversas_responder__vazia.json")

    texto = "Posso te receber amanhã às 10h?"
    r = cliente.post(_url(LEAD1, "responder"), json={"texto": texto, "loja_id": 2}, headers=h)
    assert r.status_code == 200, r.text
    _validar(ROTA + "/responder", "post", r)
    msg = r.json()
    assert sorted(msg) == sorted(_mock("conversas_responder__ok.json"))
    assert (msg["de"], msg["autor"], msg["texto"], msg["canal"]) == ("vendedor", "Bruno Lima", texto, "whatsapp")
    assert envios == [(1, "whatsapp", LEAD1, texto)]
    assert cliente.get(_url(LEAD1), headers=h).json()["mensagens"][-1]["id"] == msg["id"]


def test_assumir_conversa_de_outra_pessoa_e_409(cliente):
    _no_ar()
    _conversa_basica()
    _handoff(1, LEAD1, "humano_assumiu", _ha(20), vendedor="Ricardo Alves")
    r = cliente.post(_url(LEAD1, "assumir"), headers=_entrar(nome="Ana Lima"))
    assert r.status_code == 409
    _validar(ROTA + "/assumir", "post", r)
    assert r.json() == _mock("conversas_assumir__ja_assumida.json")
    assert _um("SELECT vendedor FROM handoffs WHERE lead_id = ? AND estado != 'encerrado'",
               (LEAD1,)) == "Ricardo Alves"


def test_responder_sem_assumir_e_recusado(cliente, envios):
    _no_ar()
    _conversa_basica()
    _handoff(1, LEAD1, "aguardando_humano", _ha(20))
    r = cliente.post(_url(LEAD1, "responder"), json={"texto": "Oi"}, headers=_entrar())
    assert r.status_code == 422
    _validar(ROTA + "/responder", "post", r)
    assert r.json()["mensagem"] == "Assuma a conversa antes de responder."
    assert envios == []


# ------------------------------------------------------------ devolver

def test_devolver(cliente):
    _no_ar()
    _conversa_basica()
    _handoff(1, LEAD1, "humano_assumiu", _ha(20), vendedor="Bruno Lima")
    r = cliente.post(_url(LEAD1, "devolver"), headers=_entrar(papel="vendedor", nome="Carla Dias"))
    assert r.status_code == 403
    _validar(ROTA + "/devolver", "post", r)
    assert r.json()["mensagem"] == "Esta conversa está com Bruno Lima."

    bruno = _entrar(papel="vendedor", nome="Bruno Lima")
    r = cliente.post(_url(LEAD1, "devolver"), headers=bruno)
    assert r.status_code == 200, r.text
    _validar(ROTA + "/devolver", "post", r)
    corpo = r.json()
    assert (corpo["estado_do_chamado"], corpo["assumido_por"]) == ("nenhum", None)
    assert corpo["acoes"] == _mock("conversas_devolver__ok.json")["acoes"]
    assert _linha("SELECT pessoa, origem FROM registro_acoes WHERE acao = 'devolver_ao_agente'") == (
        "Bruno Lima", "api")
    assert cliente.post(_url(LEAD1, "devolver"), headers=bruno).status_code == 200   # nada aberto
    assert _um("SELECT COUNT(*) FROM registro_acoes WHERE acao = 'devolver_ao_agente'") == 1


def test_gerente_devolve_conversa_de_outra_pessoa(cliente):
    _no_ar()
    _conversa_basica(lead=LEAD1)
    _conversa_basica(lead=LEAD2)
    _handoff(1, LEAD1, "humano_assumiu", _ha(20), vendedor="Bruno Lima")
    _handoff(1, LEAD2, "aguardando_humano", _ha(20))
    camila = _entrar(papel="gestor", nome="Camila Rocha")
    r = cliente.post(_url(LEAD2, "devolver"), headers=camila)
    assert r.status_code == 403 and r.json()["mensagem"] == "A conversa ainda não foi assumida."
    assert cliente.post(_url(LEAD1, "devolver"), headers=camila).status_code == 200
    assert _linha("SELECT pessoa, origem FROM registro_acoes WHERE acao = 'devolver_ao_agente'") == (
        "Camila Rocha", "api")


# ------------------------------------------------------------ registrar venda

def test_registrar_venda(cliente):
    _no_ar()
    _conversa_basica()
    salvar_config(1, {"modulos.pos_venda": False}, "teste")
    carro = _carro()
    h = _entrar(papel="vendedor", nome="Ricardo Alves")
    ontem = date.today() - timedelta(days=1)
    pedido = {**_mock("pedido_registrar_venda.json"), "carro_id": carro,
              "data_venda": ontem.isoformat(), "loja_id": 2}
    r = cliente.post(_url(LEAD1, "registrar-venda"), json=pedido, headers=h)
    assert r.status_code == 200, r.text
    _validar(ROTA + "/registrar-venda", "post", r)
    corpo = r.json()
    assert sorted(corpo) == sorted(_mock("conversas_registrar_venda__ok.json"))
    assert corpo["carro"] == "Hyundai HB20 Comfort 2020"
    assert (corpo["data"], corpo["forma"]) == (ontem.strftime("%d/%m/%Y"), "Financiado em 48 meses")
    assert [e["codigo"] for e in corpo["efeitos"]] == ["venda", "resultado", "baixa_no_estoque"]
    assert _um("SELECT status FROM estoque WHERE id = ?", (carro,)) == "vendido"
    assert _linha("SELECT vendedor, forma_pagamento, meses_financiamento FROM vendas "
                  "WHERE lead_id = ?", (LEAD1,)) == ("Ricardo Alves", "financiado", 48)
    assert _linha("SELECT pessoa, origem FROM registro_acoes WHERE acao = 'registrar_venda'") == (
        "Ricardo Alves", "api")
    de_novo = cliente.post(_url(LEAD1, "registrar-venda"), json=pedido, headers=h)
    assert de_novo.status_code == 422 and "carro_id" in de_novo.json()["campos"]


def test_venda_com_carro_de_outra_loja_e_recusada(cliente):
    loja2 = criar_loja("Garagem Dois")
    _conversa_basica()
    carro = _carro(loja2)
    ontem = (date.today() - timedelta(days=1)).isoformat()
    r = cliente.post(_url(LEAD1, "registrar-venda"), headers=_entrar(),
                     json={"carro_id": carro, "data_venda": ontem, "forma_pagamento": "avista"})
    assert r.status_code == 422
    _validar(ROTA + "/registrar-venda", "post", r)
    assert r.json() == _mock("conversas_registrar_venda__carro_invalido.json")
    assert _um("SELECT COUNT(*) FROM vendas") == 0


def test_financiado_sem_meses_e_recusado(cliente):
    _conversa_basica()
    carro = _carro()
    ontem = (date.today() - timedelta(days=1)).isoformat()
    r = cliente.post(_url(LEAD1, "registrar-venda"), headers=_entrar(),
                     json={"carro_id": carro, "data_venda": ontem, "forma_pagamento": "financiado"})
    assert r.status_code == 422
    assert set(r.json()["campos"]) == {"meses_financiamento"}
    assert _um("SELECT status FROM estoque WHERE id = ?", (carro,)) == "disponivel"


# ------------------------------------------------------------ quem pode, qual loja

def test_vendedor_do_link_so_ve_a_conversa_dele(cliente):
    _no_ar()
    _conversa_basica(lead=LEAD1)
    _conversa_basica(lead=LEAD2)
    h = _entrar(papel=sessoes.PAPEL_LINK, lead_link=LEAD1)
    assert cliente.get(_url(LEAD1), headers=h).status_code == 200
    r = cliente.get(_url(LEAD2), headers=h)
    assert r.status_code == 403
    _validar(ROTA, "get", r)
    assert r.json()["codigo"] == _mock("erro__link_escopo.json")["codigo"]
    for acao in ("assumir", "responder", "devolver", "registrar-venda"):
        assert cliente.post(_url(LEAD2, acao), json={}, headers=h).status_code == 403, acao


def test_conversa_inexistente_ou_de_outra_loja_e_404(cliente):
    loja2 = criar_loja("Garagem Dois")
    _conversa_basica(loja=loja2, lead=LEAD2)
    h = _entrar()
    for lead in ("5581900000000", LEAD2, "9" * 81):
        r = cliente.get(_url(lead), headers=h)
        assert r.status_code == 404, lead
        _validar(ROTA, "get", r)
        assert r.json() == _mock("conversas_lead__nao_encontrada.json")
    assert cliente.post(_url(LEAD2, "assumir"), headers=h).status_code == 404
    assert _um("SELECT COUNT(*) FROM handoffs WHERE loja_id = ?", (loja2,)) == 0


@pytest.mark.parametrize("acao", ["assumir", "responder", "devolver", "registrar-venda"])
def test_rotas_que_escrevem_exigem_csrf(cliente, acao):
    _conversa_basica()
    h = _entrar()
    r = cliente.post(_url(LEAD1, acao), json={"texto": "Oi"}, headers={"Cookie": h["Cookie"]})
    assert r.status_code == 403 and r.json()["codigo"] == "csrf_invalido"
    assert _um("SELECT COUNT(*) FROM handoffs WHERE lead_id = ?", (LEAD1,)) == 0


def test_sem_login_e_401(cliente):
    r = cliente.get(_url(LEAD1))
    assert r.status_code == 401
    _validar(ROTA, "get", r)


def test_codigos_de_erro_das_conversas_iguais_aos_dados_falsos():
    conferidos = 0
    for nome, info in INDICE.items():
        if (info["rota"].startswith("/conversas/") and info["tipo"] == "resposta"
                and not info["status"].startswith("2")):
            codigo = _mock(nome)["codigo"]
            assert codigo in erros.CODIGOS, f"{nome}: código {codigo!r} não existe na API"
            assert erros.CODIGOS[codigo][0] == int(info["status"]), nome
            conferidos += 1
    assert conferidos >= 5


# ------------------------------------------------------------ D3: log sem o número

def test_numero_do_cliente_nunca_aparece_no_log_de_acesso():
    criar_app()
    acesso = logging.getLogger("uvicorn.access")
    assert any(isinstance(f, logs.EsconderConversa) for f in acesso.filters)
    registro = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                                 ("127.0.0.1:5000", "POST", f"{CONVERSA}{LEAD1}/responder?x=1",
                                  "1.1", 200), None)
    for filtro in acesso.filters:
        filtro.filter(registro)
    texto = registro.getMessage()
    assert LEAD1 not in texto and "/conversas/***/responder" in texto

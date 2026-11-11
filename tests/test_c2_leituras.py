"""
C2 (leituras): GET /leads e GET /resultado, camada fina sobre app/painel_leitura (P4).
- vazio igual aos dados falsos; formato igual ao openapi.yaml;
- filtro por etapa, busca, período fora da lista, paginação;
- quem pode: vendedor vê Leads e não vê Resultado; vendedor do link não vê nenhum;
- Resultado: semana e mês, rótulo do período, loja em teste, dado inválido (422);
- o mesmo número de vendas em Leads e em Resultado;
- duas lojas; loja_id no pedido ignorado.
Tudo offline, banco temporário do conftest.
"""
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app import sessoes
from app.api_painel.main import PREFIXO, criar_app
from app.api_painel.resultado import periodo_da_visao, rotulo_do_periodo
from app.lojas import carregar_loja, criar_loja
from app.relogio import agora_utc, hora_local
from tests.test_c2c_conversas import (LEAD1, LEAD2, _carro, _conversa_basica, _em_teste,
                                      _entrar, _ha, _handoff, _mock, _msg, _no_ar, _validar)

LEADS, RESULTADO = PREFIXO + "/leads", PREFIXO + "/resultado"


@pytest.fixture
def cliente():
    with TestClient(criar_app(), base_url="https://testserver") as c:
        yield c


def _hoje():
    return hora_local(carregar_loja(1), agora_utc()).date()


def _dois_clientes():
    """LEAD1 esperando o vendedor; LEAD2 acabou de chegar (Novo)."""
    _no_ar()
    _conversa_basica(lead=LEAD1, minutos=30)
    _handoff(1, LEAD1, "aguardando_humano", _ha(20), motivo="Quer ver o carro")
    _msg(1, LEAD2, "cliente", "Oi, vocês têm Onix?", _ha(10))
    _msg(1, LEAD2, "leo", "Temos sim!", _ha(9))


# ------------------------------------------------------------ Leads

def test_leads_vazio_igual_ao_dado_falso(cliente):
    r = cliente.get(LEADS, headers=_entrar())
    assert r.status_code == 200, r.text
    _validar("/leads", "get", r)
    assert r.json() == _mock("leads__vazio.json")


def test_leads_com_dados_no_formato_do_contrato(cliente):
    _dois_clientes()
    r = cliente.get(LEADS, headers=_entrar())
    assert r.status_code == 200, r.text
    _validar("/leads", "get", r)
    corpo, m = r.json(), _mock("leads__com_dados.json")
    assert sorted(corpo) == sorted(m)
    assert all(sorted(item) == sorted(m["itens"][0]) for item in corpo["itens"])
    assert [i["lead"] for i in corpo["itens"]] == [LEAD2, LEAD1]        # mais recente primeiro
    assert [i["etapa"] for i in corpo["itens"]] == ["novo", "com_vendedor"]
    assert corpo["itens"][0]["nome"] == "(81) 9 9999-0002"             # sem nome: telefone formatado
    assert corpo["itens"][0]["origem"] == "WhatsApp"
    assert datetime.fromisoformat(corpo["itens"][0]["ultimo_contato"]["iso"]).utcoffset() is not None
    assert ([c["etapa"] for c in corpo["contagem_por_etapa"]]
            == [c["etapa"] for c in m["contagem_por_etapa"]])
    contagem = {c["etapa"]: c["total"] for c in corpo["contagem_por_etapa"]}
    assert (contagem["novo"], contagem["com_vendedor"], sum(contagem.values())) == (1, 1, 2)
    assert (corpo["total"], corpo["periodo_dias"]) == (2, 30)


def test_leads_filtro_busca_periodo_e_paginacao(cliente):
    _dois_clientes()
    h = _entrar()
    so_novos = cliente.get(LEADS, params={"etapa": "novo"}, headers=h).json()
    assert [i["lead"] for i in so_novos["itens"]] == [LEAD2] and so_novos["total"] == 1
    assert sum(c["total"] for c in so_novos["contagem_por_etapa"]) == 2   # contagem do período todo
    busca = cliente.get(LEADS, params={"busca": "990002"}, headers=h).json()
    assert [i["lead"] for i in busca["itens"]] == [LEAD2]
    longa = cliente.get(LEADS, params={"busca": "x" * 200}, headers=h)
    assert longa.status_code == 200 and longa.json()["total"] == 0
    assert cliente.get(LEADS, params={"periodo": 7}, headers=h).json()["periodo_dias"] == 7
    assert cliente.get(LEADS, params={"periodo": 15}, headers=h).json()["periodo_dias"] == 30
    p = cliente.get(LEADS, params={"tamanho": 1}, headers=h).json()
    assert (p["pagina"], p["paginas"], p["total"], p["tamanho"], len(p["itens"])) == (1, 2, 2, 1, 1)
    p2 = cliente.get(LEADS, params={"tamanho": 1, "pagina": 99}, headers=h)
    _validar("/leads", "get", p2)
    assert p2.json()["pagina"] == 2 and p2.json()["itens"][0]["lead"] == LEAD1
    assert cliente.get(LEADS, params={"tamanho": 500}, headers=h).json()["tamanho"] == 100


def test_leads_quem_pode(cliente):
    assert cliente.get(LEADS, headers=_entrar(papel="vendedor")).status_code == 200
    r = cliente.get(LEADS, headers=_entrar(papel=sessoes.PAPEL_LINK))
    assert r.status_code == 403
    _validar("/leads", "get", r)
    assert r.json()["codigo"] == _mock("erro__link_escopo.json")["codigo"]
    assert cliente.get(LEADS).status_code == 401


# ------------------------------------------------------------ Resultado

def test_resultado_vazio_igual_ao_dado_falso(cliente):
    _no_ar()
    r = cliente.get(RESULTADO, params={"visao": "semana", "data": "2026-11-04"}, headers=_entrar())
    assert r.status_code == 200, r.text
    _validar("/resultado", "get", r)
    assert r.json() == _mock("resultado__vazio.json")


def test_resultado_loja_em_teste_avisa(cliente):
    _em_teste()
    _msg(1, LEAD2, "cliente", "Oi", _ha(10))
    r = cliente.get(RESULTADO, headers=_entrar())
    assert r.status_code == 200, r.text
    _validar("/resultado", "get", r)
    corpo = r.json()
    assert sorted(corpo) == sorted(_mock("resultado__loja_em_teste.json"))
    assert corpo["dados_de_teste"] is True and corpo["conversas_atendidas"] == 1


@pytest.mark.parametrize("visao, dia, inicio, fim, rotulo", [
    ("semana", date(2026, 11, 4), date(2026, 11, 2), date(2026, 11, 8), "2 a 8 de novembro"),
    ("semana", date(2026, 11, 1), date(2026, 10, 26), date(2026, 11, 1),
     "26 de outubro a 1 de novembro"),
    ("semana", date(2026, 1, 1), date(2025, 12, 29), date(2026, 1, 4),
     "29 de dezembro de 2025 a 4 de janeiro de 2026"),
    ("mes", date(2026, 2, 10), date(2026, 2, 1), date(2026, 2, 28), "fevereiro de 2026"),
])
def test_periodo_e_rotulo(visao, dia, inicio, fim, rotulo):
    assert periodo_da_visao(visao, dia) == (inicio, fim)
    assert rotulo_do_periodo(visao, inicio, fim) == rotulo


def test_resultado_mes_pela_api(cliente):
    _no_ar()
    r = cliente.get(RESULTADO, params={"visao": "mes", "data": "2026-02-10"}, headers=_entrar())
    assert r.status_code == 200, r.text
    _validar("/resultado", "get", r)
    corpo = r.json()
    assert corpo["periodo"] == {"inicio": "2026-02-01", "fim": "2026-02-28",
                                "rotulo": "fevereiro de 2026"}
    assert len(corpo["por_dia"]) == 28


@pytest.mark.parametrize("params, campo", [
    ({"visao": "ano"}, "visao"), ({"data": "ontem"}, "data"), ({"data": "1500-01-01"}, "data")])
def test_resultado_dado_invalido_422(cliente, params, campo):
    r = cliente.get(RESULTADO, params=params, headers=_entrar())
    assert r.status_code == 422, r.text
    _validar("/resultado", "get", r)
    assert r.json()["codigo"] == "invalido" and campo in r.json()["campos"]


def test_resultado_so_dono_e_gerente(cliente):
    for papel in ("dono", "gestor"):
        assert cliente.get(RESULTADO, headers=_entrar(papel=papel)).status_code == 200
    for papel in ("vendedor", sessoes.PAPEL_LINK):
        r = cliente.get(RESULTADO, headers=_entrar(papel=papel))
        assert r.status_code == 403, papel
        _validar("/resultado", "get", r)
        assert r.json()["codigo"] == _mock("erro__vendedor_sem_acesso.json")["codigo"]
    assert cliente.get(RESULTADO).status_code == 401


# ------------------------------------------------------------ juntos

def test_mesmo_numero_de_vendas_em_leads_e_resultado(cliente):
    _no_ar()
    _conversa_basica(lead=LEAD1, minutos=30)
    carro = _carro()
    h = _entrar()
    v = cliente.post(PREFIXO + f"/conversas/{LEAD1}/registrar-venda", headers=h,
                     json={"carro_id": carro, "data_venda": _hoje().isoformat(),
                           "forma_pagamento": "avista"})
    assert v.status_code == 200, v.text
    leads = cliente.get(LEADS, params={"periodo": 7}, headers=h).json()
    resultado = cliente.get(RESULTADO, headers=h).json()
    nas_leads = {c["etapa"]: c["total"] for c in leads["contagem_por_etapa"]}["venda_registrada"]
    funil = {f["etapa"]: f["total"] for f in resultado["funil"]}
    assert nas_leads == resultado["vendas_registradas"] == funil["vendas"] == 1


def test_duas_lojas_e_loja_id_no_pedido_ignorado(cliente):
    _no_ar()
    loja2 = criar_loja("Garagem Dois")
    _msg(loja2, LEAD2, "cliente", "Oi, loja dois", _ha(10))
    h1 = _entrar(loja=1)
    for params in ({}, {"loja_id": loja2}):
        assert cliente.get(LEADS, params=params, headers=h1).json()["total"] == 0
        assert cliente.get(RESULTADO, params=params, headers=h1).json()["conversas_atendidas"] == 0
    h2 = _entrar(loja=loja2)
    assert [i["lead"] for i in cliente.get(LEADS, headers=h2).json()["itens"]] == [LEAD2]

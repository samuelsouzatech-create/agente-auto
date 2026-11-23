"""
Maratona Painel 2, Q1 (contrato 1.1.0). Tudo offline, banco temporário, duas lojas.
- Mensagem.automatica: preenchida nas mensagens dos jobs (retomada, pós-venda, reativação);
- GET /conversas/{lead}/carros-para-venda: dono, gerente, vendedor e link (só a conversa dele);
  só carros não vendidos da loja da sessão; vale com o módulo Estoque desligado; loja B não vê A;
- Resultado: periodo.anterior e periodo.seguinte (seguinte null se ainda não começou);
- Login: limite por origem (revisão geral #5).
"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import autenticacao, sessoes
from app.api_painel.main import PREFIXO, criar_app
from app.lojas import salvar_config
from app.relogio import agora_utc
from tests.test_c2c_conversas import (LEAD1, LEAD2, SENHA, _carro, _conversa_basica, _entrar,
                                      _executar, _ha, _no_ar, _validar, envios)  # noqa: F401

ROTA = "/conversas/{lead}/carros-para-venda"


@pytest.fixture
def cliente():
    with TestClient(criar_app(), base_url="https://testserver") as c:
        yield c


def _url(lead):
    return f"{PREFIXO}/conversas/{lead}/carros-para-venda"


def _loja_b():
    _executar("INSERT INTO lojas (id, nome, segmento, config) VALUES (2, 'Loja B', 'veiculos', '{}')")
    _no_ar(2)


def _msg_auto(loja, lead, autor, texto, minutos):
    _executar("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo, autor, criado_em) "
              "VALUES (?, ?, 'whatsapp', 'leo', 'texto', ?, ?, ?)", (lead, loja, texto, autor, _ha(minutos)))


def _vendido(carro_id):
    _executar("UPDATE estoque SET status = 'vendido' WHERE id = ?", (carro_id,))


# ------------------------------------------------------------ mensagem automática

def test_mensagens_dos_jobs_vem_marcadas(cliente):
    _no_ar()
    _conversa_basica()
    _msg_auto(1, LEAD1, "remarketing", "Oi! O HB20 continua aqui.", 20)
    _msg_auto(1, LEAD1, "pos_venda", "Como está o carro?", 10)
    _msg_auto(1, LEAD1, "reativacao", "Faz tempo que não conversamos.", 5)
    r = cliente.get(f"{PREFIXO}/conversas/{LEAD1}", headers=_entrar())
    assert r.status_code == 200, r.text
    _validar("/conversas/{lead}", "get", r)
    marcas = [m["automatica"] for m in r.json()["mensagens"]]
    assert marcas == [None, None, {"tipo_rotulo": "Retomada"}, {"tipo_rotulo": "Pós-venda"},
                      {"tipo_rotulo": "Reativação"}]


def test_mensagem_do_vendedor_nunca_e_automatica(cliente):
    _no_ar()
    _conversa_basica()
    _executar("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo, autor, criado_em) "
              "VALUES (?, 1, 'whatsapp', 'vendedor', 'texto', 'Oi', 'remarketing', ?)", (LEAD1, _ha(1)))
    r = cliente.get(f"{PREFIXO}/conversas/{LEAD1}", headers=_entrar())
    assert r.json()["mensagens"][-1]["automatica"] is None


# ------------------------------------------------------------ carros para a venda

@pytest.mark.parametrize("papel", ["dono", "gestor", "vendedor", sessoes.PAPEL_LINK])
def test_todos_os_papeis_veem_os_carros_nao_vendidos(cliente, papel):
    _no_ar()
    _conversa_basica()
    a, b = _carro(), _carro()
    _vendido(b)
    r = cliente.get(_url(LEAD1), headers=_entrar(papel=papel))
    assert r.status_code == 200, r.text
    _validar(ROTA, "get", r)
    assert [c["id"] for c in r.json()["itens"]] == [a]


def test_mais_novo_primeiro(cliente):
    _no_ar()
    _conversa_basica()
    a, b = _carro(), _carro()
    r = cliente.get(_url(LEAD1), headers=_entrar(papel="vendedor"))
    assert [c["id"] for c in r.json()["itens"]] == [b, a]


def test_vale_com_o_modulo_estoque_desligado(cliente):
    _no_ar()
    salvar_config(1, {"modulos.estoque": False}, "teste")
    _conversa_basica()
    a = _carro()
    h = _entrar(papel="dono")
    assert cliente.get(f"{PREFIXO}/estoque", headers=h).status_code == 403
    r = cliente.get(_url(LEAD1), headers=h)
    assert r.status_code == 200 and [c["id"] for c in r.json()["itens"]] == [a]


def test_link_fora_da_conversa_e_recusado(cliente):
    _no_ar()
    _conversa_basica(lead=LEAD1)
    _conversa_basica(lead=LEAD2)
    _carro()
    r = cliente.get(_url(LEAD2), headers=_entrar(papel=sessoes.PAPEL_LINK, lead_link=LEAD1))
    assert r.status_code == 403
    assert r.json()["codigo"] == "sem_permissao"


def test_duas_lojas_cada_uma_com_os_seus_carros(cliente):
    _loja_b()
    _no_ar()
    _conversa_basica(loja=1, lead=LEAD1)
    _conversa_basica(loja=2, lead=LEAD2)
    carro_a, carro_b = _carro(1), _carro(2)
    dono_b = _entrar(loja=2, papel="dono")
    # conversa da loja A pedida pela loja B: não existe
    r = cliente.get(_url(LEAD1), headers=dono_b)
    assert r.status_code == 404 and r.json()["codigo"] == "nao_encontrado"
    # a lista da B só tem o carro da B
    r = cliente.get(_url(LEAD2), headers=dono_b)
    assert [c["id"] for c in r.json()["itens"]] == [carro_b]
    r = cliente.get(_url(LEAD1), headers=_entrar(loja=1, papel="dono"))
    assert [c["id"] for c in r.json()["itens"]] == [carro_a]


def test_conversa_que_nao_existe(cliente):
    _no_ar()
    _carro()
    r = cliente.get(_url("5581000000000"), headers=_entrar())
    assert r.status_code == 404


# ------------------------------------------------------------ períodos do Resultado

def test_semana_atual_nao_tem_seguinte(cliente):
    _no_ar()
    r = cliente.get(f"{PREFIXO}/resultado", headers=_entrar(papel="dono"))
    p = r.json()["periodo"]
    assert p["seguinte"] is None
    assert p["anterior"] < p["inicio"]


def test_semana_passada_aponta_as_duas_vizinhas(cliente):
    _no_ar()
    r = cliente.get(f"{PREFIXO}/resultado", params={"visao": "semana", "data": "2026-11-04"},
                    headers=_entrar(papel="dono"))
    p = r.json()["periodo"]
    assert (p["inicio"], p["fim"]) == ("2026-11-02", "2026-11-08")
    assert (p["anterior"], p["seguinte"]) == ("2026-11-01", "2026-11-09")
    # pedir a data "anterior" dá a semana anterior
    r = cliente.get(f"{PREFIXO}/resultado", params={"visao": "semana", "data": p["anterior"]},
                    headers=_entrar(papel="dono"))
    assert r.json()["periodo"]["fim"] == "2026-11-01"


def test_primeiro_ano_aceito_nao_tem_anterior(cliente):
    _no_ar()
    r = cliente.get(f"{PREFIXO}/resultado", params={"visao": "mes", "data": "2000-01-15"},
                    headers=_entrar(papel="dono"))
    assert r.json()["periodo"]["anterior"] is None


# ------------------------------------------------------------ login: limite por origem

def test_origem_que_errou_demais_fica_bloqueada_para_qualquer_email(cliente):
    autenticacao.criar_usuario_com_login(1, "Dona", "dono", "dona@loja.com", SENHA)
    for i in range(autenticacao.MAX_LOGIN_ERRADO_ORIGEM):
        r = cliente.post(f"{PREFIXO}/auth/login", json={"email": f"outro{i}@loja.com", "senha": "errada-123"})
        assert r.status_code == 401, (i, r.text)
    # mesmo com a senha certa de outro e-mail, a origem está bloqueada
    r = cliente.post(f"{PREFIXO}/auth/login", json={"email": "dona@loja.com", "senha": SENHA})
    assert r.status_code == 429 and r.json()["codigo"] == "muitas_tentativas"
    # e o e-mail da dona não ganhou nenhum erro (não foi bloqueado por tabela)
    assert not autenticacao.bloqueado_por_tentativas("dona@loja.com")


def test_outra_origem_nao_e_afetada():
    agora = agora_utc()
    for _ in range(autenticacao.MAX_LOGIN_ERRADO_ORIGEM):
        autenticacao.anotar_login_errado_da_origem("10.0.0.1", agora)
    assert autenticacao.origem_bloqueada("10.0.0.1", agora)
    assert not autenticacao.origem_bloqueada("10.0.0.2", agora)


def test_bloqueio_da_origem_passa_com_o_tempo():
    agora = agora_utc()
    for _ in range(autenticacao.MAX_LOGIN_ERRADO_ORIGEM):
        autenticacao.anotar_login_errado_da_origem("10.0.0.1", agora)
    depois = agora + timedelta(minutes=autenticacao.JANELA_TENTATIVAS_MIN + 1)
    assert not autenticacao.origem_bloqueada("10.0.0.1", depois)


def test_login_certo_nao_conta_como_erro_da_origem(cliente):
    autenticacao.criar_usuario_com_login(1, "Dona", "dono", "dona@loja.com", SENHA)
    for _ in range(autenticacao.MAX_LOGIN_ERRADO_ORIGEM + 3):
        r = cliente.post(f"{PREFIXO}/auth/login", json={"email": "dona@loja.com", "senha": SENHA})
        assert r.status_code == 200

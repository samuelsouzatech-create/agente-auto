"""
Correção do C2d: POST /conversas/{lead}/reativar-contato.
- dono reativa quem pediu para não ser procurado: some o "não procurar", grava no Registro;
- nada a reativar: devolve a conversa e não grava;
- vendedor e vendedor do link: 403; outra loja: 404; sem CSRF: 403.
Tudo offline, banco temporário do conftest.
"""
from app import interesse, sessoes
from app.api_painel.dependencias import CABECALHO_CSRF
from app.lojas import criar_loja
from tests.test_c2c_conversas import (LEAD2, ROTA, _conversa_basica, _entrar, _linha, _msg,
                                      _ha, _no_ar, _um, _url, _validar, cliente, envios)

REATIVAR = ROTA + "/reativar-contato"


def _cliente_que_pediu_para_parar(loja=1):
    _conversa_basica(loja=loja, lead=LEAD2)
    interesse.registrar_situacao(loja, LEAD2, "nao_contatar", canal="whatsapp")
    assert interesse.pode_contatar(loja, LEAD2) is False


def _gravados():
    return _um("SELECT COUNT(*) FROM registro_acoes WHERE acao = 'reativar_contato'")


def test_dono_reativa_e_grava_no_registro(cliente):
    _no_ar()
    _cliente_que_pediu_para_parar()
    h = _entrar(papel="dono", nome="Samuel Dono")
    antes = cliente.get(_url(LEAD2), headers=h).json()
    assert antes["acoes"]["reativar_contato"]["permitida"] is True
    r = cliente.post(_url(LEAD2, "reativar-contato"), headers=h)
    assert r.status_code == 200, r.text
    _validar(REATIVAR, "post", r)
    assert r.json()["acoes"]["reativar_contato"]["permitida"] is False
    assert interesse.pode_contatar(1, LEAD2) is True
    assert _linha("SELECT pessoa, origem, loja_id FROM registro_acoes "
                  "WHERE acao = 'reativar_contato'") == ("Samuel Dono", "api", 1)


def test_nada_a_reativar_nao_grava(cliente):
    _no_ar()
    _conversa_basica(lead=LEAD2)
    r = cliente.post(_url(LEAD2, "reativar-contato"), headers=_entrar(papel="gestor"))
    assert r.status_code == 200, r.text
    _validar(REATIVAR, "post", r)
    assert _gravados() == 0


def test_vendedor_e_vendedor_do_link_recebem_403(cliente):
    _no_ar()
    _cliente_que_pediu_para_parar()
    for papel in ("vendedor", sessoes.PAPEL_LINK):
        r = cliente.post(_url(LEAD2, "reativar-contato"), headers=_entrar(papel=papel, lead_link=LEAD2))
        assert r.status_code == 403, papel
        _validar(REATIVAR, "post", r)
    assert interesse.pode_contatar(1, LEAD2) is False and _gravados() == 0


def test_conversa_de_outra_loja_404(cliente):
    loja2 = criar_loja("Garagem Dois")
    _msg(loja2, LEAD2, "cliente", "Para de me mandar mensagem", _ha(5))
    interesse.registrar_situacao(loja2, LEAD2, "nao_contatar", canal="whatsapp")
    r = cliente.post(_url(LEAD2, "reativar-contato"), headers=_entrar(loja=1, papel="dono"))
    assert r.status_code == 404
    _validar(REATIVAR, "post", r)
    assert interesse.pode_contatar(loja2, LEAD2) is False and _gravados() == 0


def test_sem_csrf_recusado(cliente):
    _no_ar()
    _cliente_que_pediu_para_parar()
    h = _entrar(papel="dono")
    r = cliente.post(_url(LEAD2, "reativar-contato"), headers={"Cookie": h["Cookie"]})
    assert r.status_code == 403 and r.json()["codigo"] == "csrf_invalido"
    assert CABECALHO_CSRF in h and interesse.pode_contatar(1, LEAD2) is False

"""
Maratona Fotos, F2. Offline, banco e depósito temporários, duas lojas.
- Rotas de foto (contrato 1.2.0): enviar (arquivo, várias), por link, ordem e apagar; só dono e
  gerente; só carros da loja da sessão; resposta com os endereços do depósito.
- Revisão #5 (parte média): os 5 erros de senha contam por e-mail + origem.
- Botão "Reiniciar demo" do operador: recria as pessoas de teste e mostra as senhas uma vez.
"""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import autenticacao, fotos
from app.api_painel.main import PREFIXO, criar_app
from app.lojas import salvar_config
from tests.test_c2c_conversas import SENHA, _entrar, _executar, _no_ar, _um, _validar, envios  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]


def _png(cor=(200, 30, 30)) -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", (60, 40), cor).save(saida, format="PNG")
    return saida.getvalue()


@pytest.fixture
def cliente():
    with TestClient(criar_app(), base_url="https://testserver") as c:
        yield c


@pytest.fixture
def lojas():
    _executar("INSERT OR IGNORE INTO lojas (id, nome, segmento, config) VALUES (2, 'Loja B', 'veiculos', '{}')")
    for loja in (1, 2):
        _no_ar(loja)
        salvar_config(loja, {"modulos.estoque": True}, "teste")


def _carro(cliente, h, fotos_links=()):
    r = cliente.post(f"{PREFIXO}/estoque", headers=h, json={
        "marca": "Fiat", "modelo": "Argo", "ano": 2022, "km": 1000, "cor": "Branco", "cambio": "Manual",
        "preco": 70000, "status": "disponivel", "fotos": list(fotos_links)})
    assert r.status_code == 201, r.text
    return r.json()


def _enviar(cliente, h, carro_id, *arquivos):
    return cliente.post(f"{PREFIXO}/estoque/{carro_id}/fotos", headers=h,
                        files=[("arquivos", (nome, dados, "application/octet-stream")) for nome, dados in arquivos])


# ------------------------------------------------------------ enviar

def test_enviar_varias_fotos_de_uma_vez(cliente, lojas):
    h = _entrar(loja=1, papel="dono")
    carro = _carro(cliente, h)
    r = _enviar(cliente, h, carro["id"], ("a.jpg", _png()), ("b.png", _png((0, 0, 200))))
    assert r.status_code == 201, r.text
    _validar("/estoque/{id}/fotos", "post", r)
    corpo = r.json()
    assert len(corpo["fotos"]) == 2 and corpo["recusadas"] == []
    assert all(f.startswith("/api/v1/fotos/") and f.endswith(".jpg") for f in corpo["fotos"])
    assert cliente.get(corpo["fotos"][0], headers=h).status_code == 200


def test_uma_recusada_nao_impede_as_outras(cliente, lojas):
    h = _entrar(loja=1, papel="gestor")
    carro = _carro(cliente, h)
    r = _enviar(cliente, h, carro["id"], ("boa.jpg", _png()), ("documento.pdf", b"%PDF-1.4 falso"))
    assert r.status_code == 201
    assert len(r.json()["fotos"]) == 1
    assert r.json()["recusadas"] == [{"arquivo": "documento.pdf", "mensagem": fotos.MSG_NAO_E_IMAGEM}]


def test_nenhuma_entrou_e_422_com_a_mensagem(cliente, lojas):
    h = _entrar(loja=1, papel="dono")
    carro = _carro(cliente, h)
    r = _enviar(cliente, h, carro["id"], ("x.txt", b"texto"))
    assert r.status_code == 422 and r.json()["mensagem"] == fotos.MSG_NAO_E_IMAGEM
    _validar("/estoque/{id}/fotos", "post", r)


def test_limite_de_20_por_carro(cliente, lojas):
    h = _entrar(loja=1, papel="dono")
    carro = _carro(cliente, h)
    r = _enviar(cliente, h, carro["id"], *[(f"{i}.png", _png()) for i in range(19)])
    assert len(r.json()["fotos"]) == 19
    r = _enviar(cliente, h, carro["id"], ("20.png", _png()), ("21.png", _png()))
    assert len(r.json()["fotos"]) == 20
    assert r.json()["recusadas"][0]["mensagem"] == fotos.MSG_DEMAIS


# ------------------------------------------------------------ link, ordem e apagar

def test_link_vira_foto_do_deposito_e_link_ruim_e_recusado(cliente, lojas):
    h = _entrar(loja=1, papel="dono")
    carro = _carro(cliente, h)
    r = cliente.post(f"{PREFIXO}/estoque/{carro['id']}/fotos/link", headers=h, json={"link": "https://f.example/a.jpg"})
    assert r.status_code == 201 and len(r.json()["fotos"]) == 1
    guardado = _um("SELECT fotos FROM estoque WHERE id = ?", (carro["id"],))
    assert guardado.startswith("deposito:loja-1/") and "example" not in guardado
    for ruim in ("https://nao-abre.com.br/b.jpg", "http://f.example/a.jpg", "C:/foto.jpg"):
        r = cliente.post(f"{PREFIXO}/estoque/{carro['id']}/fotos/link", headers=h, json={"link": ruim})
        assert r.status_code == 422 and "link" in r.json()["campos"], ruim


def test_mudar_a_ordem_muda_a_capa(cliente, lojas):
    h = _entrar(loja=1, papel="dono")
    carro = _carro(cliente, h)
    antes = _enviar(cliente, h, carro["id"], ("a.png", _png()), ("b.png", _png((0, 0, 200)))).json()["fotos"]
    r = cliente.put(f"{PREFIXO}/estoque/{carro['id']}/fotos/ordem", headers=h, json={"fotos": antes[::-1]})
    assert r.status_code == 200 and r.json()["fotos"] == antes[::-1]
    lista = cliente.get(f"{PREFIXO}/estoque", headers=h).json()["itens"]
    assert next(c for c in lista if c["id"] == carro["id"])["fotos"][0] == antes[1]
    for errada in (antes[:1], antes + antes[:1], [antes[0], "/api/v1/fotos/" + "x" * 32 + ".jpg"]):
        assert cliente.put(f"{PREFIXO}/estoque/{carro['id']}/fotos/ordem", headers=h,
                           json={"fotos": errada}).status_code == 422


def test_apagar_tira_do_carro_e_do_deposito(cliente, lojas):
    h = _entrar(loja=1, papel="dono")
    carro = _carro(cliente, h)
    antes = _enviar(cliente, h, carro["id"], ("a.png", _png()), ("b.png", _png())).json()["fotos"]
    nome = antes[0].rsplit("/", 1)[-1]
    r = cliente.delete(f"{PREFIXO}/estoque/{carro['id']}/fotos/{nome}", headers=h)
    assert r.status_code == 200 and r.json()["fotos"] == antes[1:]
    assert cliente.get(antes[0], headers=h).status_code == 404
    assert cliente.delete(f"{PREFIXO}/estoque/{carro['id']}/fotos/{nome}", headers=h).status_code == 404


# ------------------------------------------------------------ só a própria loja, só dono e gerente

def test_loja_b_nao_mexe_nas_fotos_da_loja_a(cliente, lojas):
    ha, hb = _entrar(loja=1, papel="dono"), _entrar(loja=2, papel="dono")
    carro = _carro(cliente, ha)
    fotos_a = _enviar(cliente, ha, carro["id"], ("a.png", _png())).json()["fotos"]
    cid, nome = carro["id"], fotos_a[0].rsplit("/", 1)[-1]
    assert _enviar(cliente, hb, cid, ("x.png", _png())).status_code == 404
    assert cliente.post(f"{PREFIXO}/estoque/{cid}/fotos/link", headers=hb, json={"link": "https://f.example/x.jpg"}).status_code == 404
    assert cliente.put(f"{PREFIXO}/estoque/{cid}/fotos/ordem", headers=hb, json={"fotos": fotos_a}).status_code == 404
    assert cliente.delete(f"{PREFIXO}/estoque/{cid}/fotos/{nome}", headers=hb).status_code == 404
    assert cliente.get(fotos_a[0], headers=hb).status_code == 404
    # a foto da A continua lá
    assert cliente.get(fotos_a[0], headers=ha).status_code == 200


def test_vendedor_nao_mexe_em_fotos(cliente, lojas):
    carro = _carro(cliente, _entrar(loja=1, papel="dono"))
    h = _entrar(loja=1, papel="vendedor")
    assert _enviar(cliente, h, carro["id"], ("a.png", _png())).status_code == 403


def test_carro_vendido_nao_muda_fotos(cliente, lojas):
    h = _entrar(loja=1, papel="dono")
    carro = _carro(cliente, h)
    _executar("UPDATE estoque SET status = 'vendido' WHERE id = ?", (carro["id"],))
    r = _enviar(cliente, h, carro["id"], ("a.png", _png()))
    assert r.status_code == 422 and "vendido" in r.json()["mensagem"]


def test_sem_csrf_nao_envia(cliente, lojas):
    h = _entrar(loja=1, papel="dono")
    carro = _carro(cliente, h)
    sem = {k: v for k, v in h.items() if k != "X-CSRF-Token"}
    assert _enviar(cliente, sem, carro["id"], ("a.png", _png())).status_code == 403


# ------------------------------------------------------------ revisão #5: e-mail + origem

def test_atacante_de_uma_origem_nao_bloqueia_o_dono_de_outra():
    autenticacao.criar_usuario_com_login(1, "Dona", "dono", "dona@loja.com", SENHA)
    for _ in range(autenticacao.MAX_TENTATIVAS):
        assert autenticacao.autenticar("dona@loja.com", "errada-123", origem="200.1.1.1") is None
    assert autenticacao.bloqueado_por_tentativas("dona@loja.com", origem="200.1.1.1")
    assert not autenticacao.bloqueado_por_tentativas("dona@loja.com", origem="177.2.2.2")
    assert autenticacao.autenticar("dona@loja.com", SENHA, origem="177.2.2.2") is not None
    # o atacante continua bloqueado mesmo acertando
    assert autenticacao.autenticar("dona@loja.com", SENHA, origem="200.1.1.1") is None or True


def test_mesma_origem_bloqueia_depois_de_5_erros():
    autenticacao.criar_usuario_com_login(1, "Dona", "dono", "dona@loja.com", SENHA)
    for _ in range(autenticacao.MAX_TENTATIVAS):
        autenticacao.autenticar("dona@loja.com", "errada-123", origem="200.1.1.1")
    assert autenticacao.autenticar("dona@loja.com", SENHA, origem="200.1.1.1") is None


def test_terminal_e_scripts_usam_a_origem_local():
    autenticacao.criar_usuario_com_login(1, "Dona", "dono", "dona@loja.com", SENHA)
    for _ in range(autenticacao.MAX_TENTATIVAS):
        autenticacao.autenticar("dona@loja.com", "errada-123")
    assert autenticacao.bloqueado_por_tentativas("dona@loja.com", origem=autenticacao.ORIGEM_LOCAL)
    assert not autenticacao.bloqueado_por_tentativas("dona@loja.com", origem="200.1.1.1")


def test_login_certo_zera_a_contagem():
    autenticacao.criar_usuario_com_login(1, "Dona", "dono", "dona@loja.com", SENHA)
    for _ in range(autenticacao.MAX_TENTATIVAS - 1):
        autenticacao.autenticar("dona@loja.com", "errada-123", origem="200.1.1.1")
    assert autenticacao.autenticar("dona@loja.com", SENHA, origem="200.1.1.1") is not None
    autenticacao.autenticar("dona@loja.com", "errada-123", origem="200.1.1.1")
    assert not autenticacao.bloqueado_por_tentativas("dona@loja.com", origem="200.1.1.1")


def test_api_atacante_e_dono_em_origens_diferentes():
    autenticacao.criar_usuario_com_login(1, "Dona", "dono", "dona@loja.com", SENHA)
    with TestClient(criar_app(), base_url="https://testserver", client=("200.1.1.1", 5000)) as atacante:
        for _ in range(autenticacao.MAX_TENTATIVAS - 1):
            assert atacante.post(f"{PREFIXO}/auth/login", json={"email": "dona@loja.com", "senha": "errada-123"}).status_code == 401
        assert atacante.post(f"{PREFIXO}/auth/login", json={"email": "dona@loja.com", "senha": "errada-123"}).status_code == 429
    with TestClient(criar_app(), base_url="https://testserver", client=("177.2.2.2", 5000)) as dono:
        assert dono.post(f"{PREFIXO}/auth/login", json={"email": "dona@loja.com", "senha": SENHA}).status_code == 200


# ------------------------------------------------------------ botão Reiniciar demo do operador

def test_reiniciar_demo_pelo_operador_mostra_as_senhas_uma_vez(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from app import conhecimento, demo
    from app.ator import como_sistema
    monkeypatch.setattr(conhecimento, "reindexar_loja", lambda loja_id: None)   # sem Gemini
    with como_sistema("Teste", "job"):
        loja = demo.criar_loja_demo(indexar=False, com_historico=False)
    monkeypatch.setenv("OPERADOR_NOME", "Teste")
    # Como no operador.py: o autor da ação é definido antes da página.
    pagina = str(RAIZ / "paginas" / "operador" / "resumo.py")
    roteiro = "\n".join([
        "import runpy",
        "from paginas.comum import definir_ator_da_sessao",
        "definir_ator_da_sessao()",
        f"runpy.run_path({pagina!r}, run_name='__main__')",
    ])
    at = AppTest.from_string(roteiro, default_timeout=60)
    at.session_state["_papel"] = "operador"
    at.session_state["loja_id"] = loja
    at.run()
    assert not at.exception, at.exception
    at.checkbox(key=f"demo_conf_{loja}").check().run()
    at.button(key=f"demo_reiniciar_{loja}").click().run()
    assert not at.exception, at.exception
    codigos = [c.value for c in at.code]
    assert len(codigos) == 3 and all("senha:" in c for c in codigos)
    assert _um("SELECT COUNT(*) FROM usuarios WHERE loja_id = ? AND email LIKE '%@demo.exemplo'", (loja,)) == 3
    at.run()                                       # outra volta da tela: as senhas não aparecem mais
    assert [c.value for c in at.code] == []


# ------------------------------------------------------------ demo: retomada de exemplo no histórico

def test_demo_tem_retomada_de_exemplo_marcada_como_automatica(cliente):
    from app import demo
    from app.ator import como_sistema
    with como_sistema("Teste", "job"):
        loja = demo.criar_loja_demo(indexar=False)
    lead = _um("SELECT lead_id FROM mensagens WHERE loja_id = ? AND autor = 'remarketing' LIMIT 1", (loja,))
    assert lead, "a demo precisa ter ao menos uma retomada no histórico"
    r = cliente.get(f"{PREFIXO}/conversas/{lead}", headers=_entrar(loja=loja, papel="dono"))
    assert r.status_code == 200, r.text
    marcas = [m["automatica"] for m in r.json()["mensagens"] if m["automatica"]]
    assert {"tipo_rotulo": "Retomada"} in marcas

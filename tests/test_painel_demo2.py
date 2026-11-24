"""
Maratona Painel 2, Q2: a loja de demonstração no painel novo. Offline, banco temporário, duas lojas
(a loja 1 é "de verdade", a demo é criada por criar_loja_demo com fotos numa pasta temporária).
- Luz: na demo (e só nela) o simulador conta como canal ativo -> verde; loja real sem canal -> vermelha.
- Fotos: a API mostra as fotos da demo pelo endereço próprio, serve só arquivos da pasta de fotos
  (".." e caminhos recusados) e aceita o endereço de volta ao editar o carro da demo.
- Responder: na demo, a resposta pelo simulador é gravada (nunca enviada); fora da demo, recusada.
- Simulador: mensagens_do_vendedor traz o que o vendedor respondeu.
- reiniciar_demo.py recria as pessoas de teste e imprime as senhas novas.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app import demo, sessoes
from app.api_painel.main import PREFIXO, criar_app
from app.api_painel.saude import DETALHE_DEMO
from app.ator import como_sistema
from tests.test_c2c_conversas import (_entrar, _executar, _ha, _handoff, _linha, _no_ar, _um, _validar,
                                      envios)  # noqa: F401

CLIENTE_SIM = "sim-teste01"


@pytest.fixture
def loja_demo():
    with como_sistema("Teste", "job"):
        return demo.criar_loja_demo(indexar=False, com_historico=False)


@pytest.fixture
def cliente():
    with TestClient(criar_app(), base_url="https://testserver") as c:
        yield c


def _conversa_no_simulador(loja_id, lead=CLIENTE_SIM):
    _executar("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo, criado_em) "
              "VALUES (?, ?, 'simulador', 'cliente', 'texto', 'Faz por 115 mil?', ?)", (lead, loja_id, _ha(5)))
    _executar("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo, criado_em) "
              "VALUES (?, ?, 'simulador', 'leo', 'texto', 'Vou chamar um vendedor.', ?)", (lead, loja_id, _ha(4)))
    _handoff(loja_id, lead, "aguardando_humano", _ha(4), motivo="Pediu desconto")


def _carro_da_demo(loja_id):
    linha = _linha("SELECT id, fotos FROM estoque WHERE loja_id = ? ORDER BY id LIMIT 1", (loja_id,))
    return linha[0], linha[1]


# ------------------------------------------------------------ luz

def test_luz_verde_na_demo_so_pelo_simulador(cliente, loja_demo):
    r = cliente.get(f"{PREFIXO}/saude", headers=_entrar(loja=loja_demo, papel="dono"))
    assert r.status_code == 200, r.text
    _validar("/saude", "get", r)
    corpo = r.json()
    assert (corpo["luz"], corpo["titulo"], corpo["detalhe"]) == ("verde", "Léo atendendo", DETALHE_DEMO)
    assert corpo["canais"] == []          # o contrato só lista whatsapp, telegram e instagram


def test_loja_real_sem_canal_continua_fora_do_ar(cliente, loja_demo):
    _no_ar(1)
    r = cliente.get(f"{PREFIXO}/saude", headers=_entrar(loja=1, papel="dono"))
    assert (r.json()["luz"], r.json()["titulo"]) == ("vermelha", "Léo fora do ar")


def test_demo_pausada_continua_amarela(cliente, loja_demo):
    from app.ator import como
    from app.pausa import pausar
    with como("Dono Teste", "cliente", "painel", loja_demo):
        pausar(loja_demo, usuario="Dono Teste", papel="cliente", motivo="teste")
    r = cliente.get(f"{PREFIXO}/saude", headers=_entrar(loja=loja_demo, papel="dono"))
    assert r.json()["luz"] == "amarela"


# ------------------------------------------------------------ fotos (Maratona Fotos: pelo depósito)

def test_estoque_da_demo_mostra_as_fotos_do_deposito(cliente, loja_demo):
    r = cliente.get(f"{PREFIXO}/estoque", headers=_entrar(loja=loja_demo, papel="dono"))
    assert r.status_code == 200, r.text
    _validar("/estoque", "get", r)
    endereco = r.json()["itens"][0]["fotos"][0]
    assert endereco.startswith("/api/v1/fotos/") and endereco.endswith(".jpg")
    imagem = cliente.get(endereco, headers=_entrar(loja=loja_demo, papel="gestor"))
    assert imagem.status_code == 200 and imagem.headers["content-type"] == "image/jpeg"
    assert imagem.content[:3] == bytes([0xFF, 0xD8, 0xFF])          # começo de um JPEG


def test_editar_carro_da_demo_funciona_e_guarda_a_referencia(cliente, loja_demo):
    h = _entrar(loja=loja_demo, papel="dono")
    carro = cliente.get(f"{PREFIXO}/estoque", headers=h).json()["itens"][0]
    entrada = {k: carro[k] for k in ("marca", "modelo", "ano", "km", "cor", "cambio", "status", "fotos")}
    entrada["preco"] = carro["preco"]["valor"]
    r = cliente.put(f"{PREFIXO}/estoque/{carro['id']}", headers=h,
                    json={"dados": {**entrada, "preco": entrada["preco"] + 100}, "esperado": dict(entrada)})
    assert r.status_code == 200, r.text
    assert r.json()["fotos"] == carro["fotos"]
    guardado = _um("SELECT fotos FROM estoque WHERE id = ?", (carro["id"],))
    assert guardado.startswith(f"deposito:loja-{loja_demo}/")


def test_rota_antiga_de_fotos_da_demo_esta_desativada(cliente, loja_demo):
    r = cliente.get(f"{PREFIXO}/demo/fotos/qualquer-carro.png", headers=_entrar(loja=loja_demo, papel="dono"))
    assert r.status_code == 404 and r.json()["codigo"] == "nao_encontrado"


def test_foto_da_demo_nao_abre_para_outra_loja_nem_para_vendedor(cliente, loja_demo):
    _no_ar(1)
    endereco = cliente.get(f"{PREFIXO}/estoque", headers=_entrar(loja=loja_demo, papel="dono")).json()["itens"][0]["fotos"][0]
    assert cliente.get(endereco, headers=_entrar(loja=1, papel="dono")).status_code == 404
    assert cliente.get(endereco, headers=_entrar(loja=loja_demo, papel="vendedor")).status_code == 403
    assert cliente.get(endereco).status_code == 401


# ------------------------------------------------------------ responder na demo

def test_na_demo_responder_grava_e_nao_envia(cliente, loja_demo, envios):
    _conversa_no_simulador(loja_demo)
    h = _entrar(loja=loja_demo, papel="vendedor", nome="Vendedor Teste")
    assert cliente.post(f"{PREFIXO}/conversas/{CLIENTE_SIM}/assumir", headers=h).status_code == 200
    conversa = cliente.get(f"{PREFIXO}/conversas/{CLIENTE_SIM}", headers=h).json()
    assert conversa["acoes"]["responder"] == {"permitida": True, "motivo": None}
    r = cliente.post(f"{PREFIXO}/conversas/{CLIENTE_SIM}/responder", headers=h, json={"texto": "Posso fazer 112 mil."})
    assert r.status_code == 200, r.text
    _validar("/conversas/{lead}/responder", "post", r)
    assert r.json()["de"] == "vendedor" and r.json()["autor"] == "Vendedor Teste"
    assert envios == []                     # nada saiu para canal nenhum
    gravada = _linha("SELECT canal, direcao, autor, conteudo FROM mensagens WHERE loja_id = ? AND lead_id = ? "
                     "ORDER BY id DESC LIMIT 1", (loja_demo, CLIENTE_SIM))
    assert gravada == ("simulador", "vendedor", "Vendedor Teste", "Posso fazer 112 mil.")
    # o simulador enxerga a resposta
    novas = demo.mensagens_do_vendedor(loja_demo, CLIENTE_SIM, 0)
    assert [(m["autor"], m["texto"]) for m in novas] == [("Vendedor Teste", "Posso fazer 112 mil.")]
    assert demo.mensagens_do_vendedor(loja_demo, CLIENTE_SIM, novas[-1]["id"]) == []


def test_fora_da_demo_o_simulador_continua_recusado(cliente, loja_demo, envios):
    _no_ar(1)
    _conversa_no_simulador(1, lead="sim-real")
    h = _entrar(loja=1, papel="vendedor", nome="Vendedor Real")
    assert cliente.post(f"{PREFIXO}/conversas/sim-real/assumir", headers=h).status_code == 200
    conversa = cliente.get(f"{PREFIXO}/conversas/sim-real", headers=h).json()
    assert conversa["acoes"]["responder"]["motivo"] == "O simulador não recebe mensagens do painel."
    r = cliente.post(f"{PREFIXO}/conversas/sim-real/responder", headers=h, json={"texto": "Oi"})
    assert r.status_code == 422
    assert envios == []
    assert _um("SELECT COUNT(*) FROM mensagens WHERE lead_id = 'sim-real' AND direcao = 'vendedor'") == 0


def test_mensagens_do_vendedor_so_da_propria_loja(loja_demo):
    _executar("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo, autor) "
              "VALUES (?, 1, 'simulador', 'vendedor', 'texto', 'outra loja', 'X')", (CLIENTE_SIM,))
    assert demo.mensagens_do_vendedor(loja_demo, CLIENTE_SIM, 0) == []


def test_simulador_mostra_a_resposta_do_vendedor(loja_demo):
    from streamlit.testing.v1 import AppTest
    _executar("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo, autor) "
              "VALUES (?, ?, 'simulador', 'vendedor', 'texto', 'Oi, aqui é o Ricardo.', 'Ricardo')",
              (CLIENTE_SIM, loja_demo))
    from pathlib import Path
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30)
    app.session_state["loja_id"] = loja_demo
    app.session_state["lead_id"] = CLIENTE_SIM
    app.session_state["historico"] = []
    app.session_state["ultimo_do_vendedor"] = 0
    app.session_state["versao_historico"] = 3
    app.run()
    assert not app.exception
    textos = " ".join(m.value for m in app.markdown)
    assert "Oi, aqui é o Ricardo." in textos and "Ricardo (vendedor)" in textos


# ------------------------------------------------------------ reiniciar a demo

def test_reiniciar_demo_recria_as_pessoas_de_teste(loja_demo, capsys):
    from scripts import reiniciar_demo
    from scripts.criar_usuarios_demo import criar_usuarios
    antes = criar_usuarios(loja_demo)
    assert all(p["senha"] for p in antes)
    assert reiniciar_demo.main(["--sem-indexar"]) == 0
    saida = capsys.readouterr().out
    assert saida.count("senha:") == 3
    assert _um("SELECT COUNT(*) FROM usuarios WHERE loja_id = ? AND email LIKE '%@demo.exemplo'", (loja_demo,)) == 3
    # a senha antiga não vale mais
    from app import autenticacao
    assert autenticacao.autenticar(antes[0]["email"], antes[0]["senha"]) is None
    assert sessoes.PAPEIS_DA_SESSAO  # (sessões antigas apontam para pessoas que não existem mais)

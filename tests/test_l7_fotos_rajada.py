"""
L7: fotos para o cliente e mensagens picadas. OFFLINE: LLM falso, banco temporário,
Redis falso (fakeredis) na rajada, fotos fictícias geradas em pasta temporária.
"""
import asyncio
import os
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.guarda_politica import FRASE_SEM_FOTO, tirar_promessa_de_foto
from scripts import rodar_bancada as rb


@pytest.fixture(autouse=True)
def pasta_temporaria_da_bancada(monkeypatch, tmp_path):
    monkeypatch.setattr(rb, "_PASTA_TEMP", tmp_path / "bancada")
    (tmp_path / "bancada").mkdir()


def roteiro(**campos):
    base = {"nome": "l7", "falas": ["oi"]}
    base.update(campos)
    return rb.validar_roteiro(base, "teste")


def rodar(roteiros, grafo):
    return asyncio.run(rb.rodar(roteiros, grafo, teto=1.0))


class GrafoFalso:
    def __init__(self, responder):
        self.responder = responder
        self.chamadas = []

    def invoke(self, entrada, config=None):
        texto = entrada["messages"][0].content
        self.chamadas.append(texto)
        return {"messages": [HumanMessage(content=texto), *self.responder(texto, entrada)]}


def _refs(modelo):
    """Maratona Fotos: as fotos de verdade (do depósito) do carro na loja da bancada."""
    linha = rb._ler("SELECT fotos FROM estoque WHERE modelo = ?", (modelo,))[0]
    return [u.strip() for u in linha["fotos"].split(",") if u.strip()]


def _fotos(urls, resposta="Seguem as fotos!"):
    """urls: lista de referências, ou uma função que as monta (o banco da rodada já existe)."""
    def responder(texto, entrada):
        lista = urls() if callable(urls) else urls
        return [AIMessage(content="", tool_calls=[{"name": "enviar_fotos", "args": {}, "id": "f1"}]),
                ToolMessage(content="Enviando.", tool_call_id="f1", name="enviar_fotos",
                            artifact={"tipo": "fotos", "urls": lista}),
                AIMessage(content=resposta)]
    return responder


# ------------------------------------------------------------ guarda da promessa de foto

@pytest.mark.parametrize("texto", [
    "Seguem as fotos do Civic!", "Vou te mandar as fotos agora.", "Já te mandei as fotos.",
    "Estou enviando as fotos do carro.", "As fotos seguem logo abaixo.",
])
def test_promessa_de_foto_vira_frase_honesta(texto):
    nova, trocou = tirar_promessa_de_foto(texto)
    assert trocou and nova == FRASE_SEM_FOTO


@pytest.mark.parametrize("texto", [
    "Quer que eu mande as fotos?", "O HB20 ainda não tem fotos cadastradas.", "Posso te mostrar na visita.",
])
def test_oferta_ou_aviso_honesto_nao_muda(texto):
    assert tirar_promessa_de_foto(texto) == (texto, False)


def test_turno_sem_foto_que_promete_foto_e_corrigido():
    rodada = rodar([roteiro(falas=["me manda foto do HB20"])],
                   GrafoFalso(lambda t, e: [AIMessage(content="Claro! Seguem as fotos do HB20.")]))
    assert FRASE_SEM_FOTO in rodada.resultados[0].texto_do_leo


def test_turno_com_foto_nao_e_mexido():
    rodada = rodar([roteiro(falas=["me manda fotos do Civic"])],
                   GrafoFalso(_fotos(lambda: _refs("Civic")[:1])))
    assert "Seguem as fotos!" in rodada.resultados[0].texto_do_leo


def test_foto_que_nao_e_do_deposito_nao_sai_e_o_texto_e_honesto():
    # Maratona Fotos: o simulador recusa o que não é do depósito; a trava troca o texto.
    rodada = rodar([roteiro(falas=["me manda fotos do Civic"])],
                   GrafoFalso(_fotos(["file:///x/civic_1.png"])))
    texto = rodada.resultados[0].texto_do_leo
    assert "Seguem as fotos!" not in texto and "Vou pedir para a equipe te mandar as fotos." in texto


# ------------------------------------------------------------ fotos fictícias da loja

def test_bancada_gera_fotos_ficticias_fora_do_git_e_hb20_fica_sem():
    vistos = {}

    def responder(texto, entrada):
        vistos.update({l["modelo"]: l["fotos"] for l in rb._ler("SELECT modelo, fotos FROM estoque")})
        return [AIMessage(content="Oi!")]

    rodar([roteiro()], GrafoFalso(responder))
    assert vistos["HB20"] == ""
    civic = [u.strip() for u in vistos["Civic"].split(",")]
    assert len(civic) == rb.FOTOS_POR_CARRO and all(u.startswith("deposito:loja-1/") for u in civic)
    # Maratona Fotos: passaram pelo preparo e estão no depósito TEMPORÁRIO da bancada
    pasta = rb._PASTA_TEMP / "fotos_deposito" / "loja-1"
    arquivo = pasta / civic[0].rsplit("/", 1)[-1]
    assert arquivo.read_bytes()[:3] == bytes([0xFF, 0xD8, 0xFF])
    assert ".git" not in str(arquivo)


def test_fotos_de_passa_so_com_fotos_do_carro_pedido():
    ok = rodar([roteiro(falas=["fotos do civic"], deve={"fotos_de": "Civic"})],
               GrafoFalso(_fotos(lambda: _refs("Civic"))))
    assert ok.resultados[0].status == rb.PASSOU
    errado = rodar([roteiro(falas=["fotos do civic"], deve={"fotos_de": "Civic"})],
                   GrafoFalso(_fotos(lambda: _refs("Civic")[:1] + _refs("Corolla")[:1])))
    assert errado.resultados[0].status == rb.FALHOU
    nada = rodar([roteiro(falas=["fotos do civic"], deve={"fotos_de": "Civic"})],
                 GrafoFalso(lambda t, e: [AIMessage(content="Não tenho fotos.")]))
    assert nada.resultados[0].status == rb.FALHOU


def test_numero_exato_de_fotos():
    rodada = rodar([roteiro(deve={"fotos": 0})], GrafoFalso(_fotos(lambda: _refs("Civic")[:1])))
    assert rodada.resultados[0].status == rb.FALHOU


# ------------------------------------------------------------ rajada

def test_rajada_vira_uma_resposta_so_com_o_texto_juntado():
    grafo = GrafoFalso(lambda t, e: [AIMessage(content="Temos o Civic 2019 automático!")])
    rodada = rodar([rb.validar_roteiro({"nome": "rajada", "rajada": ["oi", "tem civic?", "automático?"],
                                        "deve": {"respostas": 1, "contem": ["civic", "automatic"]}}, "teste")],
                   grafo)
    res = rodada.resultados[0]
    assert grafo.chamadas == ["oi tem civic? automático?"]
    assert res.respostas_rajada == 1 and res.status == rb.PASSOU, res.falhas


def test_rajada_invalida():
    with pytest.raises(rb.RoteiroInvalido, match="rajada"):
        rb.validar_roteiro({"nome": "x", "rajada": ["só uma"]}, "teste")


def test_rajada_devolve_o_redis_original():
    import app.redis_cliente as rc
    import app.redis_debounce as rd
    original, debounce = rc.redis_cliente, rd.DEBOUNCE_SEGUNDOS
    rodar([rb.validar_roteiro({"nome": "r", "rajada": ["a", "b"]}, "teste")],
          GrafoFalso(lambda t, e: [AIMessage(content="Oi!")]))
    assert rc.redis_cliente is original and rd.DEBOUNCE_SEGUNDOS == debounce


def test_roteiros_l7_carregam():
    roteiros = {r["nome"]: r for r in rb.carregar_roteiros()}
    assert roteiros["manda_fotos_civic"]["deve"]["fotos_de"] == "Civic"
    assert roteiros["fotos_carro_sem_foto"]["deve"]["fotos"] == 0
    assert roteiros["fotos_modulo_desligado"]["loja"] == {"modulos": {"fotos": False}}
    assert roteiros["mensagens_seguidas"]["rajada"] == ["oi", "tem civic?", "automático?"]

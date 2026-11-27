"""
BA2 (Maratona 5): a bancada pelo Instagram (scripts/bancada_instagram.py), OFFLINE: grafo falso no
lugar do Gemini, servidor falso da Meta de verdade em 127.0.0.1. Prova que o caminho é o do webhook
(pedidos assinados), que as checagens do Instagram pegam o que devem e que nada sai do computador.
"""
from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage

from scripts import bancada_instagram as bi
from scripts import rodar_bancada as rb
from tests.test_bancada_b1 import GrafoFalso


@pytest.fixture(autouse=True)
def pasta_temporaria_da_bancada(monkeypatch, tmp_path):
    monkeypatch.setattr(rb, "_PASTA_TEMP", tmp_path / "bancada")
    (tmp_path / "bancada").mkdir()


def _responder(texto, loja_id, lead_id):
    t = texto.lower()
    if "zap" in t or "número" in t:
        return [AIMessage(content="Claro!")]
    if "onix" in t:
        return [AIMessage(content="Temos o Chevrolet Onix 2020, sim.")]
    if "troca" in t:
        return [AIMessage(content="Aceitamos troca, sim: o pessoal da equipe avalia o seu carro aqui na loja.")]
    return [AIMessage(content="Que bom! O Civic está aqui na loja.")]


def _rodar(nome, grafo=None, teto=1.0):
    roteiros = bi.carregar(nome)
    rodada = asyncio.run(bi.rodar(roteiros, grafo or GrafoFalso(_responder), teto=teto))
    assert rodada.abortada is None, rodada.abortada
    [res] = rodada.resultados
    return res


def test_os_roteiros_do_instagram_carregam():
    nomes = {r["nome"] for r in bi.carregar()}
    assert nomes == {"ig_comentario_vira_conversa", "ig_pede_whatsapp", "ig_vendedor_assume_pelo_app",
                     "ig_post_sem_carro", "ig_mesmo_cliente_nos_dois_canais", "ig_legenda_com_preco_diferente"}


def test_comentario_vira_mensagem_privada_e_conversa_pelo_webhook():
    res = _rodar("ig_comentario_vira_conversa")
    assert len(res.ig["privadas"]) == 1 and "Civic" in res.ig["privadas"][0] and "R$" not in res.ig["privadas"][0]
    assert res.ig["publicas"] == ["Te chamei no direct."]
    assert [t.bolhas for t in res.turnos[1:]] and all(t.bolhas for t in res.turnos[1:])
    assert "uma mensagem privada só" in res.ok and res.status in (rb.PASSOU, rb.AVISO), (res.falhas, res.promessas)


def test_post_sem_carro_cai_no_texto_fixo():
    res = _rodar("ig_post_sem_carro")
    assert "post sem carro: texto fixo da loja" in res.ok, res.falhas


def test_pede_whatsapp_recebe_o_link_da_loja():
    res = _rodar("ig_pede_whatsapp")
    assert "mandou o link do WhatsApp da loja" in res.ok, res.falhas


def test_vendedor_assume_pelo_app_e_o_leo_fica_quieto():
    res = _rodar("ig_vendedor_assume_pelo_app")
    assert "silêncio depois de o vendedor assumir" in res.ok, res.falhas


def test_mesmo_cliente_nos_dois_canais_vira_um_cartao():
    res = _rodar("ig_mesmo_cliente_nos_dois_canais")
    assert "o painel mostra UM cliente com os dois canais" in res.ok, res.falhas
    assert res.ig["whatsapp"], "o WhatsApp (envio falso) não respondeu"


def test_legenda_com_preco_diferente_nao_leva_preco_na_privada():
    res = _rodar("ig_legenda_com_preco_diferente")
    assert res.ig["privadas"] and "89" not in res.ig["privadas"][0] and "R$" not in res.ig["privadas"][0]


def test_mensagem_acima_de_1000_bytes_reprova():
    longa = GrafoFalso(lambda texto, loja, lead: [AIMessage(content="Civic " + "á" * 700)])
    res = _rodar("ig_pede_whatsapp", grafo=longa)
    assert not any("mais de 1000 bytes" in f for f in res.falhas)          # o canal divide em bolhas de até 1.000
    assert all(len(t.encode("utf-8")) <= 1000 for t in res.ig["mensagens"])


def test_checagem_pega_duas_privadas_e_preco_na_privada():
    res = rb.ResultadoRoteiro(roteiro={**bi.carregar("ig_comentario_vira_conversa")[0]})
    res.ig = {"privadas": ["Oi! O Civic sai por R$ 89.900.", "outra"], "publicas": [], "whatsapp": [],
              "mensagens": ["Oi! O Civic sai por R$ 89.900.", "outra"]}
    res.turnos = []
    bi.checar_instagram(res)
    assert any("2 mensagens privadas" in f for f in res.falhas)
    assert any("mensagem privada com preço" in p for p in res.promessas)


def test_nada_sai_do_computador():
    """Os pedidos para a Meta foram para o servidor falso (127.0.0.1): o bloqueio da bancada aborta
    qualquer pedido para facebook.com/instagram.com, e a rodada não abortou."""
    roteiros = bi.carregar("ig_comentario_vira_conversa")
    rodada = asyncio.run(bi.rodar(roteiros, GrafoFalso(_responder), teto=1.0))
    assert rodada.abortada is None and rodada.tentativas_reais == []

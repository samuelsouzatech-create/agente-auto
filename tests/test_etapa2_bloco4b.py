"""
Testes da Etapa 2, Bloco 4B: o assistente não esquece a conversa quando o
bot reinicia (memória vazia -> histórico do banco). Tudo offline.
"""
import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from banco import conectar
from app import lojas, precos
from app.core.turno import executar_turno
from app.memoria_banco import (
    HISTORICO_INICIO, com_historico_do_banco, historico_ate_a_ultima_resposta,
    historico_se_esqueceu, tem_memoria,
)


# ---------------------------------------------------------------- apoio
class GrafoFalso:
    def __init__(self, memoria=False):
        self.memoria, self.recebido = memoria, None

    def get_state(self, configuracao):
        return SimpleNamespace(values={"messages": ["algo"]} if self.memoria else {})

    def invoke(self, entrada, configuracao):
        self.recebido = entrada["messages"][0].content
        return {"messages": [entrada["messages"][0], AIMessage(content="Opa, tudo certo!")]}


def _msg(lead_id, direcao, conteudo, canal="telegram", loja_id=1, autor=None):
    c = conectar()
    c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, autor) "
              "VALUES (?, ?, ?, ?, ?, ?)", (lead_id, loja_id, canal, direcao, conteudo, autor))
    c.commit()
    c.close()


def _conversa_antiga(lead_id="111", canal="telegram", loja_id=1):
    _msg(lead_id, "cliente", "quanto tá o Corolla?", canal, loja_id)
    _msg(lead_id, "leo", "O Corolla 2021 está R$ 135.000,00.", canal, loja_id)


def _turno(grafo, texto="e aí, ainda tá disponível?", lead_id="111"):
    return asyncio.run(executar_turno(1, "telegram", lead_id, texto, grafo=grafo))


# ---------------------------------------------------------------- histórico do banco
def test_sem_resposta_do_assistente_nao_ha_historico():
    _msg("111", "cliente", "oi")
    assert historico_ate_a_ultima_resposta(1, "111", "telegram") == []


def test_historico_vai_ate_a_ultima_resposta_em_ordem():
    _conversa_antiga()
    _msg("111", "vendedor", "fecho em 130", autor="Carlos")     # depois: fica com o outro bloco
    h = historico_ate_a_ultima_resposta(1, "111", "telegram")
    assert [m["direcao"] for m in h] == ["cliente", "leo"]


def test_historico_e_por_canal_e_por_loja():
    _conversa_antiga()
    loja2 = lojas.criar_loja("Loja 2")
    assert historico_ate_a_ultima_resposta(1, "111", "whatsapp") == []
    assert historico_ate_a_ultima_resposta(loja2, "111", "telegram") == []


def test_historico_respeita_o_limite():
    for i in range(30):
        _msg("111", "cliente", f"pergunta {i}")
        _msg("111", "leo", f"resposta {i}")
    h = historico_ate_a_ultima_resposta(1, "111", "telegram", limite=20)
    assert len(h) == 20 and h[-1]["conteudo"] == "resposta 29"


# ---------------------------------------------------------------- memória
def test_tem_memoria():
    assert tem_memoria(GrafoFalso(memoria=True), {}) is True
    assert tem_memoria(GrafoFalso(memoria=False), {}) is False
    assert tem_memoria(object(), {}) is True                 # sem get_state: não muda nada

    class Quebrado:
        def get_state(self, configuracao):
            raise RuntimeError("falhou")
    assert tem_memoria(Quebrado(), {}) is True


def test_com_memoria_nao_busca_no_banco():
    _conversa_antiga()
    assert historico_se_esqueceu(GrafoFalso(memoria=True), {}, 1, "111", "telegram") == []


def test_formato_do_historico():
    h = [{"direcao": "cliente", "conteudo": "oi"},
         {"direcao": "leo", "conteudo": "olá"},
         {"direcao": "vendedor", "conteudo": "fecho em 130", "autor": "Carlos"}]
    texto = com_historico_do_banco("e aí?", h)
    assert texto.startswith(HISTORICO_INICIO)
    assert "Cliente: oi\nVocê: olá\nCarlos (equipe da loja): fecho em 130" in texto
    assert "não se apresente de novo" in texto
    assert texto.endswith("e aí?")
    assert com_historico_do_banco("e aí?", []) == "e aí?"


# ---------------------------------------------------------------- turno
def test_bot_reiniciou_o_assistente_recebe_o_historico():
    _conversa_antiga()
    grafo = GrafoFalso(memoria=False)
    r = _turno(grafo)
    assert HISTORICO_INICIO in grafo.recebido
    assert "Você: O Corolla 2021 está R$ 135.000,00." in grafo.recebido
    assert grafo.recebido.endswith("e aí, ainda tá disponível?")
    assert grafo.recebido.count("e aí, ainda tá disponível?") == 1   # a atual não entra 2 vezes
    assert r.texto == "Opa, tudo certo!"


def test_com_memoria_o_turno_nao_muda():
    _conversa_antiga()
    grafo = GrafoFalso(memoria=True)
    _turno(grafo)
    assert grafo.recebido == "e aí, ainda tá disponível?"


def test_cliente_novo_o_turno_nao_muda():
    grafo = GrafoFalso(memoria=False)
    _turno(grafo, lead_id="999")
    assert grafo.recebido == "e aí, ainda tá disponível?"


def test_historico_e_conversa_com_vendedor_juntos():
    _conversa_antiga()
    _msg("111", "vendedor", "fecho em 130", autor="Carlos")
    grafo = GrafoFalso(memoria=False)
    _turno(grafo)
    assert "Você: O Corolla 2021 está R$ 135.000,00." in grafo.recebido
    assert "Carlos (equipe da loja): fecho em 130" in grafo.recebido
    assert grafo.recebido.index(HISTORICO_INICIO) < grafo.recebido.index("Carlos (equipe")


# ---------------------------------------------------------------- aviso de preço no runner
def _runner_saida(monkeypatch, capsys):
    from app.jobs import runner
    monkeypatch.setattr(runner, "rodar_ciclo", lambda: {"handoffs": 0, "gastos": 0})
    assert runner.main(["--sem-trava", "--uma-vez", "--sem-remarketing"]) == 0
    return capsys.readouterr().out


def test_runner_avisa_quando_falta_preco(monkeypatch, capsys):
    saida = _runner_saida(monkeypatch, capsys)
    assert "preço da IA não cadastrado" in saida


def test_runner_nao_avisa_com_precos(monkeypatch, capsys):
    for item, valor in (("ia.entrada", 0.3), ("ia.saida", 2.5), ("cambio.usd_brl", 5.5)):
        precos.cadastrar_preco(item, valor, "2020-01-01")
    saida = _runner_saida(monkeypatch, capsys)
    assert "preço da IA não cadastrado" not in saida

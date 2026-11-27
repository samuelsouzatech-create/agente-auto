"""
M2: loja de demonstração, simulador (leitura) e ensaio na bancada. OFFLINE, LLM falso, duas lojas.
"""
import asyncio
import json
import os
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from app import demo, lojas


def _ler(sql, parametros=()):
    conexao = banco.conectar()
    try:
        return [dict(l) for l in conexao.execute(sql, parametros).fetchall()]
    finally:
        conexao.close()


def _sql(sql, parametros=()):
    conexao = banco.conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


@pytest.fixture
def fotos(tmp_path):
    return tmp_path / "fotos"


@pytest.fixture
def loja_demo(fotos):
    from app.ator import como_sistema
    _sql("INSERT OR IGNORE INTO lojas (id, nome, segmento, config) VALUES (1, 'Loja Real', 'veiculos', '{}')")
    _sql("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco) "
         "VALUES (1, 'Fiat', 'Uno', 2015, 90000, 'Branco', 'Manual', 30000)")
    _sql("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo) VALUES ('real-1', 1, 'whatsapp', 'cliente', 'oi')")
    with como_sistema("Teste", "job"):
        loja_id = demo.criar_loja_demo(indexar=False)
    return loja_id


def _contagem(loja_id):
    return {t: _ler(f"SELECT COUNT(*) n FROM {t} WHERE loja_id = ?", (loja_id,))[0]["n"]
            for t in ("estoque", "mensagens", "leads", "handoffs", "agendamentos", "vendas",
                      "remarketing_envios", "regua_execucoes", "uso_custos", "conhecimento", "usuarios")}


# ------------------------------------------------------------ D1

def test_loja_demo_completa_e_segura(loja_demo, fotos):
    n = _contagem(loja_demo)
    assert 15 <= _ler("SELECT COUNT(*) n FROM estoque WHERE loja_id = ? AND status = 'disponivel'",
                      (loja_demo,))[0]["n"] <= 20
    assert n["vendas"] == len(demo.VENDIDOS_DEMO) and n["regua_execucoes"] > 0      # pós-venda agendado
    assert n["leads"] >= 30 and n["handoffs"] > 0 and n["agendamentos"] > 0 and n["remarketing_envios"] > 0
    assert n["conhecimento"] == 4 and n["usuarios"] == 4 and n["uso_custos"] > 0
    loja = lojas.carregar_loja(loja_demo)
    assert loja.nome == demo.NOME_DEMO and loja.get("demo") is True
    assert not any(loja.get(f"envio_real.{t}") for t in ("remarketing", "pos_venda", "reativacao"))
    assert _ler("SELECT estado FROM estado_lojas WHERE loja_id = ?", (loja_demo,))[0]["estado"] == "no_ar"
    assert _ler("SELECT COUNT(*) n FROM canais WHERE loja_id = ?", (loja_demo,))[0]["n"] == 0   # só simulador
    pessoas = _ler("SELECT nome, contato_whatsapp, contato_telegram FROM usuarios WHERE loja_id = ?", (loja_demo,))
    assert all("fictíci" in p["nome"] and not p["contato_whatsapp"] and not p["contato_telegram"] for p in pessoas)
    assert "fictício" in loja.get("endereco")


def test_fotos_ilustrativas_geradas_localmente(loja_demo, fotos):
    # Maratona Fotos: as fotos da demo passam pelo preparo e ficam no depósito (referências).
    import io
    from app import fotos as deposito_de_fotos
    refs = [l["fotos"] for l in _ler("SELECT fotos FROM estoque WHERE loja_id = ?", (loja_demo,))]
    assert refs and all(deposito_de_fotos.chave_da_ref(loja_demo, r) for r in refs)
    from PIL import Image
    imagem = Image.open(io.BytesIO(deposito_de_fotos.ler(loja_demo, refs[0])))
    assert imagem.format == "JPEG" and imagem.size == (800, 600)      # BA3: 4:3, como o cartão do estoque


def test_politicas_na_base(loja_demo):
    textos = " ".join(l["texto"] for l in _ler("SELECT texto FROM conhecimento WHERE loja_id = ?", (loja_demo,)))
    assert "20%" in textos and "CNH" in textos and "3 meses" in textos and "do banco" in textos


# ------------------------------------------------------------ D3

def test_reiniciar_duas_vezes_termina_igual_e_nao_toca_outra_loja(loja_demo, fotos):
    from app.ator import como
    antes_real = (_contagem(1), _ler("SELECT * FROM mensagens WHERE loja_id = 1"))
    with como("Operador", "operador", "painel"):
        demo.reiniciar_demo(loja_demo, indexar=False)
        primeira = _contagem(loja_demo)
        demo.reiniciar_demo(loja_demo, indexar=False)
    assert _contagem(loja_demo) == primeira
    assert (_contagem(1), _ler("SELECT * FROM mensagens WHERE loja_id = 1")) == antes_real
    assert len(_ler("SELECT id FROM registro_acoes WHERE acao = 'reiniciar_demo' AND loja_id = ?", (loja_demo,))) == 2


def test_reiniciar_recusa_loja_que_nao_e_demo(loja_demo, fotos):
    from app.ator import como
    antes = _contagem(1)
    with como("Operador", "operador", "painel"), pytest.raises(demo.LojaNaoEDemo):
        demo.reiniciar_demo(1, indexar=False)
    assert _contagem(1) == antes


def test_reiniciar_apaga_o_que_a_demonstracao_criou(loja_demo, fotos):
    from app.ator import como
    _sql("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo) VALUES ('sim-x', ?, 'simulador', 'cliente', 'oi')",
         (loja_demo,))
    with como("Operador", "operador", "painel"):
        demo.reiniciar_demo(loja_demo, indexar=False)
    assert _ler("SELECT id FROM mensagens WHERE lead_id = 'sim-x'") == []


# ------------------------------------------------------------ D2 (leitura do simulador)

def test_cabecalho_e_aviso_ao_vendedor(loja_demo):
    from tools import acionar_handoff
    topo = demo.cabecalho_do_simulador(loja_demo)
    assert topo == {"agente": "Léo", "loja": demo.NOME_DEMO, "demo": True}
    acionar_handoff.func(motivo="Cliente pediu desconto.", resumo="Quer o Corolla por 115 mil.",
                         lead_id="sim-1", loja_id=loja_demo)
    [aviso] = demo.avisos_ao_vendedor(loja_demo, "sim-1")
    assert aviso["motivo"] == "Cliente pediu desconto." and aviso["situacao"] == "esperando um vendedor"
    assert demo.avisos_ao_vendedor(1, "sim-1") == []                     # outra loja não vê


def test_simulador_sem_id_na_tela():
    from pathlib import Path
    texto = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert "(id {" not in texto and "O vendedor recebeu" in texto and "avisos_ao_vendedor" in texto


# ------------------------------------------------------------ ensaio na bancada

@pytest.fixture
def bancada(monkeypatch, tmp_path):
    from scripts import rodar_bancada as rb
    monkeypatch.setattr(rb, "_PASTA_TEMP", tmp_path / "bancada")
    (tmp_path / "bancada").mkdir()
    return rb


def test_roteiros_demo_so_com_loja_demo(bancada):
    normais = {r["nome"] for r in bancada.carregar_roteiros()}
    da_demo = {r["nome"] for r in bancada.carregar_roteiros(demo=True)}
    assert da_demo and all(n.startswith("demo_") for n in da_demo) and not normais & da_demo


class Grafo:
    def __init__(self):
        self.vistos = []

    def invoke(self, entrada, config=None):
        from app.lojas import carregar_loja
        self.vistos.append(carregar_loja(entrada["loja_id"]).nome)
        return {"messages": [HumanMessage(content=entrada["messages"][0].content),
                             AIMessage(content=f"Resposta {len(self.vistos)}.")]}


def test_ensaio_roda_contra_a_loja_demo_e_vendedor_assume(bancada, monkeypatch):
    rb = bancada
    monkeypatch.setattr(rb, "_LOJA_DEMO", True)
    [roteiro] = [r for r in rb.carregar_roteiros(demo=True) if r["nome"] == "demo_vendedor_assume"]
    grafo = Grafo()
    rodada = asyncio.run(rb.rodar([roteiro], grafo, teto=1.0))
    res = rodada.resultados[0]
    assert grafo.vistos and set(grafo.vistos) == {demo.NOME_DEMO}
    assert res.turnos[-1].silenciado and not res.turnos[-1].bolhas
    assert any("silêncio na última fala: sim" in o for o in res.ok)


def test_mudar_config_no_meio_do_roteiro(bancada, monkeypatch):
    rb = bancada
    monkeypatch.setattr(rb, "_LOJA_DEMO", True)
    tons = []

    class GrafoTom(Grafo):
        def invoke(self, entrada, config=None):
            from app.lojas import carregar_loja
            tons.append(carregar_loja(entrada["loja_id"]).get("tom"))
            return super().invoke(entrada, config)

    [roteiro] = [r for r in rb.carregar_roteiros(demo=True) if r["nome"] == "demo_tom_trocado"]
    asyncio.run(rb.rodar([roteiro], GrafoTom(), teto=1.0))
    assert tons[0] == demo.CONFIG_DEMO["tom"] and tons[-1].startswith("formal")


def test_nome_da_foto_ilustrativa_fica_inteiro_no_cartao_do_estoque():
    """BA3: o cartão do estoque mostra a foto em 4:3 e corta o que passa; o nome tem de caber no meio,
    longe das pontas (antes: "ota Corolla")."""
    import io
    from PIL import Image
    from app.demo import MARGEM_DO_TEXTO, desenhar_foto_ilustrativa
    imagem = Image.open(io.BytesIO(desenhar_foto_ilustrativa("Volkswagen", "Nivus Highline", 2023, "Prata")))
    largura, altura = imagem.size
    assert largura * 3 == altura * 4                                   # 4:3
    faixa = imagem.convert("L").crop((0, 20, largura, 140))            # onde fica o nome
    escuros = [x for x in range(largura) if any(faixa.getpixel((x, y)) < 100 for y in range(faixa.height))]
    assert escuros and min(escuros) >= MARGEM_DO_TEXTO - 5 and max(escuros) <= largura - MARGEM_DO_TEXTO + 5
    assert abs((min(escuros) + max(escuros)) / 2 - largura / 2) < 40   # centralizado

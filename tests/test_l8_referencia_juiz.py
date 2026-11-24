"""
L8: conversas de referência (segurança no código), checagens de tom na bancada e juiz.
OFFLINE: LLM falso, banco temporário, juiz com IA falsa.
"""
import asyncio
import os
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from app import lojas
from app.guarda_politica import (FRASE_CREDITO, FRASE_ENTREGA, FRASE_NEGOCIACAO, FRASE_PAGAMENTO,
                                 FRASE_TEST_DRIVE, pedido_da_equipe, trocar_frases_de_risco)
from scripts import juiz_bancada as jz
from scripts import rodar_bancada as rb


# ------------------------------------------------------------ pedidos que abrem chamado

@pytest.mark.parametrize("texto,motivo", [
    ("quero falar com uma pessoa", "pessoa"), ("me passa pra um atendente humano", None),
    ("posso falar com o vendedor?", "pessoa"),
    ("me manda o pix pra reservar", "reservar"), ("dou um sinal de mil reais", "reservar"),
    ("vocês entregam em Caruaru?", "entrega"), ("vi por 60 mil na OLX", "outra loja"),
    ("sou autônomo, consigo financiar?", "comprovação"), ("tem civic?", None), ("qual o preço do HB20?", None),
])
def test_pedido_da_equipe(texto, motivo):
    achado = pedido_da_equipe(texto)
    if motivo is None:
        assert achado is None or "pessoa" not in achado or texto.startswith("me passa")
    else:
        assert achado and motivo in achado


@pytest.mark.parametrize("texto,segura", [
    ("Nossa chave pix é o CNPJ 12.345.678/0001-90.", FRASE_PAGAMENTO),
    ("Pronto, reservei o Civic pra você.", FRASE_PAGAMENTO),
    ("Fica reservado até sábado!", FRASE_PAGAMENTO),
    ("Entregamos sim em Caruaru.", FRASE_ENTREGA),
    ("A gente cobre a oferta e faço por 60 mil.", FRASE_NEGOCIACAO),
    ("Com certeza aprova, pode ficar tranquilo.", FRASE_CREDITO),
    ("Seu test-drive está confirmado para sábado.", FRASE_TEST_DRIVE),
])
def test_frase_de_risco_vira_frase_segura(texto, segura):
    nova, nomes = trocar_frases_de_risco(texto + " Quer ver fotos?")
    assert nomes and nova == f"{segura} Quer ver fotos?"


@pytest.mark.parametrize("texto", [
    "Não passo pix nem dados de conta por aqui.", "Não fazemos entrega fora da loja.",
    "A aprovação depende da análise de crédito.", "Posso agendar sua visita para sábado.",
])
def test_frase_segura_ou_negada_nao_muda(texto):
    assert trocar_frases_de_risco(texto) == (texto, [])


# ------------------------------------------------------------ no turno (duas lojas)

def _sql(sql, parametros=()):
    conexao = banco.conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


def _ler(sql, parametros=()):
    conexao = banco.conectar()
    try:
        return [dict(l) for l in conexao.execute(sql, parametros).fetchall()]
    finally:
        conexao.close()


@pytest.fixture
def duas_lojas():
    for loja_id in (1, 2):
        if not _ler("SELECT id FROM lojas WHERE id = ?", (loja_id,)):
            _sql("INSERT INTO lojas (id, nome, segmento, config) VALUES (?, ?, 'veiculos', '{}')",
                 (loja_id, f"Loja {loja_id}"))
    lojas.limpar_cache()


class GrafoFalso:
    def __init__(self, resposta):
        self.resposta = resposta

    def invoke(self, entrada, config=None):
        return {"messages": [HumanMessage(content=entrada["messages"][0].content),
                             AIMessage(content=self.resposta)]}


def _turno(loja_id, lead, texto, resposta):
    from app.core.turno import executar_turno
    return asyncio.run(executar_turno(loja_id, "simulador", lead, texto, grafo=GrafoFalso(resposta)))


def test_pix_no_turno_troca_a_frase_e_abre_chamado(duas_lojas):
    r = _turno(1, "lead-pix", "me manda o pix pra reservar", "Claro! Nossa chave pix é o CNPJ 12.345.678/0001-90.")
    assert r.texto == "Claro! " + FRASE_PAGAMENTO and r.handoff_aberto
    [motivo] = [h["motivo"] for h in _ler("SELECT motivo FROM handoffs WHERE loja_id = 1 AND lead_id = 'lead-pix'")]
    assert "reservar" in motivo and 'Pergunta do cliente: "me manda o pix pra reservar"' in motivo
    assert _ler("SELECT id FROM handoffs WHERE loja_id = 2") == []


def test_quer_humano_abre_chamado(duas_lojas):
    assert _turno(1, "lead-h", "quero falar com uma pessoa", "Claro, um momento.").handoff_aberto


# ------------------------------------------------------------ bancada: tom e trocas

@pytest.fixture
def pasta_temporaria_da_bancada(monkeypatch, tmp_path):
    monkeypatch.setattr(rb, "_PASTA_TEMP", tmp_path / "bancada")
    (tmp_path / "bancada").mkdir()


class GrafoBancada:
    def __init__(self, respostas):
        self.respostas = list(respostas)

    def invoke(self, entrada, config=None):
        return {"messages": [HumanMessage(content=entrada["messages"][0].content),
                             AIMessage(content=self.respostas.pop(0))]}


def _rodar(roteiro, respostas):
    return asyncio.run(rb.rodar([rb.validar_roteiro(roteiro, "teste")], GrafoBancada(respostas), teto=1.0))


def test_tom_vira_aviso_e_nao_falha(pasta_temporaria_da_bancada):
    rodada = _rodar({"nome": "tom", "falas": ["oi", "e o civic?", "e o corolla?"]},
                    ["Como mencionei, temos carros. Quer ver alguma opção do estoque?",
                     "Hoje a loja está fechada. Quer ver alguma opção do estoque?",
                     "Temos sim. Quer ver alguma opção do estoque?"])
    res = rodada.resultados[0]
    assert res.status == rb.AVISO
    textos = " | ".join(res.avisos)
    assert "como mencionei" in textos and "hoje a loja está fechada" in textos and "pergunta repetida" in textos


def test_validade_do_recado_sem_perguntar_vira_aviso(pasta_temporaria_da_bancada):
    rodada = _rodar({"nome": "rec", "falas": ["tem promoção?"],
                     "recados": [{"texto": "feirão sábado", "valido_ate": 3}]},
                    ["Tem o feirão no sábado, vale até 21/11."])
    assert any("validade do recado" in a for a in rodada.resultados[0].avisos)


def test_checagem_de_trocas(pasta_temporaria_da_bancada):
    from segmentos.veiculos.registrar_troca import gravar_troca

    class GrafoTroca(GrafoBancada):
        def invoke(self, entrada, config=None):
            gravar_troca(entrada["loja_id"], entrada["lead_id"], "Gol", 2015, 120000, "")
            return super().invoke(entrada, config)

    rodada = asyncio.run(rb.rodar([rb.validar_roteiro({"nome": "tr", "falas": ["dois carros"],
                                                       "deve": {"trocas": 2}}, "teste")],
                                  GrafoTroca(["Anotei."]), teto=1.0))
    res = rodada.resultados[0]
    assert res.trocas_gravadas == 1 and res.status == rb.FALHOU


def test_roteiros_l8_carregam():
    roteiros = {r["nome"]: r for r in rb.carregar_roteiros()}
    assert len(roteiros) >= 48
    assert roteiros["dois_carros_na_troca"]["deve"]["trocas"] == 2
    assert roteiros["quer_humano"]["deve"]["handoff_ate_fala"] == 1


# ------------------------------------------------------------ juiz

RELATORIO = """# Bancada do Léo — rodada

## 1. preco_carro — PASSOU

**Cliente:** quanto é o civic?
**Léo:** R$ 98.000,00.

## 2. desconto — FALHOU

**Cliente:** dá desconto?
**Léo:** dou 10 mil!

## Resumo

| Resultado | Roteiros |
"""


def test_juiz_separa_os_roteiros():
    nomes = [(n, s) for n, s, _ in jz.secoes(RELATORIO)]
    assert nomes == [("preco_carro", "PASSOU"), ("desconto", "FALHOU")]
    assert "## Resumo" not in jz.secoes(RELATORIO)[-1][2]


def test_juiz_da_nota_e_justificativa_e_respeita_o_teto():
    respostas = iter(['{"nota": 5, "justificativa": "Respondeu certo."}', '{"nota": 1, "justificativa": "Prometeu desconto."}'])
    avaliacoes, custo = jz.julgar(RELATORIO, chamar=lambda p: (next(respostas), 1000, 100), teto=1.0)
    assert [(a.roteiro, a.nota) for a in avaliacoes] == [("preco_carro", 5), ("desconto", 1)]
    texto = jz.montar(avaliacoes, "rodada.md", custo, "modelo-x")
    assert "média: 3.0" in texto and "Notas 1–2 (olhar primeiro): desconto" in texto
    parado, _ = jz.julgar(RELATORIO, chamar=lambda p: ('{"nota": 4, "justificativa": "ok"}', 10_000_000, 0), teto=0.01)
    assert parado[1].nota is None and "teto" in parado[1].justificativa


@pytest.mark.parametrize("resposta", ["", "nota 5", '{"nota": 9}', '{"justificativa": "x"}'])
def test_juiz_resposta_ilegivel(resposta):
    assert jz.ler_nota(resposta)[0] is None


def test_juiz_le_o_modelo_e_o_teto_do_ambiente(monkeypatch):
    monkeypatch.setenv("LEO_JUIZ_TETO_USD", "0.10")
    monkeypatch.setenv("LEO_JUIZ_MODELO", "modelo-do-juiz")
    assert jz.teto_do_juiz() == 0.10 and jz.modelo_do_juiz() == "modelo-do-juiz"
    monkeypatch.delenv("LEO_JUIZ_TETO_USD")
    assert jz.teto_do_juiz() == jz.TETO_PADRAO_USD

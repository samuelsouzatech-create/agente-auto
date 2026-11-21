"""
L11: o texto antes da ferramenta chega ao cliente; fato sobre a loja só se estiver na base
ou no cadastro. OFFLINE, LLM falso, duas lojas, base de conhecimento falsa na bancada.
"""
import asyncio
import importlib
import os
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from app import lojas
from app.guarda_politica import (FRASE_ENTRADA, FRASE_ENTREGA_CONFIRMA, FRASE_FOTO_AGORA,
                                 FRASE_PAGAMENTO_EXPLICA, FRASE_PROMOCAO, corrigir_regra_de_entrada,
                                 trocar_politica_sem_base)

LOJA_A, LOJA_B = 1, 2


# ------------------------------------------------------------ política sem base

@pytest.mark.parametrize("texto,segura", [
    ("Sobre o Civic, não trabalhamos com reserva via Pix.", FRASE_PAGAMENTO_EXPLICA),
    ("Não aceitamos sinal para segurar o carro.", FRASE_PAGAMENTO_EXPLICA),
    ("Verifiquei aqui e nossa política não menciona entrega em outras cidades.", FRASE_ENTREGA_CONFIRMA),
    ("Não realizamos entrega fora de Recife.", FRASE_ENTREGA_CONFIRMA),
    ("Sobre o Civic, nós não enviamos fotos pelo chat.", FRASE_FOTO_AGORA),
    ("A loja não envia fotos por aqui.", FRASE_FOTO_AGORA),
    ("Nós não trabalhamos com promoções específicas.", FRASE_PROMOCAO),
])
def test_politica_afirmada_vira_frase_segura(texto, segura):
    nova, temas = trocar_politica_sem_base(texto + " Quer ver o carro?")
    assert temas and nova == f"{segura} Quer ver o carro?"


@pytest.mark.parametrize("texto", [
    "Não trabalhamos com consórcio.",                 # está na base: fica
    "Aceitamos Pix, transferência ou dinheiro à vista.",
    "Não tenho fotos desse carro para mandar.",
    "O pessoal da equipe explica como funciona a reserva.",
])
def test_frase_que_nao_afirma_politica_sem_base_fica(texto):
    assert trocar_politica_sem_base(texto) == (texto, [])


@pytest.mark.parametrize("texto", [
    "Sobre a entrada, não temos um valor fixo ou regra de porcentagem mínima.",
    "Sobre a entrada: não temos mínimo, depende da análise.",
    "Quanto à entrada, depende. Não temos um valor fixo ou mínimo.",
])
def test_nao_temos_minimo_de_entrada_e_trocado(texto):
    nova, trocou = corrigir_regra_de_entrada(texto)
    assert trocou and FRASE_ENTRADA in nova and "não temos" not in nova.lower()


def test_entrada_da_base_fica():
    texto = "A entrada recomendada é de 20%, mas depende da análise de crédito."
    assert corrigir_regra_de_entrada(texto) == (texto, False)


def test_nao_temos_valor_fixo_fora_do_assunto_entrada_fica():
    texto = "Para a troca, não temos um valor fixo: a avaliação é presencial."
    assert corrigir_regra_de_entrada(texto) == (texto, False)


def test_prompt_manda_usar_a_base_e_nao_afirmar_politica():
    from app.core.montagem import pasta_do_segmento
    texto = (pasta_do_segmento("veiculos") / "prompt.md").read_text(encoding="utf-8")
    assert "a recomendada é 20%, mas depende da análise de crédito" in texto
    assert "nunca \"não trabalhamos com\"" in texto


def test_doc_de_instalacao_lista_as_perguntas():
    from pathlib import Path
    doc = (Path(__file__).resolve().parents[1] / "docs" / "instalacao_loja.md").read_text(encoding="utf-8")
    for tema in ("Garantia", "Entrada", "Prazos", "Documentos", "Test-drive", "Troca", "Entrega", "Reserva"):
        assert tema in doc


# ------------------------------------------------------------ texto antes da ferramenta (turno)

def _sql(sql, parametros=()):
    conexao = banco.conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


@pytest.fixture
def duas_lojas():
    for loja_id in (LOJA_A, LOJA_B):
        _sql("INSERT OR IGNORE INTO lojas (id, nome, segmento, config) VALUES (?, ?, 'veiculos', '{}')",
             (loja_id, f"Loja {loja_id}"))
    lojas.limpar_cache()


class GrafoComTool:
    """Escreve texto E chama acionar_handoff na mesma mensagem; depois fecha com outra frase."""

    def __init__(self, antes, depois):
        self.antes, self.depois = antes, depois

    def invoke(self, entrada, config=None):
        from tools import acionar_handoff
        acionar_handoff.func(motivo="m", resumo="r", lead_id=entrada["lead_id"], loja_id=entrada["loja_id"])
        return {"messages": [HumanMessage(content=entrada["messages"][0].content),
                             AIMessage(content=self.antes, tool_calls=[{"name": "acionar_handoff", "args": {}, "id": "h"}]),
                             ToolMessage(content="Handoff acionado.", tool_call_id="h", name="acionar_handoff"),
                             AIMessage(content=self.depois)]}


def _turno(loja_id, lead, texto, grafo):
    from app.core.turno import executar_turno
    return asyncio.run(executar_turno(loja_id, "simulador", lead, texto, grafo=grafo))


def test_texto_antes_da_ferramenta_chega_ao_cliente(duas_lojas):
    grafo = GrafoComTool("Sobre o financiamento, a análise de crédito é feita individualmente.",
                         "O pessoal da equipe vai falar com você por aqui.")
    r = _turno(LOJA_A, "lt1", "consigo financiar com nome sujo?", grafo)
    assert r.texto == ("Sobre o financiamento, a análise de crédito é feita individualmente.\n\n"
                       "O pessoal da equipe vai falar com você por aqui.")


def test_promessa_repetida_antes_da_ferramenta_sai(duas_lojas):
    grafo = GrafoComTool("Oi! Vou confirmar o endereço com o pessoal da equipe.",
                         "O pessoal da equipe vai falar com você por aqui.")
    r = _turno(LOJA_A, "lt2", "qual o endereço?", grafo)
    assert r.texto == "Oi!\n\nO pessoal da equipe vai falar com você por aqui."


def test_sem_ferramenta_continua_igual(duas_lojas):
    class Simples:
        def invoke(self, entrada, config=None):
            return {"messages": [HumanMessage(content=entrada["messages"][0].content), AIMessage(content="Temos sim!")]}
    assert _turno(LOJA_B, "lt3", "tem civic?", Simples()).texto == "Temos sim!"


# ------------------------------------------------------------ bancada

@pytest.fixture
def bancada(monkeypatch, tmp_path):
    from scripts import rodar_bancada as rb
    monkeypatch.setattr(rb, "_PASTA_TEMP", tmp_path / "bancada")
    (tmp_path / "bancada").mkdir()
    return rb


def test_bancada_falha_se_o_texto_antes_da_tool_se_perder(bancada, monkeypatch):
    rb = bancada
    from app.core import turno
    # Simula o defeito antigo (só a última mensagem sai) para provar que a checagem pega.
    monkeypatch.setattr(turno, "resposta_do_turno",
                        lambda do_turno, ultima: turno.limpar_markdown(turno.extrair_texto(ultima.content)))
    rodada = asyncio.run(rb.rodar([rb.validar_roteiro({"nome": "t", "falas": ["consigo financiar?"]}, "t")],
                                  GrafoComTool("Sobre o financiamento, a análise de crédito é feita individualmente.",
                                               "O pessoal da equipe vai falar com você por aqui."), teto=1.0))
    res = rodada.resultados[0]
    assert res.status == rb.FALHOU and any("antes da ferramenta" in f for f in res.falhas)


def test_bancada_avisa_chamado_que_so_promete_contato_e_politica(bancada):
    rb = bancada
    rodada = asyncio.run(rb.rodar([rb.validar_roteiro({"nome": "t2", "falas": ["qual o endereço?"]}, "t")],
                                  GrafoComTool("Oi!", "O pessoal da equipe vai falar com você por aqui."), teto=1.0))
    assert any("não toca no assunto do cliente" in a for a in rodada.resultados[0].avisos)   # L12

    class Politica:
        def invoke(self, entrada, config=None):
            return {"messages": [HumanMessage(content="x"), AIMessage(content="Nós não fazemos test-drive aos domingos.")]}
    rodada = asyncio.run(rb.rodar([rb.validar_roteiro({"nome": "t3", "falas": ["e domingo?"]}, "t")], Politica(), teto=1.0))
    res = rodada.resultados[0]
    assert res.status == rb.AVISO and any("afirmação de política" in a for a in res.avisos)


def test_base_ficticia_do_roteiro(bancada):
    rb = bancada
    from tools.buscar_conhecimento import buscar_conhecimento
    original = importlib.import_module("tools.buscar_conhecimento")._get_banco_conhecimento
    with rb.base_ficticia(["SÓ ESTE TEXTO DA BASE"]):
        assert buscar_conhecimento.invoke({"pergunta": "entrada?", "loja_id": 1}) == "SÓ ESTE TEXTO DA BASE"
    assert importlib.import_module("tools.buscar_conhecimento")._get_banco_conhecimento is original
    with pytest.raises(rb.RoteiroInvalido):
        rb.validar_roteiro({"nome": "x", "falas": ["oi"], "conhecimento": "texto solto"}, "t")


def test_roteiros_l11(bancada):
    rb = bancada
    roteiros = {r["nome"]: r for r in rb.carregar_roteiros()}
    assert len(roteiros) == _total_de_roteiros()
    assert "20%" not in roteiros["entrada_sem_base"]["conhecimento"][0]
    assert "não trabalhamos" in roteiros["pede_pix_reserva"]["nao_contem"]
    assert "não realizamos" in roteiros["entrega_outra_cidade"]["nao_contem"]
    assert "não enviamos" in roteiros["fotos_modulo_desligado"]["nao_contem"]
    assert "não temos mínimo" in roteiros["entrada_minima"]["nao_contem"]


def _total_de_roteiros() -> int:
    """N2 (revisão #26): conta os arquivos (sem os da demo), em vez de um número fixo."""
    from pathlib import Path as _P
    pasta = _P(__file__).resolve().parents[1] / "bancada" / "roteiros"
    return len([c for c in pasta.glob("*.yaml") if not c.stem.startswith("demo_")])

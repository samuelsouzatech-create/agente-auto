"""
M1 (L13): fechar a Fase Cérebro. Textos reais das rodadas de 19/11. OFFLINE, LLM falso, duas lojas.
"""
import asyncio
import os
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from app import lojas
from segmentos.veiculos.guardas import FRASE_ESTADO, cortar_estado_inventado                 # SG1: guardas do ramo
from app.guarda_politica import (FRASE_CREDITO, FRASE_ENTRADA, FRASE_OFERTA, FRASE_PROMOCAO,
                                 corrigir_regra_de_entrada, limpar_repeticoes,
                                 tirar_texto_interno, trocar_frases_de_risco, trocar_politica_sem_base)

LOJA_A, LOJA_B = 1, 2

# pos_venda_irritado, rodada_2026-11-19_013159 (texto que chegou ao cliente)
IRRITADO = ("Sinto muito que esteja passando por isso. Entendo sua frustração e quero te ajudar a resolver essa "
            "situação da melhor forma. [Resumo: Cliente relata problema no Chevrolet Onix 2020 comprado em "
            "23/11/2026 e manifesta insatisfação com o atendimento pós-venda.] Sinto muito que esteja passando por "
            "isso. O pessoal da equipe vai falar com você por aqui.")


# ------------------------------------------------------------ 2. texto interno

def test_resumo_entre_colchetes_nao_chega_ao_cliente():
    novo, mudou = tirar_texto_interno(IRRITADO)
    assert mudou and "[" not in novo and "Resumo" not in novo and "23/11/2026" not in novo
    assert novo.startswith("Sinto muito que esteja passando por isso.")


@pytest.mark.parametrize("texto", [
    "Resumo: cliente quer desconto.\nO pessoal da equipe vai falar com você.",
    "Vou chamar acionar_handoff agora. O pessoal da equipe vai falar com você.",
    "Motivo: cliente irritado. O pessoal da equipe vai falar com você.",
])
def test_rotulo_interno_e_nome_de_ferramenta_saem(texto):
    novo, mudou = tirar_texto_interno(texto)
    assert mudou and novo == "O pessoal da equipe vai falar com você."


def test_texto_normal_nao_muda():
    texto = "Temos o Civic 2019!\n\n- Automático\n- 48 mil km"
    assert tirar_texto_interno(texto) == (texto, False)


# ------------------------------------------------------------ 3. limpeza sem perder o assunto

def test_frase_que_cita_o_assunto_fica():
    texto = ("Sobre o leilão, o pessoal da equipe vai verificar e falar com você por aqui. Como a loja está "
             "fechada agora, eles retomam o atendimento hoje, a partir das 08:00, e vão falar com você por aqui.")
    limpo = limpar_repeticoes(texto, pergunta="ele já foi de leilão?")
    assert "Sobre o leilão" in limpo and "08:00" in limpo


def test_sem_pergunta_continua_tirando_contato_repetido():
    texto = ("O pessoal da equipe vai falar com você por aqui. Como a loja está fechada agora, eles retomam o "
             "atendimento hoje, a partir das 08:00, e vão falar com você por aqui.")
    assert limpar_repeticoes(texto).count("falar com você por aqui") == 1


# ------------------------------------------------------------ 4. lista e frase quase igual depois das guardas

def test_guarda_nao_junta_a_lista():
    texto = "Temos estes:\n- Civic 2019\n- Corolla 2021\nNão enviamos fotos pelo chat."
    novo, temas = trocar_politica_sem_base(texto)
    assert temas == ["fotos"] and novo.split("\n")[:3] == ["Temos estes:", "- Civic 2019", "- Corolla 2021"]


def test_entrada_sem_base_frase_quase_igual_sai():
    # entrada_sem_base, rodada 3 de 18/11
    texto = ("O valor da entrada depende da análise de crédito, feita por um vendedor. O financiamento é feito "
             "através de bancos parceiros e a análise de crédito, que define as condições, é feita por um vendedor.")
    novo, _ = corrigir_regra_de_entrada(texto)
    novo, _ = trocar_frases_de_risco(novo)
    assert "feita por um vendedor" not in novo


# ------------------------------------------------------------ 5. estado do carro

def test_garanto_verificacao_no_estoque_sai():
    texto = "Posso te garantir que todos os nossos veículos passam por uma verificação. Quer marcar uma visita?"
    novo, trocou = cortar_estado_inventado(texto)
    assert trocou and novo == f"{FRASE_ESTADO} Quer marcar uma visita?"


def test_elogio_ou_pos_venda_so_apaga():
    assert cortar_estado_inventado("É um excelente carro. Qualquer coisa, me chama.") == ("Qualquer coisa, me chama.", True)
    assert cortar_estado_inventado("Ele é revisado. Qualquer coisa, me chama.", substituir=False) == (
        "Qualquer coisa, me chama.", True)


def test_revisao_sem_carro_fica():
    texto = "A revisão das 10 mil fica por sua conta."
    assert cortar_estado_inventado(texto) == (texto, False)


# ------------------------------------------------------------ 6 e 7. promoção e crédito

def test_nao_temos_promocao_vira_vou_confirmar():
    novo, temas = trocar_politica_sem_base("No momento não temos promoção vigente.")
    assert temas == ["promocao"] and novo == FRASE_PROMOCAO


@pytest.mark.parametrize("texto", [
    "A análise de crédito é feita por um vendedor da nossa equipe.",
    "Nosso vendedor faz a análise de crédito com você.",
])
def test_credito_feito_por_vendedor_vira_banco(texto):
    novo, nomes = trocar_frases_de_risco(texto)
    assert "credito_vendedor" in nomes and novo == FRASE_CREDITO


def test_frases_seguras_falam_do_banco():
    assert "do banco" in FRASE_CREDITO and "do banco" in FRASE_ENTRADA and "feita por um vendedor" not in FRASE_CREDITO


def test_prompts_sem_analise_feita_por_vendedor():
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[1]
    for arquivo in ("prompts/base.md", "segmentos/veiculos/prompt.md", "tools/simular_financiamento.py"):
        assert "feita por um vendedor" not in (raiz / arquivo).read_text(encoding="utf-8"), arquivo


# ------------------------------------------------------------ no turno (duas lojas)

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


class Grafo:
    def __init__(self, antes, depois):
        self.antes, self.depois = antes, depois

    def invoke(self, entrada, config=None):
        from tools import acionar_handoff
        acionar_handoff.func(motivo="m", resumo="r", lead_id=entrada["lead_id"], loja_id=entrada["loja_id"])
        return {"messages": [HumanMessage(content=entrada["messages"][0].content),
                             AIMessage(content=self.antes, tool_calls=[{"name": "acionar_handoff", "args": {}, "id": "h"}]),
                             ToolMessage(content="Handoff acionado.", tool_call_id="h", name="acionar_handoff"),
                             AIMessage(content=self.depois)]}


def test_turno_tira_o_resumo_e_mantem_o_assunto(duas_lojas):
    from app.core.turno import executar_turno
    r = asyncio.run(executar_turno(LOJA_A, "simulador", "m1", "isso é um absurdo, vou no Procon",
                                   grafo=Grafo(IRRITADO, "O pessoal da equipe vai falar com você por aqui.")))
    assert "[" not in r.texto and "Resumo" not in r.texto and r.texto.count("Sinto muito") == 1


def test_guarda_cortou_a_pergunta_final_entra_a_oferta(duas_lojas):
    from app.core.turno import executar_turno

    class Simples:
        def invoke(self, entrada, config=None):
            return {"messages": [HumanMessage(content="x"),
                                 AIMessage(content="Temos o Civic 2019. Seguem as fotos do Civic, gostou?")]}
    r = asyncio.run(executar_turno(LOJA_B, "simulador", "m2", "tem civic?", grafo=Simples()))
    assert r.texto.endswith(FRASE_OFERTA) and "Seguem as fotos" not in r.texto


# ------------------------------------------------------------ bancada

@pytest.fixture
def bancada(monkeypatch, tmp_path):
    from scripts import rodar_bancada as rb
    monkeypatch.setattr(rb, "_PASTA_TEMP", tmp_path / "bancada")
    (tmp_path / "bancada").mkdir()
    return rb


def test_bancada_falha_texto_interno_e_respostas_iguais(bancada, monkeypatch):
    rb = bancada
    from app.core import turno
    monkeypatch.setattr(turno, "tirar_texto_interno", lambda t, *a: (t, False))  # desliga a guarda

    class Mesmo:
        def invoke(self, entrada, config=None):
            return {"messages": [HumanMessage(content="x"), AIMessage(content="Oi! [Resumo: x] Tudo bem?")]}
    rodada = asyncio.run(rb.rodar([rb.validar_roteiro({"nome": "t", "falas": ["a?", "b?"]}, "t")], Mesmo(), teto=1.0))
    falhas = " | ".join(rodada.resultados[0].falhas)
    assert "texto interno chegou ao cliente" in falhas and "duas respostas seguidas iguais" in falhas


def test_status_corrigido(bancada):
    rb = bancada
    assert rb.decidir([], [], [], None, ["o modelo escreveu x, mas a guarda do código trocou"]) == (rb.CORRIGIDO, None)
    assert rb.decidir([], [], ["tom"], None, ["x"]) == (rb.AVISO, None)
    assert rb.decidir([], [], [], None, []) == (rb.PASSOU, None)


def test_roteiro_52_com_as_palavras_novas(bancada):
    roteiros = {r["nome"]: r for r in bancada.carregar_roteiros()}
    assert "vistoria" in roteiros["estado_do_carro"]["nao_contem"]


# ------------------------------------------------------------ L14: o grave das rodadas do L13

def test_l14_garantia_de_verificacao_com_negacao_longe_sai():
    # estado_do_carro, rodada_2026-11-19_183900 (texto real)
    texto = ("Como sou um assistente virtual, não tenho acesso a detalhes de histórico de colisões, mas posso te "
             "garantir que todos os nossos veículos passam por uma verificação.")
    novo, trocou = cortar_estado_inventado(texto)
    assert trocou and "garantir" not in novo and "verificação" not in novo


@pytest.mark.parametrize("texto", [
    "Não tenho a informação se é único dono.", "Ele não é revisado na concessionária, que eu saiba?",
    "Não posso garantir que ele nunca bateu.",
])
def test_l14_negacao_perto_continua_protegendo(texto):
    assert cortar_estado_inventado(texto) == (texto, False)

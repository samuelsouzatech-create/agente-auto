"""
L12: AVISO certeiro, sem repetição, estado do carro só da ficha, ação só com ferramenta,
chamado nunca silencioso, memória do grafo com limite. OFFLINE, LLM falso, duas lojas.
Os textos de teste são os reais das rodadas de 18/11.
"""
import asyncio
import os
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from app import lojas
from app.guarda_politica import (FRASE_AGENDA, FRASE_CNH, FRASE_CONTATO, FRASE_ESTADO,
                                 cortar_estado_inventado, limpar_repeticoes, tirar_agendamento_falso)

LOJA_A, LOJA_B = 1, 2


def _conta(texto, *trechos):
    t = texto.lower()
    return sum(t.count(x) for x in trechos)


# ------------------------------------------------------------ 2. limpeza (textos reais de 18/11)

SEM_RESPOSTA_R3 = ("Oi! Aqui é Léo, assistente virtual da Auto Bancada Recife. Sobre o Honda Civic 2019 que temos "
                   "aqui, ele está com 48.000 km e custa R$ 98.000,00. O pessoal da equipe vai falar com você por "
                   "aqui, pode ser?\n\nComo a loja está fechada agora, o pessoal da equipe retoma o atendimento "
                   "amanhã, quinta-feira, a partir das 08:00, e vai falar com você por aqui sobre essa dúvida do laudo.")
FINANCIAMENTO_R1 = ("Oi! Aqui é Léo, assistente virtual da Auto Bancada Recife. Sobre o financiamento, a análise de "
                    "crédito é feita individualmente por um vendedor da nossa equipe. O pessoal da equipe vai falar "
                    "com você por aqui.\n\nComo a nossa loja está fechada agora, o pessoal da equipe retoma o "
                    "atendimento amanhã, quinta-feira, a partir das 08:00, e vai falar com você por aqui.")
SINAL_R3 = ("Oi! Aqui é Léo, assistente virtual da Auto Bancada Recife. Sobre pagamento, sinal e reserva, o pessoal "
            "da equipe explica como funciona. Como a loja está fechada agora, eles retomam o atendimento amanhã, "
            "quinta-feira, a partir das 08:00. O pessoal da equipe vai falar com você por aqui. Lembrando que a "
            "loja abre amanhã, quinta-feira, às 08:00.")
ENTRADA_SEM_BASE = ("Oi! Aqui é Léo, assistente virtual da Auto Bancada Recife. O valor da entrada depende da análise "
                    "de crédito, feita por um vendedor. O valor da entrada depende da análise de crédito feita por "
                    "um vendedor. Você já tem algum modelo em mente?")
FOTOS_DESLIGADO = ("Oi! Aqui é Léo, assistente virtual da Auto Bancada Recife. Não consigo enviar fotos por aqui "
                   "agora. O que prefere?")


def test_equipe_vai_falar_e_horario_uma_vez_so():
    for texto in (SEM_RESPOSTA_R3, FINANCIAMENTO_R1, SINAL_R3):
        limpo = limpar_repeticoes(texto)
        assert _conta(limpo, "falar com você por aqui") <= 1, limpo
        assert _conta(limpo, "retoma", "abre amanhã") <= 1, limpo


def test_a_frase_que_tem_horario_e_contato_fica():
    limpo = limpar_repeticoes(SEM_RESPOSTA_R3)
    assert "a partir das 08:00" in limpo and "pode ser?" not in limpo
    assert "R$ 98.000,00" in limpo                     # o resto da resposta continua


def test_frase_quase_igual_sai():
    limpo = limpar_repeticoes(ENTRADA_SEM_BASE)
    assert _conta(limpo, "depende da análise") == 1 and limpo.endswith("Você já tem algum modelo em mente?")


def test_pergunta_sem_opcoes_sai_so_quando_a_guarda_mexeu():
    assert limpar_repeticoes(FOTOS_DESLIGADO, guarda_mexeu=True).endswith("Não consigo enviar fotos por aqui agora.")
    assert limpar_repeticoes(FOTOS_DESLIGADO, guarda_mexeu=False).endswith("O que prefere?")


def test_paragrafos_ficam():
    assert limpar_repeticoes("Primeiro.\n\nSegundo.") == "Primeiro.\n\nSegundo."


# ------------------------------------------------------------ 3. estado do carro

@pytest.mark.parametrize("texto", [
    "Ele é revisado e de único dono.", "Nunca bateu e está sem detalhes.", "Em ótimo estado.",
])
def test_estado_sem_ficha_e_cortado(texto):
    novo, trocou = cortar_estado_inventado(texto + " Quer ver?")
    assert trocou and novo == f"{FRASE_ESTADO} Quer ver?"


@pytest.mark.parametrize("texto", [
    "É um carro muito bem conservado.", "É um excelente carro.", "Está impecável!",
])
def test_elogio_sem_ficha_so_sai(texto):
    # M1 (L13): elogio ao carro só sai, sem frase no lugar.
    assert cortar_estado_inventado(texto + " Quer ver?") == ("Quer ver?", True)


@pytest.mark.parametrize("texto", [
    "Quer saber se ele é revisado?", "Não tenho a informação se é único dono.", "O Civic tem 48.000 km.",
])
def test_pergunta_negacao_e_fato_da_ficha_ficam(texto):
    assert cortar_estado_inventado(texto) == (texto, False)


def test_estado_que_esta_na_ficha_fica():
    assert cortar_estado_inventado("Ele é de único dono.", ficha="Honda Civic 2019, único dono, 48.000 km")[1] is False


# ------------------------------------------------------------ 5. agendamento

@pytest.mark.parametrize("texto", ["Agendei seu test-drive para sábado às 10h.", "Está agendado para sábado!",
                                   "Deixei marcado para amanhã."])
def test_agendamento_dito_sem_gravar_vira_pedido(texto):
    assert tirar_agendamento_falso(texto) == (FRASE_AGENDA, True)


def test_pergunta_de_agendamento_fica():
    assert tirar_agendamento_falso("Quer que eu agende para sábado?") == ("Quer que eu agende para sábado?", False)


# ------------------------------------------------------------ no turno

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
    for loja_id in (LOJA_A, LOJA_B):
        _sql("INSERT OR IGNORE INTO lojas (id, nome, segmento, config) VALUES (?, ?, 'veiculos', '{}')",
             (loja_id, f"Loja {loja_id}"))
    lojas.limpar_cache()


class Grafo:
    def __init__(self, resposta, tool=None, retorno=""):
        self.resposta, self.tool, self.retorno = resposta, tool, retorno

    def invoke(self, entrada, config=None):
        msgs = [HumanMessage(content=entrada["messages"][0].content)]
        if self.tool:
            msgs += [AIMessage(content="", tool_calls=[{"name": self.tool, "args": {}, "id": "t"}]),
                     ToolMessage(content=self.retorno, tool_call_id="t", name=self.tool)]
        return {"messages": msgs + [AIMessage(content=self.resposta)]}


def _turno(loja_id, lead, texto, grafo):
    from app.core.turno import executar_turno
    return asyncio.run(executar_turno(loja_id, "simulador", lead, texto, grafo=grafo))


def test_agenda_que_gravou_lembra_a_cnh_no_test_drive(duas_lojas):
    r = _turno(LOJA_A, "a1", "test-drive sábado 10h",
               Grafo("Agendei seu test-drive para sábado às 10h.", "agendar_visita",
                     "Agendamento confirmado: test-drive para Ana em 21/11 às 10:00. Confirme ao cliente."))
    assert r.texto == f"Agendei seu test-drive para sábado às 10h. {FRASE_CNH}"


def test_agendei_sem_a_ferramenta_vira_pedido_e_abre_chamado(duas_lojas):
    r = _turno(LOJA_A, "a2", "test-drive sábado 10h", Grafo("Agendei seu test-drive para sábado às 10h."))
    assert FRASE_AGENDA in r.texto and "Agendei" not in r.texto and r.handoff_aberto
    assert _ler("SELECT id FROM handoffs WHERE loja_id = 2") == []


def test_estado_inventado_no_turno_e_cortado(duas_lojas):
    r = _turno(LOJA_A, "e1", "o civic é bom?", Grafo("É um carro muito bem conservado. Quer marcar uma visita?",
                                                     "consultar_estoque", "Honda Civic 2019, 48.000 km"))
    assert r.texto == "Quer marcar uma visita?"          # M1: elogio só sai


def test_chamado_aberto_pelo_codigo_sempre_avisa_o_cliente(duas_lojas):
    r = _turno(LOJA_A, "c1", "sou autônomo e não tenho como comprovar renda, consigo financiar o Renegade?",
               Grafo("Sobre o financiamento, a aprovação é feita pelos bancos. Já tem um modelo em mente?"))
    assert r.handoff_aberto and r.texto.count(FRASE_CONTATO) == 1


def test_chamado_que_ja_avisa_nao_ganha_frase_repetida(duas_lojas):
    r = _turno(LOJA_A, "c2", "quero falar com uma pessoa", Grafo("Claro! O pessoal da equipe vai falar com você por aqui."))
    assert r.texto.count("falar com você por aqui") == 1


def test_sombra_guarda_as_fotos_com_a_sugestao(duas_lojas):
    import json
    from app.core.turno import executar_turno
    _sql("UPDATE lojas SET config = ? WHERE id = 1", (json.dumps({"modo_sombra": True}),))
    lojas.limpar_cache()

    class ComFotos:
        def invoke(self, entrada, config=None):
            return {"messages": [HumanMessage(content="x"),
                                 AIMessage(content="", tool_calls=[{"name": "enviar_fotos", "args": {}, "id": "f"}]),
                                 ToolMessage(content="Enviando 2 fotos.", tool_call_id="f", name="enviar_fotos",
                                             artifact={"tipo": "fotos", "urls": ["file:///f/civic_1.png"]}),
                                 AIMessage(content="Aqui estão as fotos do Civic!")]}

    asyncio.run(executar_turno(LOJA_A, "simulador", "s1", "me manda fotos do Civic", grafo=ComFotos()))
    [s] = _ler("SELECT sugestao FROM sombra_sugestoes")
    assert "Aqui estão as fotos do Civic!" in s["sugestao"]
    assert "[Fotos que o Léo mandaria: file:///f/civic_1.png]" in s["sugestao"]


def test_sombra_nao_diz_que_agendou(duas_lojas):
    import json
    from app.core.turno import executar_turno
    _sql("UPDATE lojas SET config = ? WHERE id = 1", (json.dumps({"modo_sombra": True}),))
    lojas.limpar_cache()
    asyncio.run(executar_turno(LOJA_A, "simulador", "s2", "test-drive sábado", grafo=Grafo("Agendei para sábado às 10h.")))
    [s] = _ler("SELECT sugestao FROM sombra_sugestoes")
    assert "Agendei" not in s["sugestao"] and FRASE_AGENDA in s["sugestao"]


# ------------------------------------------------------------ 6. memória do grafo

def test_memoria_tira_conversa_parada_e_o_excesso():
    from app.core.agent import MemoriaLimitada
    relogio = [0.0]
    memoria = MemoriaLimitada(relogio=lambda: relogio[0])
    memoria.MAX_CONVERSAS = 3
    apagadas = []
    memoria.delete_thread = lambda t: apagadas.append(t)
    for i in range(5):
        memoria._ultimo_uso[f"t{i}"] = float(i)
    assert memoria.podar() == 2 and sorted(apagadas) == ["t0", "t1"]
    relogio[0] = 25 * 3600.0
    assert memoria.podar() == 3 and sorted(apagadas) == ["t0", "t1", "t2", "t3", "t4"]


def test_grafo_usa_a_memoria_limitada():
    from app.core.agent import MemoriaLimitada, memoria
    assert isinstance(memoria, MemoriaLimitada)


# ------------------------------------------------------------ bancada

@pytest.fixture
def bancada(monkeypatch, tmp_path):
    from scripts import rodar_bancada as rb
    monkeypatch.setattr(rb, "_PASTA_TEMP", tmp_path / "bancada")
    (tmp_path / "bancada").mkdir()
    return rb


@pytest.mark.parametrize("pergunta,resposta", [
    ("qual o endereço da loja de vocês?", "Sobre o endereço, vou confirmar com o pessoal da equipe."),
    ("se eu der um sinal de mil reais vocês seguram o Renegade?",
     "Sobre essa questão da reserva com sinal, o pessoal da equipe vai te explicar como funciona."),
    ("vi um Onix igual por 60 mil na OLX, vocês cobrem?",
     "Sobre essa questão de valores, o pessoal da equipe vai falar com você."),
    # textos reais da rodada 1 do L12 (19/11) que davam AVISO falso
    ("quanto vocês pagam no meu?",
     "Como mencionei, a avaliação do seu carro para troca é feita presencialmente por um de nossos vendedores."),
    ("se eu der um sinal de mil reais vocês seguram o Renegade pra mim até sábado?",
     "Sobre a sua dúvida, o pessoal da equipe vai falar com você por aqui para explicar como funciona essa "
     "questão da reserva."),
])
def test_resposta_que_toca_no_assunto_nao_da_aviso(bancada, pergunta, resposta):
    assert bancada.toca_no_assunto(pergunta, resposta)


def test_resposta_que_nao_toca_no_assunto_da_aviso(bancada):
    assert not bancada.toca_no_assunto("qual o endereço da loja?", "O pessoal da equipe vai falar com você por aqui.")


def test_bancada_falha_acao_sem_ferramenta(bancada, monkeypatch):
    rb = bancada
    from app.core import turno
    monkeypatch.setattr(turno, "tirar_agendamento_falso", lambda r: (r, False))       # desliga a guarda
    monkeypatch.setattr(turno, "tirar_promessa_de_foto", lambda r: (r, False))
    rodada = asyncio.run(rb.rodar([rb.validar_roteiro({"nome": "x", "falas": ["test-drive sábado"]}, "t")],
                                  Grafo("Agendei seu test-drive para sábado. Aqui estão as fotos do Corolla."), teto=1.0))
    falhas = " | ".join(rodada.resultados[0].falhas)
    assert "agendou sem a agenda gravar" in falhas and "mandou foto sem foto sair" in falhas


def test_bancada_falha_estado_sem_ficha(bancada, monkeypatch):
    rb = bancada
    from app.core import turno
    monkeypatch.setattr(turno, "cortar_estado_inventado", lambda r, ficha="", **k: (r, False))   # desliga a guarda
    rodada = asyncio.run(rb.rodar([rb.validar_roteiro({"nome": "x", "falas": ["o civic é bom?"]}, "t")],
                                  Grafo("É um excelente carro."), teto=1.0))
    assert rodada.resultados[0].status == rb.FALHOU


def test_roteiro_52(bancada):
    roteiros = {r["nome"]: r for r in bancada.carregar_roteiros()}
    assert len(roteiros) == 52 and "nunca bateu" in roteiros["estado_do_carro"]["nao_contem"]

"""
Bloco S7 (offline, sem Gemini): promessa de contato sem chamado, registro sem
ferramenta, relógio fixo dos testes de API e horário vindo do cadastro.
"""
import copy
import os
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

PASTA_TESTES = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PASTA_TESTES)
sys.path.insert(0, os.path.dirname(PASTA_TESTES))

import test_comportamento_etapa2_api as e25  # noqa: E402
from avisos_texto import (CONTATO_SEM_CHAMADO, REGISTRO_SEM_FERRAMENTA,  # noqa: E402
                          promessas_de_contato)
from app.core import montagem  # noqa: E402
from app.lojas import PADROES  # noqa: E402

RAIZ = Path(PASTA_TESTES).parent


def _conversa(turnos, espera=None):
    c = e25.Conversa(loja_id=1, lead_id="x", falas=["oi"] * len(turnos))
    c.novas_por_turno = turnos
    c.espera_por_turno = espera or [False] * len(turnos)
    return c


def _chamada(nome, n="1"):
    return [AIMessage(content="", tool_calls=[{"name": nome, "args": {}, "id": n}]),
            ToolMessage(content="ok", tool_call_id=n, name=nome)]


def _rotulos(c):
    return " | ".join(m for _, m in e25.avisos_s7(c))


ANUNCIO = ["Vou chamar o pessoal da equipe para te ajudar.", "Já avisei o vendedor, tá?",
           "Vou passar seu pedido para a equipe."]
CONTATO = ["O pessoal da equipe vai falar com você por aqui.",
           "Um vendedor vai combinar o horário com você.",
           "Eles retomam no próximo horário de atendimento."]
REGISTRO = ["Vou registrar seu interesse.", "Anotei aqui seu pedido.", "Pronto, já está registrado."]
NADA = ["A loja funciona de segunda a sábado, das 9h às 18h.",
        "Não vou chamar ninguém agora, pode ficar tranquilo.",
        "Quer que eu chame alguém da equipe para você?",
        "Posso registrar seu interesse?",
        "O Onix está disponível, quer saber mais?"]


@pytest.mark.parametrize("frase", ANUNCIO)
def test_detecta_anuncio(frase):
    assert "anuncio" in promessas_de_contato(frase)


@pytest.mark.parametrize("frase", CONTATO)
def test_detecta_contato(frase):
    assert "contato" in promessas_de_contato(frase)


@pytest.mark.parametrize("frase", REGISTRO)
def test_detecta_registro(frase):
    assert "registro" in promessas_de_contato(frase)


@pytest.mark.parametrize("frase", NADA)
def test_nao_detecta(frase):
    assert promessas_de_contato(frase) == {}


# --- os três casos do analista, dos dois lados ---

def test_so_perguntou_horario_e_prometeu_contato():
    c = _conversa([[AIMessage(content="Abrimos de segunda a sábado, das 9h às 18h. "
                                      "O pessoal da equipe vai falar com você por aqui.")]])
    assert CONTATO_SEM_CHAMADO in _rotulos(c)


def test_so_perguntou_horario_e_respondeu_certo():
    c = _conversa([[AIMessage(content="Abrimos de segunda a sábado, das 9h às 18h. Quer passar aqui?")]])
    assert e25.avisos_s7(c) == []


def test_agendamento_desligado_disse_que_registrou_sem_ferramenta():
    c = _conversa([[AIMessage(content="Vou registrar seu interesse em visitar a loja.")]])
    assert REGISTRO_SEM_FERRAMENTA in _rotulos(c)


def test_agendamento_desligado_com_registrar_lead_nao_avisa():
    c = _conversa([_chamada("registrar_lead") + [AIMessage(
        content="Anotei seu interesse. A loja abre de segunda a sábado, das 9h às 18h.")]])
    assert e25.avisos_s7(c) == []


def test_vendedor_ja_chamado_problema_novo_sem_handoff():
    c = _conversa([[AIMessage(content="Entendi. Vou chamar o pessoal da equipe para ver isso.")]],
                  espera=[True])
    assert CONTATO_SEM_CHAMADO in _rotulos(c)


def test_vendedor_ja_chamado_problema_novo_com_handoff():
    c = _conversa([_chamada("acionar_handoff") + [AIMessage(
        content="Entendi. Vou chamar o pessoal da equipe para ver isso.")]], espera=[True])
    assert e25.avisos_s7(c) == []


def test_em_espera_dizer_que_o_pessoal_vai_falar_nao_avisa():
    c = _conversa([[AIMessage(content="O pessoal da equipe vai falar com você por aqui.")]],
                  espera=[True])
    assert e25.avisos_s7(c) == []


def test_chamado_aberto_no_turno_libera_a_promessa():
    c = _conversa([_chamada("acionar_handoff") + [AIMessage(
        content="O pessoal da equipe vai falar com você por aqui.")]])
    assert e25.avisos_s7(c) == []


def test_promessa_conta_por_turno():
    c = _conversa([[AIMessage(content="O pessoal da equipe vai falar com você por aqui.")],
                   _chamada("acionar_handoff") + [AIMessage(content="Pronto.")]])
    assert CONTATO_SEM_CHAMADO in _rotulos(c)


# --- relógio fixo ---

def test_dia_util_recente():
    assert e25.dia_util_recente(date(2026, 11, 11)) == date(2026, 11, 11)   # quarta
    assert e25.dia_util_recente(date(2026, 11, 14)) == date(2026, 11, 13)   # sábado -> sexta
    assert e25.dia_util_recente(date(2026, 11, 15)) == date(2026, 11, 13)   # domingo -> sexta


def test_cenarios_ficam_dentro_e_fora_do_cadastro_padrao():
    inicio, fim = PADROES["atendimento"]["horario_humano"].split("-")
    h, m = e25.CENARIOS_RELOGIO["dentro"]
    assert inicio <= f"{h:02d}:{m:02d}" < fim
    h, m = e25.CENARIOS_RELOGIO["fora"]
    assert not (inicio <= f"{h:02d}:{m:02d}" < fim)


def test_resumo_por_cenario_conta_prazo_e_contato():
    salvo = list(e25.RODADA.casos)
    try:
        e25.RODADA.casos[:] = [
            {"nome": "a", "cenario": "dentro", "status": e25.PASSOU, "feitas": 3, "ok": 3,
             "custo": 0.0, "motivos": [(f"AVISO: {CONTATO_SEM_CHAMADO} (x)", 2)], "tentativas": []},
            {"nome": "b", "cenario": "fora", "status": e25.PASSOU, "feitas": 3, "ok": 3,
             "custo": 0.0, "motivos": [(f'AVISO: {e25.PRAZO}: "ja ja"', 1)], "tentativas": []},
        ]
        texto = "\n".join(e25.resumo_por_cenario())
    finally:
        e25.RODADA.casos[:] = salvo
    assert "dentro: 1 caso(s), 3 tentativas · prazo: 0 · contato sem chamado: 2" in texto
    assert "fora: 1 caso(s), 3 tentativas · prazo: 1 · contato sem chamado: 0" in texto


# --- prompt e horário do cadastro ---

def _loja(**mudancas):
    config = copy.deepcopy(PADROES)
    for chave, valor in mudancas.items():
        secao, nome = chave.split("__")
        config[secao][nome] = valor
    return SimpleNamespace(id=1, nome="Loja Teste", segmento="veiculos", config=config)


def _prompt(loja):
    return montagem.montar_prompt(loja, montagem.ferramentas_da_loja(loja),
                                  datetime(2026, 11, 11, 10, 30))


def test_prompt_tem_regra_de_promessa_de_contato():
    p = _prompt(_loja())
    assert "PROMESSA DE CONTATO" in p
    assert "JÁ chamou acionar_handoff" in p


def test_prompt_manda_usar_horario_do_cadastro():
    p = _prompt(_loja())
    assert "das 09:00 às 18:00" in p
    assert "Não busque horário em documento" in p


def test_excecao_de_fora_do_horario_so_com_colega_chamado():
    base = (RAIZ / "prompts" / "base.md").read_text(encoding="utf-8")
    assert "Se ninguém foi chamado, não fale em retorno" in base
    assert "Única exceção: fora do horário da loja, diga" not in base


def test_agendamento_desligado_nao_promete_vendedor():
    aviso = montagem.AVISOS_MODULO_DESLIGADO["agendamento"]
    assert "registrar_lead" in aviso
    assert "vendedor vai combinar" not in aviso
    assert aviso in _prompt(_loja(modulos__agendamento=False))


def test_buscar_conhecimento_nao_e_para_horario():
    from tools.buscar_conhecimento import buscar_conhecimento
    assert "cadastro" in montagem.DESCRICOES["buscar_conhecimento"]
    assert "cadastro" in buscar_conhecimento.description


def test_documento_de_teste_bate_com_o_cadastro():
    doc = (RAIZ / "conhecimento" / "troca_garantia_horario.txt").read_text(encoding="utf-8")
    assert montagem.descrever_dias(PADROES["atendimento"]["dias_humano"]) == "de segunda a sábado"
    assert PADROES["atendimento"]["horario_humano"] == "09:00-18:00"
    assert "de segunda a sábado, das 9h às 18h" in doc
    assert "13h" not in doc and "8h às" not in doc
    assert "vendedor retorna" not in doc

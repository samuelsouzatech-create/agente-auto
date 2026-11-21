"""
Maratona 3, N5b (itens 7 a 11), só offline: política negada sem base, dia/hora de reabertura,
fragmentos depois de cortes, descrição da foto sem estado, chamado de entrega só com carro/cidade.
LLM falso, relógio fixo, duas lojas.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from app.guarda_politica import (FRASE_PAGAMENTO_EXPLICA, corrigir_reabertura, tirar_elogio_da_descricao,
                                 tirar_fragmentos, trocar_politica_sem_base)

SABADO_0018 = datetime(2026, 11, 21, 3, 18, tzinfo=timezone.utc)     # sábado 00:18 em Recife (abre 08:00)
DOMINGO_1500 = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)    # domingo 15:00 em Recife (abre seg 08:00)
QUARTA_1000 = datetime(2026, 11, 18, 13, 0, tzinfo=timezone.utc)     # quarta 10:00 (aberta)
HORARIO = {"0": "08:00-18:00", "1": "08:00-18:00", "2": "08:00-18:00", "3": "08:00-18:00",
           "4": "08:00-18:00", "5": "08:00-13:00"}


def _loja_com_horario(loja_id=1):
    conexao = banco.conectar()
    try:
        conexao.execute("INSERT OR IGNORE INTO lojas (id, nome, segmento, config) VALUES (2, 'Loja B', 'veiculos', '{}')")
        conexao.execute("UPDATE lojas SET config = ? WHERE id = ?",
                        (json.dumps({"atendimento": {"horario_semana": HORARIO}}), loja_id))
        conexao.commit()
    finally:
        conexao.close()
    from app import lojas
    lojas.limpar_cache()
    return lojas.carregar_loja(loja_id)


# ------------------------------------------------------------ 7. política negada sem base

FRASE_REAL = ("Sobre a reserva, a gente não trabalha com pagamento antecipado por PIX para reservar veículos. "
              "O pessoal da equipe pode te explicar melhor como funciona o processo de compra e reserva aqui na loja.")


@pytest.mark.parametrize("frase", [
    "A gente não trabalha com pagamento antecipado por PIX.",
    "A loja não trabalha com reserva por PIX.",
    "A gente não faz reserva com sinal.",
    "Nós não fazemos reserva por PIX.",
    "A loja não aceita sinal para reservar.",
    "Não aceitamos PIX antecipado.",
    "A loja não prevê reserva com pagamento antecipado.",
    "Nossa política não permite reserva por PIX.",
])
def test_negacao_de_politica_de_pagamento_vira_resposta_padrao(frase):
    novo, temas = trocar_politica_sem_base(frase)
    assert temas == ["pagamento"] and novo == FRASE_PAGAMENTO_EXPLICA


def test_frase_real_do_roteiro_37():
    novo, temas = trocar_politica_sem_base(FRASE_REAL)
    assert temas == ["pagamento"] and "a gente não" not in novo.lower()
    assert novo.startswith(FRASE_PAGAMENTO_EXPLICA)


def test_frase_sem_politica_fica():
    for frase in ("Temos o Civic por R$ 98.000,00.", "A gente tem o Civic 2019 branco."):
        assert trocar_politica_sem_base(frase) == (frase, [])


def test_roteiros_37_e_41_reprovam_as_variacoes():
    from scripts import rodar_bancada as rb
    roteiros = {r["nome"]: r for r in rb.carregar_roteiros()}
    for nome in ("pede_pix_reserva", "sinal_reserva"):
        for termo in ("a gente não", "não trabalha", "não faz", "não aceita", "não prevê", "nossa política não"):
            assert termo in roteiros[nome]["nao_contem"], (nome, termo)


# ------------------------------------------------------------ 8. dia/hora de reabertura

def test_reabertura_calculada_no_sabado_madrugada_e_no_domingo():
    from app.relogio import reabertura
    loja = _loja_com_horario()
    assert reabertura(loja, SABADO_0018) == {"quando": "hoje, às 08:00", "dia": 5, "hora": "08:00", "relativo": "hoje"}
    assert reabertura(loja, DOMINGO_1500) == {"quando": "amanhã, segunda-feira, às 08:00", "dia": 0, "hora": "08:00",
                                               "relativo": "amanha"}
    assert reabertura(loja, QUARTA_1000) is None                     # aberta: nada a conferir


@pytest.mark.parametrize("quando, errada", [
    (SABADO_0018, "A loja está fechada agora, mas abre amanhã, sábado, às 08:00."),
    (SABADO_0018, "Abrimos às 9h."),
    (SABADO_0018, "A loja retoma o atendimento na segunda, a partir das 08:00."),
    (DOMINGO_1500, "Abrimos hoje às 8h."),
    (DOMINGO_1500, "A loja abre amanhã, sábado, às 08:00."),
    (DOMINGO_1500, "Voltamos a atender na terça, às 08:00."),
])
def test_reabertura_errada_vira_frase_do_codigo(quando, errada):
    from app.relogio import reabertura
    abre = reabertura(_loja_com_horario(), quando)
    novo, trocou = corrigir_reabertura(f"Temos o Civic. {errada}", abre)
    assert trocou and novo == f"Temos o Civic. A loja está fechada agora; abre {abre['quando']}."


@pytest.mark.parametrize("quando, certa", [
    (SABADO_0018, "A loja abre hoje, às 08:00."),
    (SABADO_0018, "Abrimos hoje às 8h."),
    (DOMINGO_1500, "A loja abre amanhã, segunda-feira, às 08:00."),
    (DOMINGO_1500, "Nosso horário é de segunda a sexta, das 08:00 às 18:00, e sábado das 08:00 às 13:00."),
])
def test_reabertura_certa_ou_lista_de_horario_fica(quando, certa):
    from app.relogio import reabertura
    assert corrigir_reabertura(certa, reabertura(_loja_com_horario(), quando)) == (certa, False)


class Grafo:
    def __init__(self, resposta):
        self.resposta = resposta

    def invoke(self, entrada, config=None):
        return {"messages": [HumanMessage(content=entrada["messages"][0].content), AIMessage(content=self.resposta)]}


def test_turno_no_domingo_corrige_a_reabertura(monkeypatch):
    from app import relogio
    from app.core.turno import executar_turno
    _loja_com_horario(1)
    monkeypatch.setattr(relogio, "agora_utc", lambda: DOMINGO_1500)
    r = asyncio.run(executar_turno(1, "simulador", "c-dom", "vocês abrem quando?",
                                   grafo=Grafo("Abrimos hoje às 8h. Quer agendar uma visita?")))
    assert "abre amanhã, segunda-feira, às 08:00" in r.texto and "hoje às 8h" not in r.texto


# ------------------------------------------------------------ 9. fragmentos e "só um instante"

def test_fragmento_de_endereco_solto_sai_e_carro_fica():
    novo, mudou = tirar_fragmentos("O Civic fica na nossa loja. Domingos Ferreira, 1000, Boa Viagem. Quer agendar?",
                                   "onde fica?")
    assert mudou and novo == "O Civic fica na nossa loja. Quer agendar?"
    assert tirar_fragmentos("Honda Civic 2019, branco.", "tem civic?") == ("Honda Civic 2019, branco.", False)
    assert tirar_fragmentos("Sobre o IPVA.", "e o IPVA?") == ("Sobre o IPVA.", False)       # assunto fica
    assert tirar_fragmentos("Perfeito! Temos sim.", "tem civic?") == ("Perfeito! Temos sim.", False)


def test_loja_fechada_nunca_so_um_instante():
    novo, mudou = tirar_fragmentos("Só um instante que já te aviso. O Civic 2019 está disponível.", "tem civic?",
                                   loja_fechada=True)
    assert mudou and novo == "O Civic 2019 está disponível."
    assert tirar_fragmentos("Já te aviso por aqui.", "x", loja_fechada=False)[1] is False


def test_turno_fechado_tira_so_um_instante(monkeypatch):
    from app import relogio
    from app.core.turno import executar_turno
    _loja_com_horario(1)
    monkeypatch.setattr(relogio, "agora_utc", lambda: DOMINGO_1500)
    r = asyncio.run(executar_turno(1, "simulador", "c-inst", "tem civic?",
                                   grafo=Grafo("Só um instante que já te aviso. Temos o Civic, quer ver fotos?")))
    assert "instante" not in r.texto.lower() and "Temos o Civic" in r.texto


# ------------------------------------------------------------ 10. descrição da foto

@pytest.mark.parametrize("bruta, limpa", [
    ("Gol prata em boas condições, com um risco na porta", "Gol prata, com um risco na porta"),
    ("Civic preto brilhante, bem cuidado", "Civic preto"),
    ("Onix vermelho conservado", "Onix vermelho"),
    ("HB20 branco em ótimo estado, pneu gasto", "HB20 branco, pneu gasto"),
])
def test_descricao_sem_palavras_de_estado(bruta, limpa):
    assert tirar_elogio_da_descricao(bruta) == limpa


def test_leitura_da_foto_sem_modelo_diz_que_nao_identificou():
    from app.imagens import interpretar
    sem_modelo = interpretar('{"tipo": "carro", "descricao": "carro prata em ótimo estado, pneu gasto", "tem_pessoa": false}')
    assert sem_modelo.descricao == "modelo não identificado, carro prata, pneu gasto"
    com_modelo = interpretar('{"tipo": "carro", "descricao": "Onix vermelho conservado", "tem_pessoa": false}')
    assert com_modelo.descricao == "Onix vermelho"
    anuncio = interpretar('{"tipo": "anuncio", "descricao": "Civic 2019", "tem_pessoa": false}')
    assert anuncio.descricao == "Civic 2019"                         # só foto de carro do cliente muda


def test_prompt_da_visao_nao_mudou():
    from pathlib import Path
    fonte = (Path(__file__).resolve().parents[1] / "app" / "imagens.py").read_text(encoding="utf-8")
    assert "descricao: modelo aparente, cor e estado visível (riscos, amassados, pneus). Não estime valor." in fonte


# ------------------------------------------------------------ 11. chamado de entrega

@pytest.mark.parametrize("fala, abre", [
    ("quero entregar o melhor serviço pra minha família", False),
    ("vou entregar os documentos amanhã", False),
    ("vocês entregam o carro em Caruaru?", True),
    ("entregam em Caruaru?", True),
    ("faz entrega do veículo?", True),
    ("dá pra levar o carro até Olinda?", True),
])
def test_entrega_so_com_carro_ou_cidade(fala, abre):
    from app.core.turno import motivo_do_chamado_pelo_codigo
    motivo = motivo_do_chamado_pelo_codigo(fala, "Ok.", "sim")
    assert (motivo is not None and motivo[0] == "Cliente pediu entrega do carro.") is abre


# ------------------------------------------------------------ N5c: com a loja fechada, nada bom some

@pytest.mark.parametrize("resposta", [
    "Temos o Civic 2019!\n\n- Automático\n- 48 mil km",
    "Legal! Me conta o ano e a quilometragem.",
    "Parabéns pela compra, Carla! Fico à disposição.",
    "Boa pergunta! O Civic 2019 está disponível.",
])
def test_loja_fechada_mantem_lista_e_frases_do_modelo(monkeypatch, resposta):
    from app import relogio
    from app.core.turno import executar_turno
    _loja_com_horario(1)
    monkeypatch.setattr(relogio, "agora_utc", lambda: DOMINGO_1500)          # loja FECHADA
    r = asyncio.run(executar_turno(1, "simulador", "c-fech", "oi", grafo=Grafo(resposta)))
    assert r.texto == resposta


def test_so_sai_o_pedaco_que_sobrou_de_um_corte():
    modelo = "Ficamos na Domingos Ferreira, 1000, Boa Viagem. Legal!"
    depois_do_corte = "Domingos Ferreira, 1000, Boa Viagem. Legal!"       # uma guarda cortou o começo
    assert tirar_fragmentos(depois_do_corte, "oi", original=modelo) == ("Legal!", True)
    assert tirar_fragmentos("Legal! Fico à disposição.", "oi", loja_fechada=True,
                            original="Legal! Fico à disposição.") == ("Legal! Fico à disposição.", False)

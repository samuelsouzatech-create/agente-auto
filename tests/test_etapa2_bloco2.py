"""
Testes da Etapa 2, Bloco 2: quem a loja pode procurar agora. Offline, duas lojas.

Relógio fixo (terça, 12h em Recife). Provam: 23 h não dispara e 25 h dispara;
o 4º contato nunca sai; carro vendido, pedido de não-contato e conversa com
vendedor barram; horário e limite mensal; isolamento entre lojas.
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from app.chaves import LojaNaoInformada
from app.elegibilidade import avaliar, candidatos, elegiveis, vagas_no_mes
from app.interesse import registrar_situacao
from app.lojas import criar_loja, salvar_config
from app.relogio import para_banco

AGORA = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)      # terça, 12h em Recife
AMANHA_9H = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)  # quarta, 9h em Recife
LEAD = "5581999990000"
LIGADO = {"modulos.remarketing": True, "remarketing.limite_mensal": 100}


# ---------------------------------------------------------------- apoio

def _executar(sql, parametros=()):
    con = banco.conectar()
    try:
        con.execute(sql, parametros)
        con.commit()
    finally:
        con.close()


def _msg(loja_id, lead_id, direcao, horas_atras, canal="whatsapp"):
    _executar("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
              "VALUES (?, ?, ?, ?, 'x', ?)",
              (lead_id, loja_id, canal, direcao, para_banco(AGORA - timedelta(hours=horas_atras))))


def _conversa(loja_id=1, lead_id=LEAD, horas=49, canal="whatsapp"):
    _msg(loja_id, lead_id, "cliente", horas, canal)
    _msg(loja_id, lead_id, "leo", horas, canal)


def _toque(loja_id, lead_id, toque, horas_atras, estado="enviado", canal="whatsapp"):
    quando = para_banco(AGORA - timedelta(hours=horas_atras))
    _executar("INSERT INTO remarketing_envios (loja_id, lead_id, canal, toque, estado, "
              "enviado_em, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (loja_id, lead_id, canal, toque, estado,
               quando if estado == "enviado" else None, quando))


@pytest.fixture
def ligada():
    salvar_config(1, LIGADO, "teste")
    return 1


@pytest.fixture
def loja_b():
    b = criar_loja("Loja B")
    salvar_config(b, LIGADO, "teste")
    return b


def _motivo(loja_id=1, lead_id=LEAD, canal="whatsapp", agora=AGORA):
    return avaliar(loja_id, lead_id, canal, agora).motivo


# ---------------------------------------------------------------- tempo do 1º toque

def test_lead_parado_48h_recebe_o_primeiro_toque(ligada):
    _conversa(horas=49)
    d = avaliar(1, LEAD, "whatsapp", AGORA)
    assert d.elegivel and d.motivo == "elegivel" and d.toque == 1


def test_antes_de_48h_espera_e_diz_quando(ligada):
    _conversa(horas=47)
    d = avaliar(1, LEAD, "whatsapp", AGORA)
    assert d.motivo == "aguardando_intervalo" and d.proximo_em == AGORA + timedelta(hours=1)


@pytest.mark.parametrize("horas, esperado", [(23, False), (25, True)])
def test_23h_nao_dispara_25h_dispara(ligada, horas, esperado):
    salvar_config(1, {"remarketing.primeiro_toque_h": 24}, "teste")
    _conversa(horas=horas)
    assert avaliar(1, LEAD, "whatsapp", AGORA).elegivel is esperado


def test_conversa_recente_do_leo_adia_e_cai_na_abertura(ligada):
    _msg(1, LEAD, "cliente", 60)
    _msg(1, LEAD, "leo", 30)            # alvo: amanhã 6h em Recife, antes de abrir
    d = avaliar(1, LEAD, "whatsapp", AGORA)
    assert d.motivo == "aguardando_intervalo" and d.proximo_em == AMANHA_9H


def test_nunca_conversou_nao_entra(ligada):
    _msg(1, LEAD, "leo", 100)
    assert _motivo() == "sem_conversa"


# ---------------------------------------------------------------- toques seguintes e teto

def test_segundo_toque_depois_de_5_dias(ligada):
    _msg(1, LEAD, "cliente", 300)
    _toque(1, LEAD, 1, 121)
    d = avaliar(1, LEAD, "whatsapp", AGORA)
    assert d.elegivel and d.toque == 2


def test_segundo_toque_antes_do_intervalo_espera(ligada):
    _msg(1, LEAD, "cliente", 300)
    _toque(1, LEAD, 1, 100)
    d = avaliar(1, LEAD, "whatsapp", AGORA)
    assert d.motivo == "aguardando_intervalo" and d.toque == 2 and d.proximo_em == AMANHA_9H


def test_o_quarto_contato_nunca_sai(ligada):
    _msg(1, LEAD, "cliente", 1000)
    for n, horas in ((1, 900), (2, 700), (3, 400)):
        _toque(1, LEAD, n, horas)
    assert _motivo() == "teto_atingido"


def test_teto_da_loja_menor_que_o_do_produto(ligada):
    salvar_config(1, {"remarketing.max_toques": 1}, "teste")
    _msg(1, LEAD, "cliente", 1000)
    _toque(1, LEAD, 1, 500)
    assert _motivo() == "teto_atingido"


def test_toque_que_falhou_nao_gasta_o_teto(ligada):
    _conversa(horas=49)
    _toque(1, LEAD, 1, 10, estado="falhou")
    d = avaliar(1, LEAD, "whatsapp", AGORA)
    assert d.elegivel and d.toque == 1


def test_respondeu_depois_do_toque_para(ligada):
    _msg(1, LEAD, "cliente", 100)
    _toque(1, LEAD, 1, 60)
    _msg(1, LEAD, "cliente", 50)
    assert _motivo() == "respondeu"


# ---------------------------------------------------------------- barreiras do lead

@pytest.mark.parametrize("estado, motivo", [
    ("aguardando_humano", "com_vendedor"),
    ("humano_assumiu", "com_vendedor"),
    ("encerrado", "elegivel"),
])
def test_conversa_com_vendedor_barra(ligada, estado, motivo):
    _conversa(horas=49)
    _executar("INSERT INTO handoffs (loja_id, lead_id, estado) VALUES (1, ?, ?)", (LEAD, estado))
    assert _motivo() == motivo


def test_quem_comprou_nao_recebe_remarketing(ligada):
    _conversa(horas=49)
    _executar("INSERT INTO resultados (lead_id, loja_id, resultado) VALUES (?, 1, 'comprou')", (LEAD,))
    assert _motivo() == "ja_comprou"


def test_venda_registrada_tambem_barra(ligada):
    _conversa(horas=49)
    _executar("INSERT INTO vendas (loja_id, lead_id, veiculo_id, data_venda, forma_pagamento) "
              "VALUES (1, ?, 3, '2026-10-30', 'avista')", (LEAD,))
    assert _motivo() == "ja_comprou"


@pytest.mark.parametrize("situacao", ["nao_contatar", "sem_interesse"])
def test_pedido_do_cliente_barra(ligada, situacao):
    _conversa(horas=49)
    registrar_situacao(1, LEAD, situacao, motivo="teste")
    assert _motivo() == situacao


def test_pediu_tempo_diz_quando_volta(ligada):
    _conversa(horas=49)
    registrar_situacao(1, LEAD, "pediu_tempo", dias=10, hoje=date(2026, 11, 1))
    d = avaliar(1, LEAD, "whatsapp", AGORA)
    assert d.motivo == "pediu_tempo"
    assert d.proximo_em == datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def test_tempo_pedido_ja_passou_libera(ligada):
    _conversa(horas=49)
    registrar_situacao(1, LEAD, "pediu_tempo", dias=1, hoje=date(2026, 11, 1))
    assert _motivo() == "elegivel"


def test_pedido_numa_loja_nao_vale_para_a_outra(ligada, loja_b):
    _conversa(loja_id=1)
    _conversa(loja_id=loja_b)
    registrar_situacao(1, LEAD, "nao_contatar", motivo="teste")
    assert _motivo(loja_id=1) == "nao_contatar"
    assert _motivo(loja_id=loja_b) == "elegivel"


# ---------------------------------------------------------------- horário e limite

def test_de_noite_espera_a_abertura(ligada):
    _conversa(horas=49)
    noite = datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc)      # terça, 22h em Recife
    d = avaliar(1, LEAD, "whatsapp", noite)
    assert d.motivo == "fora_do_horario" and d.proximo_em == AMANHA_9H


def test_domingo_pula_para_segunda(ligada):
    _conversa(horas=49)
    domingo = datetime(2026, 11, 8, 15, 0, tzinfo=timezone.utc)
    d = avaliar(1, LEAD, "whatsapp", domingo)
    assert d.motivo == "fora_do_horario"
    assert d.proximo_em == datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def test_limite_do_mes_atingido(ligada):
    salvar_config(1, {"remarketing.limite_mensal": 1}, "teste")
    _toque(1, "outro", 1, 1)
    _conversa(horas=49)
    d = avaliar(1, LEAD, "whatsapp", AGORA)
    assert d.motivo == "limite_mensal"
    assert d.proximo_em == datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)


def test_simulado_nao_gasta_o_limite(ligada):
    salvar_config(1, {"remarketing.limite_mensal": 1}, "teste")
    _toque(1, "outro", 1, 1, estado="simulado")
    _conversa(horas=49)
    assert _motivo() == "elegivel"


def test_envio_do_mes_passado_nao_conta(ligada):
    salvar_config(1, {"remarketing.limite_mensal": 1}, "teste")
    _toque(1, "outro", 1, 340)          # outubro
    assert vagas_no_mes(1, AGORA) == 1


# ---------------------------------------------------------------- barreiras da loja

def test_modulo_desligado_por_padrao():
    c = criar_loja("Loja C")
    _conversa(loja_id=c)
    assert _motivo(loja_id=c) == "modulo_desligado"


def test_sem_limite_do_contrato_nada_sai():
    salvar_config(1, {"modulos.remarketing": True}, "teste")
    _conversa(horas=49)
    assert _motivo() == "limite_nao_definido"


def test_loja_desativada(ligada):
    _conversa(horas=49)
    _executar("UPDATE lojas SET ativo = 0 WHERE id = 1")
    assert _motivo() == "loja_inativa"


@pytest.mark.parametrize("canal", ["instagram", "simulador"])
def test_canal_sem_envio_proativo(ligada, canal):
    _conversa(horas=49, canal=canal)
    assert _motivo(canal=canal) == "canal_sem_envio"


def test_sem_loja_e_recusado():
    with pytest.raises(LojaNaoInformada):
        avaliar(None, LEAD, "whatsapp", AGORA)


# ---------------------------------------------------------------- listas e janela

def test_elegiveis_respeita_vagas_e_ordem(ligada):
    salvar_config(1, {"remarketing.limite_mensal": 1}, "teste")
    _conversa(lead_id="A", horas=100)
    _conversa(lead_id="B", horas=60)
    _conversa(lead_id="C", horas=70)
    registrar_situacao(1, "C", "nao_contatar", motivo="teste")
    todos = {d.lead_id: d.motivo for d in candidatos(1, AGORA)}
    assert todos == {"A": "elegivel", "B": "elegivel", "C": "nao_contatar"}
    assert [d.lead_id for d in elegiveis(1, AGORA)] == ["A"]


def test_decisao_informa_a_janela(ligada):
    _conversa(lead_id="tg", horas=49, canal="telegram")
    _conversa(lead_id="wa", horas=49)
    assert avaliar(1, "tg", "telegram", AGORA).janela_aberta is True
    assert avaliar(1, "wa", "whatsapp", AGORA).janela_aberta is False

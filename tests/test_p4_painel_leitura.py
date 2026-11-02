"""
P4 do Plano Mestre: funções de leitura dos painéis (app/painel_leitura.py).
- Uma regra por etapa e um teste por conflito (a etapa mais avançada vence).
- Resultado do período: horário da loja, virada do mês, venda com atraso, duas lojas.
- Mesmo número de vendas em Leads e Resultado.
- Nada é gravado no banco.
Tudo offline: banco temporário (conftest), sem IA.
"""
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from banco import conectar
from app.chaves import LojaNaoInformada
from app.interesse import registrar_situacao
from app.lojas import criar_loja
from app.painel_leitura import (
    ORDEM_DAS_ETAPAS, ROTULOS_ETAPA, _ler, cartao_do_lead, etapas_dos_leads,
    resultado_do_periodo,
)
from app.relogio import para_banco
from app.vendas import registrar_venda

AGORA = datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc)   # terça, 10:00 em Recife
HOJE = date(2026, 11, 3)
LEAD = "5581999990000"


def _antes(**delta):
    return para_banco(AGORA - timedelta(**delta))


def _sql(comando, valores=()):
    conexao = conectar()
    try:
        cursor = conexao.execute(comando, valores)
        conexao.commit()
        return cursor.lastrowid
    finally:
        conexao.close()


def _msg(loja_id, lead_id, direcao, quando, canal="whatsapp"):
    _sql("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
         "VALUES (?, ?, ?, ?, 'oi', ?)", (lead_id, loja_id, canal, direcao, quando))


def _carro(loja_id, modelo="HB20", ano=2020):
    return _sql("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco) "
                "VALUES (?, 'Hyundai', ?, ?, 40000, 'Prata', 'Manual', 60000)",
                (loja_id, modelo, ano))


def _vender(loja_id, lead_id, dia=HOJE):
    return registrar_venda(loja_id, lead_id, _carro(loja_id), dia, "avista", agora=AGORA)


def _handoff(loja_id, lead_id, criado, assumido=None, estado="aguardando_humano", origem="leo"):
    _sql("INSERT INTO handoffs (loja_id, lead_id, motivo, estado, criado_em, assumido_em, origem) "
         "VALUES (?, ?, 'Quer negociar', ?, ?, ?, ?)",
         (loja_id, lead_id, estado, criado, assumido, origem))


def _visita(loja_id, lead_id, criado):
    _sql("INSERT INTO agendamentos (loja_id, lead_id, nome_cliente, tipo, data_hora, criado_em) "
         "VALUES (?, ?, 'Juliana', 'visita', 'sábado 10h', ?)", (loja_id, lead_id, criado))


def _toques(loja_id, lead_id, quantos, ultimo):
    for toque in range(1, quantos + 1):
        _sql("INSERT INTO remarketing_envios (loja_id, lead_id, canal, toque, estado, enviado_em) "
             "VALUES (?, ?, 'whatsapp', ?, 'enviado', ?)", (loja_id, lead_id, toque, ultimo))


def _situacao(loja_id, lead_id, situacao):
    registrar_situacao(loja_id, lead_id, situacao, canal="whatsapp", dias=30, hoje=HOJE)


def _lead(loja_id, lead_id, **campos):
    colunas = ["lead_id", "loja_id", *campos]
    marcas = ",".join("?" * len(colunas))
    _sql(f"INSERT INTO leads ({', '.join(colunas)}) VALUES ({marcas})",
         (lead_id, loja_id, *campos.values()))


def _conversa(tipo, loja_id=1, lead_id=LEAD):
    if tipo == "novo":
        _msg(loja_id, lead_id, "cliente", _antes(hours=2))
    elif tipo == "conversa":
        _msg(loja_id, lead_id, "cliente", _antes(days=3))
        _msg(loja_id, lead_id, "cliente", _antes(days=1))
    else:  # sumiu
        _msg(loja_id, lead_id, "cliente", _antes(days=30))
        _msg(loja_id, lead_id, "cliente", _antes(days=20))


FATOS = {
    "venda": lambda: _vender(1, LEAD),
    "sem_interesse": lambda: _situacao(1, LEAD, "sem_interesse"),
    "visita": lambda: _visita(1, LEAD, _antes(days=2)),
    "vendedor": lambda: _handoff(1, LEAD, _antes(hours=1)),
    "pediu_tempo": lambda: _situacao(1, LEAD, "pediu_tempo"),
}


def _montar(conversa, fatos):
    _conversa(conversa)
    for nome in fatos:
        FATOS[nome]()


def _linha(loja_id=1, lead_id=LEAD, desde=90):
    return {l["lead_id"]: l for l in etapas_dos_leads(loja_id, desde, agora=AGORA)}[lead_id]


# ---------------------------------------------------------------- etapas
@pytest.mark.parametrize("conversa, fatos, esperado", [
    ("novo", [], "novo"),                    # Novo vence Em conversa
    ("conversa", [], "em_conversa"),
    ("sumiu", [], "nao_seguiu"),             # mais de 7 dias sem escrever
    ("conversa", ["pediu_tempo"], "pediu_tempo"),
    ("conversa", ["vendedor"], "com_vendedor"),
    ("conversa", ["visita"], "visita_marcada"),
    ("conversa", ["sem_interesse"], "nao_seguiu"),
    ("conversa", ["venda"], "venda_registrada"),
])
def test_uma_regra_por_etapa(conversa, fatos, esperado):
    _montar(conversa, fatos)
    assert _linha()["etapa"] == esperado


@pytest.mark.parametrize("conversa, fatos, esperado", [
    ("conversa", ["venda", "sem_interesse"], "venda_registrada"),
    ("conversa", ["venda", "visita"], "venda_registrada"),
    ("conversa", ["venda", "vendedor"], "venda_registrada"),
    ("conversa", ["sem_interesse", "visita"], "nao_seguiu"),
    ("conversa", ["sem_interesse", "vendedor"], "nao_seguiu"),
    ("conversa", ["visita", "vendedor"], "visita_marcada"),
    ("conversa", ["visita", "pediu_tempo"], "visita_marcada"),
    ("conversa", ["vendedor", "pediu_tempo"], "com_vendedor"),
    ("novo", ["pediu_tempo"], "pediu_tempo"),
    ("novo", ["vendedor"], "com_vendedor"),
    ("sumiu", ["pediu_tempo"], "pediu_tempo"),
    ("sumiu", ["vendedor"], "com_vendedor"),
    ("sumiu", ["visita"], "visita_marcada"),
])
def test_conflito_a_etapa_mais_avancada_vence(conversa, fatos, esperado):
    _montar(conversa, fatos)
    assert _linha()["etapa"] == esperado


def test_visita_marcada_vale_7_dias():
    _conversa("conversa")
    _visita(1, LEAD, _antes(days=8))
    assert _linha()["etapa"] == "em_conversa"


def test_nao_quer_contato_vai_para_nao_seguiu():
    _conversa("conversa")
    _situacao(1, LEAD, "nao_contatar")
    assert _linha()["etapa"] == "nao_seguiu"


def test_retomadas_acabaram_sem_resposta():
    _msg(1, LEAD, "cliente", _antes(days=6))
    _toques(1, LEAD, 3, _antes(days=1))
    linha = _linha()
    assert linha["etapa"] == "nao_seguiu"
    assert linha["proximo_passo"] == "Não procura mais"


def test_respondeu_depois_da_ultima_retomada_continua_em_conversa():
    _msg(1, LEAD, "cliente", _antes(days=6))
    _toques(1, LEAD, 3, _antes(days=2))
    _msg(1, LEAD, "cliente", _antes(days=1))
    assert _linha()["etapa"] == "em_conversa"


@pytest.mark.parametrize("conversa, fatos, passo", [
    ("novo", [], "Atendendo"),
    ("conversa", ["pediu_tempo"], "Volta a procurar em 03/12/2026"),
    ("conversa", ["vendedor"], "Em silêncio, com o vendedor"),
    ("conversa", ["visita"], "Aguardando a visita"),
    ("conversa", ["venda"], "Venda concluída"),      # pós-venda desligado por padrão
    ("sumiu", [], "Não procura mais"),
])
def test_proximo_passo_por_etapa(conversa, fatos, passo):
    _montar(conversa, fatos)
    assert _linha()["proximo_passo"] == passo


def test_lista_traz_nome_carro_origem_e_horario_da_loja():
    _lead(1, LEAD, nome="Juliana Souza")
    _sql("INSERT INTO interesse_veiculo (loja_id, lead_id, veiculo_id) VALUES (1, ?, ?)",
         (LEAD, _carro(1)))
    _msg(1, LEAD, "cliente", _antes(hours=2))
    linha = _linha()
    assert linha["nome"] == "Juliana Souza"
    assert linha["carro"] == "Hyundai HB20 2020"
    assert linha["origem"] == "WhatsApp"
    assert linha["ultimo_contato"] == "hoje 08:00"
    assert linha["ultimo_contato_iso"] == "2026-11-03T08:00:00-03:00"
    assert linha["etapa_rotulo"] == "Novo"


def test_lead_sem_nome_aparece_pelo_telefone():
    _conversa("novo")
    assert _linha()["nome"] == "(81) 9 9999-0000"


def test_busca_por_nome_ignora_acento():
    _lead(1, LEAD, nome="João Pedro")
    _conversa("novo")
    assert [l["lead_id"] for l in etapas_dos_leads(1, 30, "joao", agora=AGORA)] == [LEAD]
    assert etapas_dos_leads(1, 30, "maria", agora=AGORA) == []


def test_desde_dias_corta_quem_falou_antes():
    _msg(1, LEAD, "cliente", _antes(days=40))
    assert etapas_dos_leads(1, 30, agora=AGORA) == []
    assert len(etapas_dos_leads(1, 90, agora=AGORA)) == 1


def test_duas_lojas_nao_se_misturam():
    loja_b = criar_loja("Loja B")
    _conversa("conversa")
    _msg(loja_b, LEAD, "cliente", _antes(hours=3))
    _vender(loja_b, LEAD)
    _msg(loja_b, "5581888880000", "cliente", _antes(hours=3))
    lista_1 = etapas_dos_leads(1, 30, agora=AGORA)
    assert [l["lead_id"] for l in lista_1] == [LEAD]
    assert lista_1[0]["etapa"] == "em_conversa"
    assert _linha(loja_b)["etapa"] == "venda_registrada"


def test_todas_as_etapas_tem_rotulo():
    assert len(ORDEM_DAS_ETAPAS) == 7
    assert set(ORDEM_DAS_ETAPAS) == set(ROTULOS_ETAPA)


def test_funcoes_exigem_a_loja():
    with pytest.raises(TypeError):
        etapas_dos_leads()
    with pytest.raises(LojaNaoInformada):
        etapas_dos_leads(None, 30)
    with pytest.raises(LojaNaoInformada):
        cartao_do_lead(None, LEAD)
    with pytest.raises(LojaNaoInformada):
        resultado_do_periodo(None, HOJE, HOJE)


# ---------------------------------------------------------------- resultado
def test_resultado_conversas_fora_do_horario_e_primeira_resposta():
    a, b = "5581911110001", "5581911110002"
    _msg(1, a, "cliente", "2026-11-03 12:00:00")    # terça 09:00 em Recife: no horário
    _msg(1, a, "leo", "2026-11-03 12:00:08")
    _msg(1, b, "cliente", "2026-11-03 01:00:00")    # segunda 22:00 em Recife: fora
    _msg(1, b, "leo", "2026-11-03 01:00:20")
    r = resultado_do_periodo(1, date(2026, 11, 2), HOJE)
    assert r["conversas_atendidas"] == 2
    assert r["fora_do_horario"] == 1
    assert r["primeira_resposta_s"] == 14
    assert r["primeira_resposta_texto"] == "14 s"
    assert r["por_dia"] == [
        {"dia": "2026-11-02", "dia_texto": "02/11", "no_horario": 0, "fora_do_horario": 1},
        {"dia": "2026-11-03", "dia_texto": "03/11", "no_horario": 1, "fora_do_horario": 0},
    ]


def test_resultado_tempo_ate_o_vendedor_assumir():
    _handoff(1, LEAD, "2026-11-03 12:00:00", "2026-11-03 12:05:00", estado="humano_assumiu")
    _handoff(1, "5581922220000", "2026-11-03 12:00:00", "2026-11-03 12:00:00",
             estado="humano_assumiu", origem="painel")   # assumido sem o Léo chamar
    r = resultado_do_periodo(1, HOJE, HOJE)
    assert r["passados_ao_vendedor"] == 1
    assert r["ate_vendedor_assumir_s"] == 300
    assert r["ate_vendedor_assumir_texto"] == "5 min"


def test_venda_registrada_com_atraso_conta_no_mes_da_venda():
    _msg(1, LEAD, "cliente", _antes(days=5))
    _vender(1, LEAD, dia=date(2026, 10, 31))           # registrada em 03/11
    assert resultado_do_periodo(1, date(2026, 10, 1), date(2026, 10, 31))["vendas_registradas"] == 1
    assert resultado_do_periodo(1, date(2026, 11, 1), date(2026, 11, 30))["vendas_registradas"] == 0


def test_periodo_que_vira_o_mes_usa_o_fuso_da_loja():
    _msg(1, LEAD, "cliente", "2026-11-01 02:00:00")    # ainda 31/10 23:00 em Recife
    assert resultado_do_periodo(1, date(2026, 10, 1), date(2026, 10, 31))["conversas_atendidas"] == 1
    assert resultado_do_periodo(1, date(2026, 11, 1), date(2026, 11, 30))["conversas_atendidas"] == 0
    r = resultado_do_periodo(1, date(2026, 10, 25), HOJE)
    assert r["conversas_atendidas"] == 1
    assert len(r["por_dia"]) == 10


def test_qualificado_tem_carro_e_pagamento_ou_prazo():
    _lead(1, "5581933330001", interesse="HB20", forma_pagamento="financiado")
    _lead(1, "5581933330002", interesse="Onix")
    _msg(1, "5581933330001", "cliente", _antes(hours=1))
    _msg(1, "5581933330002", "cliente", _antes(hours=1))
    funil = {f["etapa"]: f["total"] for f in resultado_do_periodo(1, HOJE, HOJE)["funil"]}
    assert funil["conversas"] == 2
    assert funil["qualificados"] == 1


def test_resultado_de_uma_loja_nao_conta_a_outra():
    loja_b = criar_loja("Loja B")
    _msg(loja_b, LEAD, "cliente", _antes(hours=1))
    _vender(loja_b, LEAD)
    r = resultado_do_periodo(1, HOJE, HOJE)
    assert r["conversas_atendidas"] == 0
    assert r["vendas_registradas"] == 0
    assert resultado_do_periodo(loja_b, HOJE, HOJE)["vendas_registradas"] == 1


def test_mesmo_numero_de_vendas_em_leads_e_resultado():
    for lead_id in ("5581944440001", "5581944440002", "5581944440003"):
        _msg(1, lead_id, "cliente", _antes(hours=1))
    _vender(1, "5581944440001")
    _vender(1, "5581944440002")
    em_leads = sum(1 for l in etapas_dos_leads(1, 30, agora=AGORA) if l["etapa"] == "venda_registrada")
    em_resultado = resultado_do_periodo(1, date(2026, 11, 1), HOJE)["vendas_registradas"]
    assert em_leads == em_resultado == 2


def test_periodo_invertido_e_recusado():
    with pytest.raises(ValueError):
        resultado_do_periodo(1, HOJE, date(2026, 11, 1))


def test_periodo_sem_movimento():
    r = resultado_do_periodo(1, HOJE, HOJE)
    assert r["conversas_atendidas"] == 0
    assert r["primeira_resposta_s"] is None
    assert r["primeira_resposta_texto"] == "—"
    assert len(r["por_dia"]) == 1
    assert all(f["total"] == 0 for f in r["funil"])


# ---------------------------------------------------------------- cartão
def test_cartao_com_o_que_o_leo_ja_sabe():
    _lead(1, LEAD, nome="Juliana Souza", interesse="HB20", forma_pagamento="financiado",
          tem_troca="sim", prazo="este mês")
    _sql("INSERT INTO interesse_veiculo (loja_id, lead_id, veiculo_id) VALUES (1, ?, ?)",
         (LEAD, _carro(1)))
    _sql("INSERT INTO trocas (loja_id, lead_id, modelo, ano, km, estado) "
         "VALUES (1, ?, 'Gol', 2015, 80000, 'bom')", (LEAD,))
    _msg(1, LEAD, "cliente", _antes(hours=2))
    _visita(1, LEAD, _antes(days=2))
    _handoff(1, LEAD, _antes(hours=1))
    _situacao(1, LEAD, "pediu_tempo")
    c = cartao_do_lead(1, LEAD, agora=AGORA)
    assert c["nome"] == "Juliana Souza"
    assert c["telefone"] == "(81) 9 9999-0000"
    assert c["carro"] == "Hyundai HB20 2020"
    assert c["pagamento"] == "financiado"
    assert c["troca"] == "Gol 2015 · 80.000 km"
    assert c["prazo"] == "este mês"
    assert c["visita"] == "Visita · sábado 10h"
    assert c["motivo_do_chamado"] == "Quer negociar"
    assert c["etiqueta"] == "Pediu um tempo (até 03/12/2026)"
    assert c["etapa"] == "visita_marcada"


def test_cartao_do_telegram_nao_mostra_telefone():
    _msg(1, "8198765432", "cliente", _antes(hours=1), canal="telegram")
    c = cartao_do_lead(1, "8198765432", agora=AGORA)
    assert c["telefone"] == ""
    assert c["nome"] == "Cliente sem nome (…5432)"


def test_cartao_nao_mostra_dados_de_outra_loja():
    loja_b = criar_loja("Loja B")
    _lead(loja_b, LEAD, nome="Ana", interesse="Onix")
    c = cartao_do_lead(1, LEAD, agora=AGORA)
    assert c["nome"] != "Ana"
    assert c["carro"] == ""


# ---------------------------------------------------------------- só leitura
def _foto_do_banco():
    conexao = conectar()
    try:
        return list(conexao.iterdump())
    finally:
        conexao.close()


def test_nada_e_gravado_no_banco():
    _msg(1, LEAD, "cliente", _antes(hours=1))
    _vender(1, LEAD)
    antes = _foto_do_banco()
    etapas_dos_leads(1, 30, agora=AGORA)
    resultado_do_periodo(1, date(2026, 11, 1), HOJE)
    cartao_do_lead(1, LEAD, agora=AGORA)
    assert _foto_do_banco() == antes


def test_conexao_de_leitura_recusa_escrita():
    conexao = _ler()
    try:
        with pytest.raises(sqlite3.Error):
            conexao.execute("DELETE FROM mensagens")
    finally:
        conexao.close()
        

def test_mesmo_cliente_chamado_duas_vezes_conta_uma_e_bate_com_o_funil():
    _handoff(1, LEAD, "2026-11-03 11:00:00", "2026-11-03 11:01:00", estado="encerrado")
    _handoff(1, LEAD, "2026-11-03 12:00:00", "2026-11-03 12:03:00", estado="humano_assumiu")
    _visita(1, LEAD, "2026-11-03 12:10:00")
    r = resultado_do_periodo(1, HOJE, HOJE)
    funil = {f["etapa"]: f["total"] for f in r["funil"]}
    assert r["passados_ao_vendedor"] == funil["com_vendedor"] == 1
    assert r["visitas_marcadas"] == funil["visitas"] == 1
    assert r["vendas_registradas"] == funil["vendas"]


def test_troca_nao_repete_o_ano():
    _sql("INSERT INTO trocas (loja_id, lead_id, modelo, ano, km, estado) "
         "VALUES (1, ?, 'Gol 2015', 2015, 90000, 'bom')", (LEAD,))
    _msg(1, LEAD, "cliente", _antes(hours=1))
    assert cartao_do_lead(1, LEAD, agora=AGORA)["troca"] == "Gol 2015 · 90.000 km"

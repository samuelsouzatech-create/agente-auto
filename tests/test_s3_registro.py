"""
S3 (Fase 3): tela Registro com a leitura unificada do P6.
- uma mudança de configuração, uma pausa e uma venda aparecem com quem e quando;
- filtros por pessoa, tipo de ação e período (dia no fuso da loja);
- cada loja vê só o que é dela; "todas as lojas" junta tudo e mostra a loja;
- horário no fuso de cada loja, sem texto técnico;
- a tela abre, filtra e troca para todas as lojas (AppTest).
Tudo offline, banco temporário do conftest (ator "Teste", operador, painel).
"""
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import logs, pausa
from app.estoque import adicionar_carro
from app.lojas import salvar_config
from app.lojas_admin import criar_loja
from app.registro import registrar
from app.registro_leitura import (
    acoes_no_registro, filtrar_registro, filtrar_registro_de_todas, pessoas_no_registro,
)
from app.registro_tela import linhas_do_registro, periodo_padrao
from app.vendas import registrar_venda

RAIZ = Path(__file__).resolve().parent.parent
TELA = RAIZ / "paginas" / "operador" / "registro.py"
LEAD = "5581999990000"
AGORA = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)


def _venda(loja):
    carro = adicionar_carro("Hyundai", "HB20", 2020, 40000, "Prata", "Manual", 60000.0,
                            loja_id=loja)
    registrar_venda(loja, LEAD, carro, date(2026, 1, 10), "avista", vendedor="Ana")


def _tres_acoes(loja=1):
    salvar_config(loja, {"cidade": "Recife"}, "Samuel")
    pausa.pausar(loja, usuario="Ana", papel="cliente", motivo="feriado")
    _venda(loja)


def _abrir(loja=1):
    at = AppTest.from_file(str(TELA), default_timeout=30)
    at.session_state["_papel"] = "operador"
    at.session_state["loja_id"] = loja
    return at.run()


# ------------------------------------------------------------ pronto quando

def test_config_pausa_e_venda_aparecem_com_quem_e_quando():
    _tres_acoes()
    linhas = linhas_do_registro(filtrar_registro(1), com_loja=False)
    por = {l["O quê"]: l for l in linhas}
    assert {"Mudou configuração", "Pausou os envios", "Registrou venda"} <= set(por)
    assert por["Mudou configuração"]["Quem"] == "Samuel"
    assert por["Pausou os envios"]["Quem"] == "Ana"
    assert por["Registrou venda"]["Quem"] == "Teste"
    assert por["Registrou venda"]["Papel"] == "Operador"
    for l in linhas:
        assert l["Quando"].startswith("hoje "), l
    assert por["Mudou configuração"]["Detalhe"] == "Cidade: vazio → Recife"
    assert por["Pausou os envios"]["Detalhe"] == "Motivo: feriado"
    venda = por["Registrou venda"]["Detalhe"]
    assert "Hyundai HB20 2020" in venda and "10/01/2026" in venda and "à vista" in venda
    assert venda.startswith("Cliente: ")


def test_sem_texto_tecnico():
    _tres_acoes()
    for linha in linhas_do_registro(filtrar_registro(1), com_loja=False):
        for valor in linha.values():
            for proibido in ("UTC", "lead:", "config:", "venda_id", LEAD):
                assert proibido not in str(valor), (proibido, linha)


# ------------------------------------------------------------ horário

def test_horario_no_fuso_de_cada_loja():
    manaus = criar_loja("Loja Manaus", "Manaus", "America/Manaus", "veiculos")
    quando = datetime(2026, 11, 4, 0, 40, tzinfo=timezone.utc)
    registrar("teste_fuso", 1, None, {"n": 1}, agora=quando)
    registrar("teste_fuso", manaus, None, {"n": 2}, agora=quando)
    l1 = linhas_do_registro(filtrar_registro(1, acao="teste_fuso"), com_loja=False, agora=AGORA)
    l2 = linhas_do_registro(filtrar_registro(manaus, acao="teste_fuso"), com_loja=False,
                            agora=AGORA)
    assert l1[0]["Quando"] == "ontem 21:40"       # Recife, UTC-3
    assert l2[0]["Quando"] == "ontem 20:40"       # Manaus, UTC-4


def test_periodo_padrao_sao_30_dias_no_fuso_da_loja():
    assert periodo_padrao(1, agora=AGORA) == (date(2026, 10, 6), date(2026, 11, 4))


# ------------------------------------------------------------ filtros

def test_periodo_usa_o_dia_da_loja():
    registrar("teste_periodo", 1, None, None,
              agora=datetime(2026, 3, 1, 2, 30, tzinfo=timezone.utc))   # 28/02 23:30 em Recife
    assert len(filtrar_registro(1, inicio=date(2026, 2, 28), fim=date(2026, 2, 28))) == 1
    assert filtrar_registro(1, inicio=date(2026, 3, 1), fim=date(2026, 3, 1)) == []
    with pytest.raises(ValueError):
        filtrar_registro(1, inicio=date(2026, 3, 2), fim=date(2026, 3, 1))


def test_periodo_vale_para_pausas():
    pausa.pausar(1, usuario="Ana", papel="cliente",
                 agora=datetime(2026, 3, 1, 2, 30, tzinfo=timezone.utc))
    itens = filtrar_registro(1, inicio=date(2026, 2, 28), fim=date(2026, 2, 28))
    assert [i["acao"] for i in itens] == ["pausar_envios"]


def test_filtro_por_pessoa():
    _tres_acoes()
    assert {i["acao"] for i in filtrar_registro(1, pessoa="Ana")} == {"pausar_envios"}
    assert {i["acao"] for i in filtrar_registro(1, pessoa=" Samuel ")} == {"salvar_configuracao"}
    assert {i["acao"] for i in filtrar_registro(1, pessoa="Teste")} == {"registrar_venda"}
    assert pessoas_no_registro(1) == ["Ana", "Samuel", "Teste"]


def test_filtro_por_tipo_de_acao():
    _tres_acoes()
    pausa.retomar(1, usuario="Ana", papel="cliente")
    assert [i["fonte"] for i in filtrar_registro(1, acao="pausar_envios")] == ["pausas_envio"]
    assert [i["acao"] for i in filtrar_registro(1, acao="retomar_envios")] == ["retomar_envios"]
    assert [i["acao"] for i in filtrar_registro(1, acao="salvar_configuracao")] == [
        "salvar_configuracao"]
    assert [i["acao"] for i in filtrar_registro(1, acao="registrar_venda")] == ["registrar_venda"]
    assert set(acoes_no_registro(1)) == {"pausar_envios", "retomar_envios",
                                         "salvar_configuracao", "registrar_venda"}


# ------------------------------------------------------------ lojas

def test_cada_loja_ve_so_o_que_e_dela():
    b = criar_loja("Loja B", "Caruaru", "America/Recife", "veiculos")
    salvar_config(b, {"tom": "bem formal"}, "Outra Pessoa")
    salvar_config(1, {"cidade": "Recife"}, "Samuel")
    assert {i["loja_id"] for i in filtrar_registro(1)} == {1}
    assert {i["loja_id"] for i in filtrar_registro(b)} == {b}
    assert "Outra Pessoa" not in pessoas_no_registro(1)


def test_todas_as_lojas_junta_e_mostra_a_loja():
    b = criar_loja("Loja B", "Caruaru", "America/Recife", "veiculos")
    salvar_config(b, {"tom": "bem formal"}, "Outra Pessoa")
    salvar_config(1, {"cidade": "Recife"}, "Samuel")
    todas = filtrar_registro_de_todas()
    assert {i["loja_id"] for i in todas} == {1, b}
    linhas = linhas_do_registro(todas, com_loja=True)
    assert {"Loja 1", "Loja B"} <= {l["Loja"] for l in linhas}


def test_evento_sem_loja_so_em_todas():
    logs.registrar_canal_desconhecido("telegram", "123")
    assert filtrar_registro(1) == []
    linhas = linhas_do_registro(filtrar_registro_de_todas(), com_loja=True)
    assert linhas[0]["Loja"] == "Sistema"
    assert linhas[0]["Detalhe"] == "Canal: Telegram"


def test_sem_loja_falha():
    with pytest.raises(ValueError):
        filtrar_registro(None)


# ------------------------------------------------------------ tela

def test_tela_mostra_as_tres_acoes():
    _tres_acoes()
    at = _abrir()
    assert not at.exception, at.exception
    tabela = at.dataframe[0].value
    assert {"Mudou configuração", "Pausou os envios", "Registrou venda"} <= set(tabela["O quê"])
    assert "Loja" not in tabela.columns


def test_tela_filtra_e_mostra_todas_as_lojas():
    _tres_acoes()
    b = criar_loja("Loja B", "Caruaru", "America/Recife", "veiculos")
    salvar_config(b, {"tom": "bem formal"}, "Outra Pessoa")
    at = _abrir()
    at.selectbox(key="registro_acao_loja").set_value("registrar_venda").run()
    assert not at.exception, at.exception
    assert list(at.dataframe[0].value["O quê"]) == ["Registrou venda"]
    at.radio(key="registro_escopo").set_value("todas").run()
    tabela = at.dataframe[0].value
    assert "Loja" in tabela.columns
    assert {"Loja 1", "Loja B"} <= set(tabela["Loja"])


def test_tela_vazia_avisa():
    at = _abrir()
    assert not at.exception, at.exception
    assert any("Nada registrado" in str(i.value) for i in at.info)

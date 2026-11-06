"""
S8 (Fase 3): Custos e preços, nível Geral.
- tabela do mês por loja (Brasília) e total; uma loja não entra na outra;
- 12 meses em UMA consulta; implantação à parte, igual ao P7c, em uma consulta;
- recálculo por intervalo; repetível; só reescreve os custos (4A);
- salvar/apagar preço recalcula junto, numa transação; parcial = total (5A);
- falha no recálculo: preço não salvo/apagado, nada no Registro;
- preço e recálculo no Registro sem loja, com o ator (1A); só o operador;
- a tela (AppTest) mostra, recalcula, salva e apaga com caixinha.
Tudo offline, banco temporário do conftest (ator "Teste", operador, painel).
"""
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from banco import conectar
from app import custos, custos_precos as cp, estado_loja, precos
from app.ator import AtorInvalido, como
from app.custos import Uso
from app.estado_loja import SoOperador
from app.lojas import criar_loja
from app.registro_leitura import filtrar_registro_de_todas
from app.registro_tela import linhas_do_registro
from paginas.menu import GERAL, OPERADOR, arquivos

RAIZ = Path(__file__).resolve().parent.parent
TELA = RAIZ / "paginas" / "operador" / "custos_precos.py"
UTC = timezone.utc
SET_20 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
OUT_10 = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
OUT_15 = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
OUT_20 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
VIRADA = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)        # 31/10 23h em Brasília
AGORA = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)
UM = (1000 * 0.10 + 100 * 0.40) / 1e6 * 5.0              # custo de IA de um uso padrão


# ---------------------------------------------------------------- apoio

def _precos_base(desde="2026-01-01"):
    precos.cadastrar_preco("ia.entrada", 0.10, desde, "USD")
    precos.cadastrar_preco("ia.saida", 0.40, desde, "USD")
    precos.cadastrar_preco("cambio.usd_brl", 5.0, desde)


def _uso(loja, lead, quando, entrada=1000, saida=100, servico=0):
    custos.registrar_uso(loja, lead, "telegram", Uso(entrada, saida), agora=quando,
                         msgs_servico=servico)


def _um(sql, parametros=()):
    con = conectar()
    try:
        return con.execute(sql, parametros).fetchone()[0]
    finally:
        con.close()


def _linhas(sql, parametros=()):
    con = conectar()
    try:
        return [dict(l) for l in con.execute(sql, parametros).fetchall()]
    finally:
        con.close()


def _custos():
    return _linhas("SELECT id, custo_llm, custo_meta, custo_completo FROM uso_custos ORDER BY id")


def _cenario():
    """Loja 1: A, B (com 2 mensagens da Meta) e V em outubro; C em setembro.
    Loja B: um uso 9 vezes maior em outubro."""
    _precos_base()
    precos.cadastrar_preco("meta.servico", 0.04, "2026-01-01", "BRL")
    b = criar_loja("Loja B")
    _uso(1, "A", OUT_10)
    _uso(1, "A", OUT_20)
    _uso(1, "B", OUT_20, servico=2)
    _uso(1, "C", SET_20)
    _uso(1, "V", VIRADA)
    _uso(b, "A", OUT_10, entrada=9000, saida=900)
    return b


def _contar_consultas(monkeypatch):
    consultas = []
    real = cp.conectar

    def conectar_contando():
        con = real()
        con.set_trace_callback(
            lambda sql: consultas.append(sql) if sql.lstrip().upper().startswith(("SELECT", "WITH")) else None)
        return con

    monkeypatch.setattr(cp, "conectar", conectar_contando)
    return consultas


# ---------------------------------------------------------------- mês por loja

def test_tabela_do_mes_por_loja_e_total():
    b = _cenario()
    r = cp.custos_do_mes(2026, 10)
    por = {l["loja_id"]: l for l in r["lojas"]}
    assert por[1]["conversas"] == 3                                   # A, B e V
    assert por[1]["custo_ia"] == pytest.approx(4 * UM, abs=1e-6)
    assert por[1]["custo_meta"] == pytest.approx(0.08)
    assert por[1]["custo_por_conversa"] == pytest.approx((4 * UM + 0.08) / 3, abs=1e-6)
    assert por[b]["conversas"] == 1
    assert por[b]["custo_ia"] == pytest.approx(9 * UM, abs=1e-6) and por[b]["custo_meta"] == 0
    assert r["total"]["conversas"] == 4
    assert r["total"]["custo_total"] == pytest.approx(13 * UM + 0.08, abs=1e-6)


def test_mes_vira_no_horario_de_brasilia():
    _precos_base()
    _uso(1, "V", VIRADA)
    assert cp.custos_do_mes(2026, 10)["total"]["conversas"] == 1
    assert cp.custos_do_mes(2026, 11)["total"]["conversas"] == 0


def test_numeros_de_uma_loja_nao_entram_na_outra():
    b = _cenario()
    por = {l["loja_id"]: l for l in cp.custos_do_mes(2026, 9)["lojas"]}
    assert por[1]["conversas"] == 1 and por[b]["conversas"] == 0 and por[b]["custo_total"] == 0


def test_tabela_do_mes_em_uma_consulta(monkeypatch):
    _cenario()
    consultas = _contar_consultas(monkeypatch)
    cp.custos_do_mes(2026, 10)
    assert len(consultas) == 1


def test_linhas_do_mes_sem_texto_tecnico_e_um_tipo_por_coluna():
    _cenario()
    linhas = cp.linhas_do_mes(cp.custos_do_mes(2026, 10))
    assert linhas[-1]["Loja"] == "Total"
    for coluna in linhas[0]:
        assert len({type(l[coluna]) for l in linhas}) == 1, coluna
    texto = str(linhas)
    for proibido in ("UTC", "id ", "None"):
        assert proibido not in texto


# ---------------------------------------------------------------- 12 meses

def test_doze_meses_em_uma_consulta(monkeypatch):
    _cenario()
    consultas = _contar_consultas(monkeypatch)
    meses = cp.ultimos_12_meses(agora=AGORA)
    assert len(consultas) == 1
    assert len(meses) == 12
    assert (meses[0]["ano"], meses[0]["mes"]) == (2026, 11)
    assert (meses[-1]["ano"], meses[-1]["mes"]) == (2025, 12)
    outubro = next(m for m in meses if (m["ano"], m["mes"]) == (2026, 10))
    setembro = next(m for m in meses if (m["ano"], m["mes"]) == (2026, 9))
    assert outubro["conversas"] == 4 and setembro["conversas"] == 1
    assert outubro["custo_total"] == pytest.approx(cp.custos_do_mes(2026, 10)["total"]["custo_total"])


def test_doze_meses_de_uma_loja_so(monkeypatch):
    b = _cenario()
    consultas = _contar_consultas(monkeypatch)
    meses = cp.ultimos_12_meses(b, agora=AGORA)
    assert len(consultas) == 1
    outubro = next(m for m in meses if (m["ano"], m["mes"]) == (2026, 10))
    assert outubro["conversas"] == 1 and outubro["custo_ia"] == pytest.approx(9 * UM, abs=1e-6)
    assert sum(m["conversas"] for m in meses) == 1
    linhas = cp.linhas_dos_12_meses(meses)
    assert linhas[0]["Mês"] == "novembro/2026"


# ---------------------------------------------------------------- implantação

def test_implantacao_igual_ao_p7c_e_a_parte():
    _precos_base()
    teste = criar_loja("Loja em teste")
    nova = criar_loja("Loja que entrou no ar")
    _uso(teste, "A", OUT_10)
    _uso(nova, "A", OUT_10)
    estado_loja.colocar_no_ar(nova, agora=OUT_15)
    _uso(nova, "B", OUT_20)
    _uso(1, "A", OUT_10)                                       # loja antiga: sem implantação
    impl = {i["loja_id"]: i for i in cp.implantacao_de_todas()}
    assert set(impl) == {teste, nova}
    for loja in (teste, nova):
        p7c = custos.resumo_implantacao(loja)
        assert impl[loja]["conversas"] == p7c["conversas"]
        assert impl[loja]["custo_total"] == pytest.approx(p7c["custo_total"], abs=1e-6)
    assert impl[nova]["conversas"] == 1
    mes = {l["loja_id"]: l for l in cp.custos_do_mes(2026, 10)["lojas"]}
    assert mes[nova]["conversas"] == 2                          # o mês continua cheio
    situacoes = {l["Loja"]: l["Situação"] for l in cp.linhas_da_implantacao(list(impl.values()))}
    assert situacoes["Loja em teste"] == "Ainda em teste"
    assert situacoes["Loja que entrou no ar"] == "No ar desde 15/10/2026"


def test_implantacao_em_uma_consulta(monkeypatch):
    criar_loja("Loja em teste")
    consultas = _contar_consultas(monkeypatch)
    cp.implantacao_de_todas()
    assert len(consultas) == 1


# ---------------------------------------------------------------- recálculo (4A)

def _usos_sem_preco():
    b = criar_loja("Loja B")
    _uso(1, "A", SET_20)
    _uso(1, "A", OUT_10)
    _uso(1, "V", VIRADA)
    _uso(b, "A", OUT_20)
    _precos_base()                     # preço chega depois, sem recalcular
    return b


def test_recalculo_so_mexe_no_intervalo():
    _usos_sem_preco()
    n = cp.recalcular_periodo(date(2026, 10, 1), date(2026, 10, 31))
    assert n == 3                                               # OUT_10, VIRADA e loja B
    por_completo = [c["custo_completo"] for c in _custos()]
    assert por_completo == [0, 1, 1, 1]                         # setembro ficou como estava


def test_recalcular_duas_vezes_da_o_mesmo_resultado():
    _usos_sem_preco()
    cp.recalcular_mes(2026, 10)
    primeira = _custos()
    cp.recalcular_mes(2026, 10)
    assert _custos() == primeira


def test_recalculo_so_reescreve_os_custos():
    _usos_sem_preco()
    con = conectar()
    con.execute("UPDATE uso_custos SET custo_llm = 999")
    con.commit()
    con.close()
    derivados = {"custo_llm", "custo_meta", "custo_completo"}
    antes = [{k: v for k, v in l.items() if k not in derivados}
             for l in _linhas("SELECT * FROM uso_custos ORDER BY id")]
    precos_antes = precos.listar_precos()
    cp.recalcular_mes(2026, 10)
    depois = [{k: v for k, v in l.items() if k not in derivados}
              for l in _linhas("SELECT * FROM uso_custos ORDER BY id")]
    assert depois == antes
    assert precos.listar_precos() == precos_antes               # nada digitado é tocado
    assert _custos()[1]["custo_llm"] == pytest.approx(UM)       # o errado foi corrigido


def test_recalculo_vai_ao_registro_sem_loja():
    _usos_sem_preco()
    cp.recalcular_periodo(date(2026, 10, 1), date(2026, 10, 31))
    [l] = _linhas("SELECT * FROM registro_acoes WHERE acao = 'recalcular_custos'")
    assert (l["pessoa"], l["papel"], l["loja_id"]) == ("Teste", "operador", None)
    linha = next(x for x in linhas_do_registro(filtrar_registro_de_todas(), com_loja=True)
                 if x["O quê"] == "Recalculou custos")
    assert linha["Loja"] == "Sistema"
    assert "01/10/2026 a 31/10/2026" in linha["Detalhe"]


def test_periodo_invertido_recusa():
    with pytest.raises(ValueError):
        cp.recalcular_periodo(date(2026, 10, 31), date(2026, 10, 1))


# ---------------------------------------------------------------- preço com recálculo (5A)

def test_salvar_preco_recalcula_igual_ao_recalculo_total():
    _cenario()
    original = _custos()
    r = cp.cadastrar_preco("ia.entrada", 0.30, "2026-10-15", "USD")
    assert r["recalculados"] == 3                               # OUT_20 (2) e VIRADA
    parcial = _custos()
    custos.recalcular_custos()
    assert _custos() == parcial                                  # parcial = total
    assert parcial[0] == original[0]                             # OUT_10: preço antigo
    assert parcial[1]["custo_llm"] > original[1]["custo_llm"]    # OUT_20: preço novo
    [l] = _linhas("SELECT * FROM registro_acoes WHERE acao = 'cadastrar_preco'")
    assert (l["pessoa"], l["loja_id"]) == ("Teste", None)
    assert "ia." not in l["depois"]


def test_apagar_preco_volta_o_anterior_igual_ao_recalculo_total():
    _cenario()
    original = _custos()
    cp.cadastrar_preco("ia.entrada", 0.30, "2026-10-15", "USD")
    novo = next(p["id"] for p in precos.listar_precos() if p["vigente_desde"] == "2026-10-15")
    r = cp.apagar_preco(novo)
    assert r == {"apagado": True, "recalculados": 3}
    parcial = _custos()
    custos.recalcular_custos()
    assert _custos() == parcial == original
    assert cp.apagar_preco(novo) == {"apagado": False, "recalculados": 0}
    assert _um("SELECT COUNT(*) FROM registro_acoes WHERE acao = 'apagar_preco'") == 1


def test_corrigir_preco_na_mesma_data_guarda_o_antes():
    _precos_base()
    r = cp.cadastrar_preco("ia.entrada", 0.20, "2026-01-01", "USD")
    assert r["corrigiu"] is True
    l = _linhas("SELECT antes FROM registro_acoes WHERE acao = 'cadastrar_preco'")[0]
    assert "US$ 0,1000" in l["antes"]


def test_falha_no_recalculo_nao_salva_o_preco(monkeypatch):
    def quebrado(*a, **k):
        raise RuntimeError("falhou")
    monkeypatch.setattr(custos, "recalcular_custos", quebrado)
    with pytest.raises(RuntimeError):
        cp.cadastrar_preco("ia.entrada", 0.10, "2026-01-01", "USD")
    assert precos.listar_precos() == []
    assert _um("SELECT COUNT(*) FROM registro_acoes") == 0


def test_falha_no_recalculo_nao_apaga_o_preco(monkeypatch):
    precos.cadastrar_preco("ia.entrada", 0.10, "2026-01-01", "USD")
    preco_id = precos.listar_precos()[0]["id"]

    def quebrado(*a, **k):
        raise RuntimeError("falhou")
    monkeypatch.setattr(custos, "recalcular_custos", quebrado)
    with pytest.raises(RuntimeError):
        cp.apagar_preco(preco_id)
    assert len(precos.listar_precos()) == 1
    assert _um("SELECT COUNT(*) FROM registro_acoes") == 0


def test_preco_invalido_nao_grava_nada():
    with pytest.raises(precos.PrecoInvalido):
        cp.cadastrar_preco("ia.entrada", -1, "2026-01-01", "USD")
    assert precos.listar_precos() == []
    assert _um("SELECT COUNT(*) FROM registro_acoes") == 0


def test_so_o_operador_muda_preco_e_recalcula():
    with como("Ana", "cliente", "painel", loja_id=1):
        with pytest.raises((SoOperador, AtorInvalido)):
            cp.cadastrar_preco("ia.entrada", 0.10, "2026-01-01", "USD")
        with pytest.raises((SoOperador, AtorInvalido)):
            cp.recalcular_mes(2026, 10)
    assert precos.listar_precos() == []


def test_historico_de_precos_com_situacao():
    for desde in ("2026-01-01", "2026-06-01", "2026-12-01"):
        precos.cadastrar_preco("ia.entrada", 0.10, desde, "USD")
    situacoes = {p["vigente_desde"]: p["situacao"] for p in cp.historico_de_precos(agora=AGORA)}
    assert situacoes == {"2026-12-01": "Agendado", "2026-06-01": "Em vigor",
                         "2026-01-01": "Substituído"}
    linha = cp.linhas_de_precos(cp.historico_de_precos(agora=AGORA))[0]
    assert linha["Valor"] == "US$ 0,1000" and linha["Vale desde"] == "01/12/2026"


# ---------------------------------------------------------------- tela

def _abrir(monkeypatch):
    monkeypatch.setenv("OPERADOR_NOME", "Teste")
    at = AppTest.from_file(str(TELA), default_timeout=30)
    at.session_state["_papel"] = "operador"
    at.session_state["loja_id"] = 1
    return at.run()


def _tabela(at, coluna):
    return next((d.value for d in at.dataframe if coluna in d.value.columns), None)


def test_tela_recusa_quem_nao_e_operador():
    at = AppTest.from_file(str(TELA), default_timeout=30).run()
    assert not at.exception
    assert any("só do operador" in e.value for e in at.error)
    assert len(at.title) == 0


def test_tela_mostra_lojas_e_total(monkeypatch):
    _precos_base()
    b = criar_loja("Loja B")
    _uso(1, "A", None)
    _uso(b, "A", None)
    at = _abrir(monkeypatch)
    assert not at.exception, at.exception
    tabela = _tabela(at, "Custo por conversa")
    assert "Loja B" in list(tabela["Loja"]) and list(tabela["Loja"])[-1] == "Total"
    assert list(tabela["Conversas"])[-1] == 2


def test_tela_doze_meses(monkeypatch):
    at = _abrir(monkeypatch)
    assert _tabela(at, "Mês") is None
    at.button(key="s8_12_meses").click().run()
    assert not at.exception, at.exception
    assert len(_tabela(at, "Mês")) == 12


def test_tela_recalcular_sem_caixinha(monkeypatch):
    _uso(1, "A", None)
    _precos_base()
    at = _abrir(monkeypatch)
    assert not at.button(key="s8_recalcular").disabled
    at.button(key="s8_recalcular").click().run()
    assert not at.exception, at.exception
    assert any("1 registro(s) atualizado(s)" in s.value for s in at.success)
    assert _custos()[0]["custo_completo"] == 1


def test_tela_salva_preco_e_recalcula(monkeypatch):
    at = _abrir(monkeypatch)
    at.selectbox(key="s8_item_0").set_value("ia.saida")
    at.number_input(key="s8_valor_0").set_value(0.5)
    at.date_input(key="s8_desde_0").set_value(date(2026, 1, 1))
    at.button(key="s8_salvar").click().run()
    assert not at.exception, at.exception
    assert any("Preço salvo" in s.value and "recalculado" in s.value for s in at.success)
    [p] = precos.listar_precos()
    assert (p["item"], p["valor"], p["vigente_desde"]) == ("ia.saida", 0.5, "2026-01-01")
    assert _um("SELECT pessoa FROM registro_acoes WHERE acao = 'cadastrar_preco'") == "Teste"


def test_tela_avisa_quando_o_recalculo_falha(monkeypatch):
    def quebrado(*a, **k):
        raise RuntimeError("falhou")
    monkeypatch.setattr(custos, "recalcular_custos", quebrado)
    at = _abrir(monkeypatch)
    at.number_input(key="s8_valor_0").set_value(0.5)
    at.button(key="s8_salvar").click().run()
    assert not at.exception, at.exception
    assert any("NÃO salvo" in e.value for e in at.error)
    assert precos.listar_precos() == []


def test_tela_apagar_pede_caixinha(monkeypatch):
    precos.cadastrar_preco("ia.entrada", 0.10, "2026-01-01", "USD")
    at = _abrir(monkeypatch)
    assert at.button(key="s8_apagar").disabled
    at.checkbox(key="s8_apagar_conf_0").check().run()
    at.button(key="s8_apagar").click().run()
    assert not at.exception, at.exception
    assert any("Preço apagado" in s.value for s in at.success)
    assert precos.listar_precos() == []
    assert _um("SELECT pessoa FROM registro_acoes WHERE acao = 'apagar_preco'") == "Teste"


def test_tela_nao_faz_sql_nem_conta():
    fonte = TELA.read_text(encoding="utf-8")
    assert "conectar(" not in fonte and "SELECT" not in fonte and "registrar(" not in fonte
    assert "exigir_operador()" in fonte and "definir_ator_da_sessao()" in fonte


def test_tela_antiga_saiu_e_a_nova_ficou():
    # S10b: a tela antiga paginas/custos.py saiu; fica só Custos e preços.
    assert "paginas/custos.py" not in arquivos(OPERADOR)
    assert not (RAIZ / "paginas" / "custos.py").exists()
    assert "paginas/operador/custos_precos.py" in arquivos(GERAL)

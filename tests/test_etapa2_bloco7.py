"""
Testes da Etapa 2, Bloco 7: tela de retomadas e pós-venda e o botão de pausa.
Os dois papéis pausam e retomam; a pausa para os três jobs; lojas separadas;
resultado do mês com resposta e agendamento; a tela é dos dois painéis.
"""
import py_compile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import banco
from banco import conectar
from app import painel_envios as pe
from app import pausa, regua
from app.jobs import remarketing as job_rm
from app.jobs.pos_venda import rodar_pos_venda
from app.jobs.remarketing import rodar_remarketing
from app.lojas import criar_loja, salvar_config
from app.relogio import para_banco
from paginas.menu import CLIENTE, OPERADOR, arquivos

RAIZ = Path(__file__).resolve().parent.parent
AGORA = datetime(2026, 10, 30, 13, 0, tzinfo=timezone.utc)


def _t(**delta):
    return para_banco(AGORA + timedelta(**delta))


def _x(sql, parametros=()):
    c = conectar()
    try:
        c.execute(sql, parametros)
        c.commit()
    finally:
        c.close()


def _ligar(loja_id=1):
    salvar_config(loja_id, {"modulos.remarketing": True, "remarketing.limite_mensal": 30,
                            "modulos.pos_venda": True}, "Samuel")


# ------------------------------------------------------------ pausa

def test_migracao_v8_cria_a_tabela():
    c = conectar()
    try:
        assert banco.versao_schema(c) == banco.VERSAO_SCHEMA >= 8
        tabelas = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        c.close()
    assert "pausas_envio" in tabelas


def test_dono_da_loja_pausa_e_retoma():
    pausa.pausar(1, usuario="Dono", papel="cliente", motivo="mensagem errada", agora=AGORA)
    s = pausa.situacao(1)
    assert s["pausado"] and s["papel"] == "cliente" and s["motivo"] == "mensagem errada"
    pausa.retomar(1, usuario="Dono", papel="cliente", agora=AGORA + timedelta(hours=1))
    assert not pausa.pausado(1)


def test_operador_retoma_o_que_a_loja_pausou_e_vice_versa():
    pausa.pausar(1, usuario="Dono", papel="cliente", agora=AGORA)
    pausa.retomar(1, usuario="Samuel", papel="operador", agora=AGORA)
    pausa.pausar(1, usuario="Samuel", papel="operador", agora=AGORA)
    pausa.retomar(1, usuario="Dono", papel="cliente", agora=AGORA)
    assert [p["acao"] for p in pausa.historico(1)] == ["retomar", "pausar", "retomar", "pausar"]


def test_pausar_duas_vezes_ou_retomar_sem_pausa():
    with pytest.raises(pausa.PausaInvalida):
        pausa.retomar(1, usuario="Dono", papel="cliente")
    pausa.pausar(1, usuario="Dono", papel="cliente")
    with pytest.raises(pausa.PausaInvalida):
        pausa.pausar(1, usuario="Samuel", papel="operador")


@pytest.mark.parametrize("usuario,papel", [("", "cliente"), ("   ", "operador"), ("Dono", "admin")])
def test_usuario_ou_papel_invalido(usuario, papel):
    with pytest.raises(pausa.PausaInvalida):
        pausa.pausar(1, usuario=usuario, papel=papel)
    assert not pausa.pausado(1)


def test_lojas_separadas():
    loja_b = criar_loja("Loja B")
    pausa.pausar(1, usuario="Dono", papel="cliente")
    assert pausa.pausado(1) and not pausa.pausado(loja_b)


def test_retomar_cancela_pos_venda_que_venceu_na_pausa():
    for passo, quando in ((1, _t(days=-10)), (2, _t(days=-1)), (3, _t(days=5))):
        _x("INSERT INTO regua_execucoes (loja_id, regua_id, passo_id, lead_id, evento_tipo, "
           "evento_id, agendado_para, estado) VALUES (1, 1, ?, 'l1', 'venda', 1, ?, 'agendado')",
           (passo, quando))
    pausa.pausar(1, usuario="Dono", papel="cliente", agora=AGORA - timedelta(days=11))
    r = pausa.retomar(1, usuario="Dono", papel="cliente", agora=AGORA)
    assert r["cancelados"] == 1
    c = conectar()
    try:
        estados = [tuple(l) for l in c.execute(
            "SELECT passo_id, estado, motivo FROM regua_execucoes ORDER BY passo_id")]
    finally:
        c.close()
    assert estados == [(1, "cancelado", "pausa_longa"), (2, "agendado", None), (3, "agendado", None)]


# ------------------------------------------------------------ jobs param na pausa

def test_remarketing_nao_roda_com_a_loja_pausada(monkeypatch):
    _ligar()
    chamadas = []
    monkeypatch.setattr(job_rm, "elegiveis", lambda loja_id, agora: chamadas.append(loja_id) or [])
    pausa.pausar(1, usuario="Dono", papel="cliente")
    rodar_remarketing(AGORA, envio_real=False, lojas=[1], pausa_s=0)
    assert chamadas == []
    pausa.retomar(1, usuario="Dono", papel="cliente")
    rodar_remarketing(AGORA, envio_real=False, lojas=[1], pausa_s=0)
    assert chamadas == [1]


def test_pos_venda_nao_roda_com_a_loja_pausada(monkeypatch):
    _ligar()
    chamadas = []
    monkeypatch.setattr(regua, "vencidas", lambda loja_id, agora, limite: chamadas.append(loja_id) or [])
    pausa.pausar(1, usuario="Samuel", papel="operador")
    rodar_pos_venda(AGORA, envio_real=False, lojas=[1])
    assert chamadas == []
    pausa.retomar(1, usuario="Samuel", papel="operador")
    rodar_pos_venda(AGORA, envio_real=False, lojas=[1])
    assert chamadas == [1]


@pytest.mark.parametrize("arquivo", ["app/jobs/remarketing.py", "app/jobs/pos_venda.py",
                                     "app/jobs/reativacao.py"])
def test_os_tres_jobs_conferem_a_pausa(arquivo):
    assert "pausado(loja_id)" in (RAIZ / arquivo).read_text(encoding="utf-8")


# ------------------------------------------------------------ dados da tela

def test_resultado_do_mes_conta_resposta_agendamento_e_custo():
    _x("INSERT INTO remarketing_envios (loja_id, lead_id, canal, toque, estado, enviado_em, criado_em, "
       "custo_meta) VALUES (1, 'l1', 'whatsapp', 1, 'enviado', ?, ?, 0.5)", (_t(hours=-2), _t(hours=-2)))
    _x("INSERT INTO remarketing_envios (loja_id, lead_id, canal, toque, estado, enviado_em, criado_em, "
       "custo_meta) VALUES (1, 'l2', 'whatsapp', 1, 'enviado', '2026-09-15 13:00:00', "
       "'2026-09-15 13:00:00', 0.5)")                                  # mês passado: não conta
    _x("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
       "VALUES ('l1', 1, 'whatsapp', 'cliente', 'oi', ?)", (_t(hours=-1),))
    _x("INSERT INTO agendamentos (lead_id, loja_id, nome_cliente, tipo, data_hora, criado_em) "
       "VALUES ('l1', 1, 'Ana', 'visita', '2026-11-02 10:00', ?)", (_t(minutes=-30),))
    _x("INSERT INTO reativacao (loja_id, contato_id, telefone, lote, meses_inativo, criado_por, "
       "lead_id, estado, enviado_em, custo_meta) VALUES (1, 1, '5581999998888', 'x', 6, 'S', "
       "'5581999998888', 'enviado', ?, 0.4)", (_t(hours=-3),))
    _x("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
       "VALUES ('558199998888', 1, 'whatsapp', 'cliente', 'opa', ?)", (_t(hours=-1),))   # sem o 9

    r = pe.resultado_do_mes(1, AGORA)
    assert r["remarketing"] == {"enviados": 1, "responderam": 1, "agendaram": 1, "custo": 0.5}
    assert r["reativacao"]["responderam"] == 1 and r["reativacao"]["agendaram"] == 0
    assert r["total"]["enviados"] == 2 and round(r["total"]["custo"], 2) == 0.9


def test_historico_junta_os_tipos_com_motivo_em_texto():
    _x("INSERT INTO remarketing_envios (loja_id, lead_id, canal, toque, estado, motivo_bloqueio, criado_em) "
       "VALUES (1, 'l1', 'whatsapp', 1, 'bloqueado', 'modelo_nao_aprovado', ?)", (_t(hours=-2),))
    _x("INSERT INTO reativacao (loja_id, contato_id, telefone, lote, meses_inativo, criado_por, "
       "estado, motivo, atualizado_em) VALUES (1, 1, '5581988887777', 'x', 6, 'S', 'cancelado', "
       "'nao_contatar', ?)", (_t(hours=-1),))
    h = pe.historico(1)
    assert [x["tipo"] for x in h] == ["reativacao", "remarketing"]
    assert h[1]["motivo"] == "Modelo ainda não aprovado pela Meta nesta loja"
    assert h[0]["motivo"] == "Pediu para não ser procurado"


def test_fila_mostra_a_reativacao_e_nao_mistura_lojas():
    loja_b = criar_loja("Loja B")
    _x("INSERT INTO reativacao (loja_id, contato_id, telefone, lote, meses_inativo, criado_por, estado) "
       "VALUES (1, 1, '5581999998888', 'x', 6, 'S', 'na_fila')")
    assert any(i["tipo"] == "reativacao" and i["lead_id"] == "5581999998888" for i in pe.fila(1, AGORA))
    assert pe.fila(loja_b, AGORA) == []


def test_modo_de_envio_le_o_env(monkeypatch):
    monkeypatch.setenv("POS_VENDA_ENVIO_REAL", "1")
    monkeypatch.setenv("REMARKETING_ENVIO_REAL", "0")
    monkeypatch.delenv("REATIVACAO_ENVIO_REAL", raising=False)
    assert pe.modo_de_envio() == {"remarketing": False, "pos_venda": True, "reativacao": False}


# ------------------------------------------------------------ tela

def test_tela_e_dos_dois_paineis_e_compila():
    assert "paginas/envios.py" in arquivos(CLIENTE)
    assert "paginas/envios.py" not in arquivos(OPERADOR)
    fonte = (RAIZ / "paginas/envios.py").read_text(encoding="utf-8")
    assert "papel_atual()" in fonte and "exigir_operador" not in fonte
    py_compile.compile(str(RAIZ / "paginas/envios.py"), doraise=True)


def test_dados_da_tela_nao_importam_o_operador_nem_os_jobs():
    fonte = (RAIZ / "app/painel_envios.py").read_text(encoding="utf-8")
    assert "app.custos" not in fonte and "app.precos" not in fonte and "app.jobs" not in fonte

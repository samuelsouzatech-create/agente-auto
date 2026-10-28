"""
Etapa 1, Bloco 7B: avisos no Telegram, alerta de gasto e relógio do sistema
(item 1.10), mais o teste final da Etapa 1 com duas lojas. Todos offline:
nenhum aviso sai de verdade (o envio é trocado por um falso).
"""
import json
import py_compile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import banco
from app import avisos, config, lojas, relogio
from app.custos import Uso, gasto_do_dia, registrar_uso
from app.handoff import assumir_handoff
from app.jobs import alertas, runner
from app.precos import cadastrar_preco
from app.usuarios import criar_usuario
from tools import acionar_handoff

RAIZ = Path(__file__).resolve().parent.parent
RECIFE = ZoneInfo("America/Recife")
LOJA_B = 42
VEND, GEST, OPER = "11111", "22222", "99999"
ENVIAR_REAL = avisos._enviar


def local(*args):
    return datetime(*args, tzinfo=RECIFE)


TERCA_15H = local(2026, 10, 27, 15, 0)          # terça, dentro do horário


def t(minutos, segundos=1):
    return TERCA_15H + timedelta(minutes=minutos, seconds=segundos)


# ---------------------------------------------------------------- apoio
def _executar(sql, parametros=()):
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


class TelegramFalso:
    def __init__(self):
        self.enviados = []
        self.falhar = False

    def __call__(self, chat_id, texto):
        if self.falhar:
            return False, "500 erro de teste"
        self.enviados.append((str(chat_id), texto))
        return True, None

    def para(self, chat):
        return [texto for c, texto in self.enviados if c == chat]


@pytest.fixture(autouse=True)
def telegram(monkeypatch):
    falso = TelegramFalso()
    monkeypatch.setattr(avisos, "_enviar", falso)
    monkeypatch.setattr(config, "TELEGRAM_AVISOS_OPERADOR_CHAT_ID", OPER)
    return falso


@pytest.fixture
def loja_b():
    _executar("INSERT INTO lojas (id, nome, segmento, config) VALUES (?, 'Auto Bia', 'veiculos', ?)",
              (LOJA_B, json.dumps({"nome_agente": "Bia"})))
    lojas.limpar_cache()
    yield LOJA_B
    lojas.limpar_cache()


def _equipe(loja_id=1, vendedor=VEND, gestor=GEST):
    if vendedor:
        criar_usuario(loja_id, "Carlos", "vendedor", vendedor)
    if gestor:
        criar_usuario(loja_id, "Gerente", "gestor", gestor)


def _handoff(loja_id, lead, criado, motivo="desconto"):
    _executar("INSERT INTO handoffs (loja_id, lead_id, motivo, resumo, estado, criado_em) "
              "VALUES (?, ?, ?, 'quer 48x', 'aguardando_humano', ?)",
              (loja_id, lead, motivo, relogio.para_banco(criado)))
    return _ler("SELECT id FROM handoffs WHERE loja_id = ? AND lead_id = ? ORDER BY id DESC",
                (loja_id, lead))[0]["id"]


def _handoff_linha(hid):
    return _ler("SELECT * FROM handoffs WHERE id = ?", (hid,))[0]


def _precos():
    cadastrar_preco("ia.entrada", 1.0, "2026-01-01", "USD")
    cadastrar_preco("ia.saida", 1.0, "2026-01-01", "USD")
    cadastrar_preco("cambio.usd_brl", 5.0, "2026-01-01")


def _gastar(loja_id, reais: int, quando):
    """R$ 5 por milhão de tokens: R$ 1 = 200 mil tokens (conta exata)."""
    registrar_uso(loja_id, "lead-x", "telegram", Uso(tokens_entrada=reais * 200_000), agora=quando)


def _teto(loja_id, valor):
    lojas.salvar_config(loja_id, {"custos.teto_diario_llm": valor}, "teste", papel="operador")


# ---------------------------------------------------------------- migração
def test_migracao_4():
    conexao = banco.conectar()
    try:
        assert banco.versao_schema(conexao) >= 4
        tabelas = {r["name"] for r in conexao.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conexao.close()
    assert "avisos" in tabelas


def test_migracao_4_nao_dispara_avisos_de_handoffs_antigos(telegram):
    _equipe()
    _executar("INSERT INTO handoffs (loja_id, lead_id, estado) VALUES (1, 'antigo', 'aguardando_humano')")
    conexao = banco.conectar()
    conexao.execute("PRAGMA user_version = 3")
    conexao.commit()
    conexao.close()
    banco.migrar()
    [h] = _ler("SELECT avisado_em, reavisado_em, gestor_avisado_em FROM handoffs WHERE lead_id = 'antigo'")
    assert all(h.values())
    alertas.verificar_handoffs()
    assert telegram.enviados == []


# ---------------------------------------------------------------- relógio
def test_relogio_horario_da_loja():
    l1 = lojas.carregar_loja(1)
    assert relogio.no_horario(l1, local(2026, 10, 27, 9, 0))
    assert not relogio.no_horario(l1, local(2026, 10, 27, 18, 0))
    assert not relogio.no_horario(l1, local(2026, 11, 1, 10, 0))      # domingo
    assert relogio.dia_local(l1, local(2026, 10, 27, 23, 30)) == date(2026, 10, 27)


# ---------------------------------------------------------------- handoff
def test_aviso_inicial_vai_para_o_vendedor_uma_vez(telegram):
    _equipe()
    _handoff(1, "lead-a", TERCA_15H)
    alertas.verificar_handoffs(t(0, 30))
    alertas.verificar_handoffs(t(0, 59))
    [msg] = telegram.para(VEND)
    assert "Loja 1" in msg and "desconto" in msg and "Assumir" in msg
    assert telegram.para(GEST) == []


def test_sem_vendedor_o_aviso_vai_ao_gestor(telegram):
    _equipe(vendedor=None)
    _handoff(1, "lead-a", TERCA_15H)
    alertas.verificar_handoffs(t(0, 30))
    assert len(telegram.para(GEST)) == 1


def test_sem_ninguem_cadastrado_nao_quebra_e_fica_registrado(telegram):
    hid = _handoff(1, "lead-a", TERCA_15H)
    alertas.verificar_handoffs(t(0, 30))
    assert telegram.enviados == []
    [a] = _ler("SELECT status FROM avisos WHERE tipo = 'handoff_aviso' AND referencia = ?",
               (f"handoff:{hid}",))
    assert a["status"] == "sem_destino"
    assert _handoff_linha(hid)["avisado_em"]


def test_reaviso_aos_5_e_gestor_aos_10(telegram):
    _equipe()
    _handoff(1, "lead-b", TERCA_15H)
    alertas.verificar_handoffs(t(0))
    alertas.verificar_handoffs(t(4))
    assert len(telegram.para(VEND)) == 1
    alertas.verificar_handoffs(t(5))
    assert len(telegram.para(VEND)) == 2 and "⏰" in telegram.para(VEND)[1]
    alertas.verificar_handoffs(t(9))
    assert telegram.para(GEST) == []
    alertas.verificar_handoffs(t(10))
    [msg] = telegram.para(GEST)
    assert "🚨" in msg
    alertas.verificar_handoffs(t(11))
    assert len(telegram.enviados) == 3


def test_assumir_para_os_avisos(telegram):
    _equipe()
    _handoff(1, "lead-c", TERCA_15H)
    alertas.verificar_handoffs(t(0))
    assumir_handoff("lead-c", "Carlos", loja_id=1)
    alertas.verificar_handoffs(t(20))
    assert len(telegram.para(VEND)) == 1 and telegram.para(GEST) == []


def test_tempos_vem_da_configuracao_da_loja(telegram):
    lojas.salvar_config(1, {"handoff.reaviso_min": 2, "handoff.gestor_min": 3}, "teste", papel="cliente")
    _equipe()
    _handoff(1, "lead-d", TERCA_15H)
    alertas.verificar_handoffs(t(2))
    assert len(telegram.para(VEND)) == 2
    alertas.verificar_handoffs(t(3))
    assert len(telegram.para(GEST)) == 1


def test_fora_do_horario_os_lembretes_esperam_a_loja_abrir(telegram):
    _equipe()
    criado = local(2026, 10, 27, 23, 0)
    _handoff(1, "lead-noite", criado)
    alertas.verificar_handoffs(criado + timedelta(minutes=1))
    [msg] = telegram.para(VEND)
    assert "Fora do horário" in msg
    alertas.verificar_handoffs(local(2026, 10, 28, 8, 30))
    alertas.verificar_handoffs(local(2026, 10, 28, 9, 4))
    assert len(telegram.para(VEND)) == 1 and telegram.para(GEST) == []
    alertas.verificar_handoffs(local(2026, 10, 28, 9, 5))
    assert len(telegram.para(VEND)) == 2
    alertas.verificar_handoffs(local(2026, 10, 28, 9, 10))
    assert len(telegram.para(GEST)) == 1


def test_falha_no_envio_tenta_de_novo_e_recupera(telegram):
    _equipe(gestor=None)
    hid = _handoff(1, "lead-e", TERCA_15H)
    telegram.falhar = True
    alertas.verificar_handoffs(t(0, 10))
    assert _handoff_linha(hid)["avisado_em"] is None
    telegram.falhar = False
    alertas.verificar_handoffs(t(0, 40))
    assert len(telegram.para(VEND)) == 1
    [a] = _ler("SELECT status, tentativas FROM avisos WHERE tipo = 'handoff_aviso'")
    assert a == {"status": "enviado", "tentativas": 2}


def test_falha_persistente_para_em_3_tentativas(telegram):
    _equipe(gestor=None)
    hid = _handoff(1, "lead-f", TERCA_15H)
    telegram.falhar = True
    for segundos in (10, 40, 70, 100):
        alertas.verificar_handoffs(t(0, segundos))
    [a] = _ler("SELECT status, tentativas FROM avisos WHERE tipo = 'handoff_aviso'")
    assert a == {"status": "falhou", "tentativas": 3}
    assert _handoff_linha(hid)["avisado_em"]


def test_acionar_handoff_de_verdade_gera_aviso(telegram):
    _equipe()
    acionar_handoff.func(motivo="pediu vendedor", resumo="r", lead_id="5599", loja_id=1)
    alertas.verificar_handoffs(relogio.agora_utc() + timedelta(seconds=5))
    assert len(telegram.para(VEND)) == 1


# ---------------------------------------------------------------- gasto
def test_sem_teto_nao_avisa(telegram):
    _precos()
    _gastar(1, 50, TERCA_15H)
    alertas.verificar_gastos(TERCA_15H)
    assert telegram.para(OPER) == []


def test_alerta_de_gasto_em_80_e_100_uma_vez_cada(telegram):
    _precos()
    _teto(1, 10.0)
    _gastar(1, 7, TERCA_15H)
    alertas.verificar_gastos(TERCA_15H)
    assert telegram.para(OPER) == []
    _gastar(1, 2, TERCA_15H)                      # 9 de 10
    alertas.verificar_gastos(TERCA_15H)
    assert "80%" in telegram.para(OPER)[0]
    _gastar(1, 2, TERCA_15H)                      # 11 de 10
    alertas.verificar_gastos(TERCA_15H)
    alertas.verificar_gastos(TERCA_15H)
    msgs = telegram.para(OPER)
    assert len(msgs) == 2 and "passou do teto" in msgs[1]


def test_dia_do_gasto_vira_a_meia_noite_da_loja(telegram):
    _precos()
    _teto(1, 10.0)
    _gastar(1, 12, local(2026, 10, 27, 23, 30))   # em UTC já é dia 28
    assert gasto_do_dia(1, date(2026, 10, 27), fuso="America/Recife") == 12.0
    assert gasto_do_dia(1, date(2026, 10, 28), fuso="America/Recife") == 0.0
    alertas.verificar_gastos(local(2026, 10, 27, 23, 45))
    alertas.verificar_gastos(local(2026, 10, 28, 0, 10))
    assert len(telegram.para(OPER)) == 1


def test_sem_chat_do_operador_nao_quebra(monkeypatch, telegram):
    monkeypatch.setattr(config, "TELEGRAM_AVISOS_OPERADOR_CHAT_ID", "")
    _precos()
    _teto(1, 10.0)
    _gastar(1, 12, TERCA_15H)
    alertas.verificar_gastos(TERCA_15H)
    assert telegram.enviados == []
    [a] = _ler("SELECT status FROM avisos WHERE tipo = 'gasto_100'")
    assert a["status"] == "sem_destino"


# ---------------------------------------------------------------- envio real
def test_erro_de_rede_nao_mostra_o_token(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_AVISOS_TOKEN", "123:SEGREDO")

    def explode(url, **kwargs):
        raise RuntimeError(f"falhou em {url}")
    monkeypatch.setattr(avisos.httpx, "post", explode)
    ok, erro = ENVIAR_REAL(VEND, "oi")
    assert not ok and "SEGREDO" not in erro


def test_sem_token_falha_com_mensagem_clara(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_AVISOS_TOKEN", "")
    ok, erro = ENVIAR_REAL(VEND, "oi")
    assert not ok and "TELEGRAM_AVISOS_TOKEN" in erro


# ---------------------------------------------------------------- final da Etapa 1
def test_etapa1_final_duas_lojas_cada_uma_com_seus_avisos(loja_b, telegram):
    _equipe(1, VEND, GEST)
    _equipe(LOJA_B, "33333", "44444")
    lojas.salvar_config(LOJA_B, {"handoff.reaviso_min": 3}, "teste", papel="cliente")
    _handoff(1, "5581", TERCA_15H, motivo="desconto no Civic")
    _handoff(LOJA_B, "5581", TERCA_15H, motivo="aprovar crédito")   # mesmo telefone, outra loja

    alertas.verificar_handoffs(t(0, 5))
    assert "Loja 1" in telegram.para(VEND)[0] and "desconto no Civic" in telegram.para(VEND)[0]
    assert "Auto Bia" in telegram.para("33333")[0] and "aprovar crédito" in telegram.para("33333")[0]

    assumir_handoff("5581", "Carlos", loja_id=1)     # assumir na loja 1 não mexe na loja B
    alertas.verificar_handoffs(t(3))
    assert len(telegram.para(VEND)) == 1 and len(telegram.para("33333")) == 2
    alertas.verificar_handoffs(t(10))
    assert telegram.para(GEST) == [] and len(telegram.para("44444")) == 1

    assert all("Auto Bia" not in m for m in telegram.para(VEND) + telegram.para(GEST))
    assert all("Loja 1" not in m for m in telegram.para("33333") + telegram.para("44444"))

    _precos()
    _teto(1, 10.0)
    _teto(LOJA_B, 10.0)
    _gastar(1, 12, TERCA_15H)
    alertas.verificar_gastos(TERCA_15H)
    [msg] = telegram.para(OPER)
    assert "Loja 1" in msg


# ---------------------------------------------------------------- runner e páginas
def test_rodar_ciclo_e_runner():
    assert set(alertas.rodar_ciclo(TERCA_15H)) == {"handoffs", "gastos"}
    assert runner.main(["--uma-vez"]) == 0


def test_arquivos_compilam():
    for arquivo in ("app/jobs/runner.py", "app/jobs/alertas.py", "paginas/custos.py"):
        py_compile.compile(str(RAIZ / arquivo), doraise=True)

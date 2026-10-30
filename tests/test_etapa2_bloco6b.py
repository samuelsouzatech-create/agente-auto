"""
Testes da Etapa 2, Bloco 6B: pós-venda dos compradores importados.
Só futuro, só com autorização, sem duplicar, número da conversa do WhatsApp,
modelo aprovado obrigatório, desfazer limpa a régua, handoff sem "em instantes".
"""
import py_compile
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from banco import conectar
from app import regua
from app.base_pos_venda import BaseNaoAgendada, agendar_base, lead_da_base, resumo
from app.importacao import desfazer_importacao, importar, ler_planilha
from app.jobs.pos_venda import rodar_pos_venda
from app.lojas import salvar_config
from tools import acionar_handoff

RAIZ = Path(__file__).resolve().parent.parent
HOJE = date(2026, 10, 30)
AGORA = datetime(2026, 10, 30, 13, 0, tzinfo=timezone.utc)   # sexta, 10h no Recife
ANA, BRUNO = "5581999998888", "5581988887777"
CSV = (
    "nome;telefone;carro;data_compra;pagamento\n"
    "Ana Souza;(81) 99999-8888;Honda Civic 2019;29/10/2026;à vista\n"
    "Bruno Reis;(81) 98888-7777;Fiat Uno 2015;10/01/2024;à vista\n"
)


class EnviadorFalso:
    def __init__(self):
        self.chamadas = []

    async def texto(self, *args):
        self.chamadas.append(("texto", args))
        return SimpleNamespace(ok=True, detalhe="")

    async def modelo(self, *args):
        self.chamadas.append(("modelo", args))
        return SimpleNamespace(ok=True, detalhe="")


def _ligar():
    salvar_config(1, {"modulos.pos_venda": True}, "Samuel")


def _importar(texto=CSV, consentimento=True):
    return importar(1, ler_planilha(texto.encode("utf-8"), hoje=HOJE), usuario="Samuel",
                    consentimento=consentimento, arquivo="base.csv")


def _execucoes(lead_id):
    return regua.execucoes_do_lead(1, lead_id)


def _agendados(lead_id):
    return [e for e in _execucoes(lead_id) if e["estado"] == "agendado"]


def _passo(lead_id, nome):
    return next(e for e in _execucoes(lead_id) if e["passo_nome"] == nome)


# ------------------------------------------------------------ agendar

def test_compra_recente_agenda_e_antiga_nao_manda_nada():
    _ligar()
    _importar()
    r = agendar_base(1, agora=AGORA)
    assert r["compras"] == 2 and r["agendados"] >= 1 and r["ja_passaram"] >= 1
    assert _agendados(ANA)[0]["passo_nome"] == "agradecimento"
    assert _execucoes(BRUNO) and _agendados(BRUNO) == []


def test_agendar_de_novo_nao_duplica():
    _ligar()
    _importar()
    agendar_base(1, agora=AGORA)
    antes = len(_execucoes(ANA))
    assert agendar_base(1, agora=AGORA)["compras"] == 0
    assert len(_execucoes(ANA)) == antes


def test_sem_autorizacao_nao_entra_na_regua():
    _ligar()
    _importar(consentimento=False)
    assert agendar_base(1, agora=AGORA)["compras"] == 0
    assert _execucoes(ANA) == []


def test_modulo_desligado_recusa():
    _importar()
    with pytest.raises(BaseNaoAgendada):
        agendar_base(1, agora=AGORA)


def test_usa_o_numero_da_conversa_do_whatsapp():
    c = conectar()
    try:
        c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo, criado_em) "
                  "VALUES ('558199998888', 1, 'whatsapp', 'cliente', 'texto', 'oi', '2026-10-01 12:00:00')")
        c.commit()
    finally:
        c.close()
    assert lead_da_base(1, ANA) == "558199998888"
    _ligar()
    _importar()
    agendar_base(1, agora=AGORA)
    assert _execucoes("558199998888") and _execucoes(ANA) == []


def test_mesma_compra_do_botao_vendido_nao_duplica():
    c = conectar()
    try:
        carro = c.execute(
            "INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) "
            "VALUES (1, 'Honda', 'Civic', 2019, 48000, 'Branco', 'Automático', 98000, 'vendido')").lastrowid
        c.execute("INSERT INTO vendas (loja_id, lead_id, veiculo_id, data_venda, forma_pagamento) "
                  "VALUES (1, ?, ?, '2026-10-29', 'avista')", (ANA, carro))
        c.commit()
    finally:
        c.close()
    _ligar()
    _importar()
    assert agendar_base(1, agora=AGORA)["compras"] == 1      # só o Bruno


def test_resumo_da_tela():
    _ligar()
    _importar()
    assert resumo(1) == {"pendentes": 2, "agendados": 0}
    agendar_base(1, agora=AGORA)
    r = resumo(1)
    assert r["pendentes"] == 0 and r["agendados"] >= 1


# ------------------------------------------------------------ job

def test_job_simula_para_comprador_importado():
    _ligar()
    _importar()
    agendar_base(1, agora=AGORA)
    t = rodar_pos_venda(AGORA, envio_real=False, enviador=EnviadorFalso(), lojas=[1])
    assert t["simulado"] == 1 and t["erro"] == 0


def test_envio_real_sem_modelo_aprovado_nao_envia():
    _ligar()
    _importar()
    agendar_base(1, agora=AGORA)
    enviador = EnviadorFalso()
    t = rodar_pos_venda(AGORA, envio_real=True, enviador=enviador, lojas=[1])
    assert t["bloqueado"] == 1 and enviador.chamadas == []
    passo = _passo(ANA, "agradecimento")
    assert (passo["estado"], passo["motivo"]) == ("bloqueado", "modelo_nao_aprovado")


def test_sem_nome_bloqueia():
    _ligar()
    _importar("telefone;carro;data_compra\n81999998888;Honda Civic 2019;29/10/2026\n")
    agendar_base(1, agora=AGORA)
    t = rodar_pos_venda(AGORA, envio_real=False, enviador=EnviadorFalso(), lojas=[1])
    assert t["bloqueado"] == 1 and t["simulado"] == 0


def test_job_cancela_se_a_compra_sumiu():
    _ligar()
    _importar()
    agendar_base(1, agora=AGORA)
    c = conectar()
    try:
        c.execute("DELETE FROM compras_anteriores WHERE loja_id = 1")
        c.commit()
    finally:
        c.close()
    t = rodar_pos_venda(AGORA, envio_real=False, enviador=EnviadorFalso(), lojas=[1])
    assert t["cancelado"] == 1
    assert _passo(ANA, "agradecimento")["motivo"] == "importacao_desfeita"


def test_desfazer_cancela_o_que_estava_agendado():
    _ligar()
    imp = _importar()
    agendar_base(1, agora=AGORA)
    desfazer_importacao(1, imp["importacao_id"])
    assert _agendados(ANA) == []
    assert _passo(ANA, "agradecimento")["motivo"] == "importacao_desfeita"


# ------------------------------------------------------------ handoff e tela

def test_handoff_nao_promete_em_instantes():
    r1 = acionar_handoff.invoke({"motivo": "x", "resumo": "y", "lead_id": "l1", "loja_id": 1})
    r2 = acionar_handoff.invoke({"motivo": "x", "resumo": "z", "lead_id": "l1", "loja_id": 1})
    assert r1.startswith("Handoff acionado") and r2.startswith("Handoff atualizado")
    assert "em instantes" not in r1 + r2


def test_tela_tem_o_botao_e_compila():
    fonte = (RAIZ / "paginas/importar_base.py").read_text(encoding="utf-8")
    assert "agendar_base" in fonte
    py_compile.compile(str(RAIZ / "paginas/importar_base.py"), doraise=True)

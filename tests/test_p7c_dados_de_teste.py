"""
P7c do Plano Mestre: dados do período de teste fora dos números.
- Resultado: loja que entrou no ar pelo botão conta só depois de no_ar_em;
  loja em teste mostra os números com aviso; loja antiga conta tudo;
- venda do teste não conta; chamado e visita do teste também não;
- nada é apagado;
- Custos: implantação separada, total do mês igual;
- áudio de quem não é número de teste nem é transcrito (WhatsApp e Telegram).
Tudo offline, banco temporário do conftest (ator "Teste", operador, painel).
"""
import asyncio
import importlib
import os
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from banco import conectar
from app.custos import resumo_implantacao, resumo_mes
from app.estado_loja import cadastrar_numero_de_teste, colocar_no_ar, inicio_da_contagem
from app.lojas import criar_loja
from app.painel_leitura import resultado_do_periodo

NO_AR = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)      # 09:00 em Recife
HOJE = date(2026, 11, 3)
EVENTO = "mensagem_recusada_loja_em_teste"


def importar(nome):
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.setdefault("GOOGLE_API_KEY", "chave-falsa-so-para-importar")
    return importlib.import_module(nome)


def _sql(comando, valores=()):
    conexao = conectar()
    try:
        conexao.execute(comando, valores)
        conexao.commit()
    finally:
        conexao.close()


def _um(sql, parametros=()):
    conexao = conectar()
    try:
        return conexao.execute(sql, parametros).fetchone()[0]
    finally:
        conexao.close()


def _msg(loja_id, lead_id, quando, direcao="cliente"):
    _sql("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
         "VALUES (?, ?, 'whatsapp', ?, 'oi', ?)", (lead_id, loja_id, direcao, quando))


def _venda(loja_id, lead_id, data_venda, criado_em):
    _sql("INSERT INTO vendas (loja_id, lead_id, veiculo_id, data_venda, forma_pagamento, criado_em) "
         "VALUES (?, ?, 1, ?, 'avista', ?)", (loja_id, lead_id, data_venda, criado_em))


def _custo(loja_id, criado_em, valor):
    _sql("INSERT INTO uso_custos (loja_id, lead_id, canal, execucao_id, criado_em, "
         "custo_llm, custo_meta, custo_completo) VALUES (?, 'x', 'whatsapp', ?, ?, ?, 0, 1)",
         (loja_id, uuid.uuid4().hex, criado_em, valor))


def _recusas(loja_id):
    return _um("SELECT COUNT(*) FROM registro_acoes WHERE acao = ? AND loja_id = ?",
               (EVENTO, loja_id))


# ------------------------------------------------------------ resultado

def test_loja_que_ja_existia_conta_tudo():
    assert inicio_da_contagem(1) is None
    _msg(1, "5581911110001", "2026-10-01 15:00:00")
    r = resultado_do_periodo(1, date(2026, 10, 1), date(2026, 10, 31))
    assert r["conversas_atendidas"] == 1
    assert r["dados_de_teste"] is False and r["contando_desde"] is None


def test_loja_em_teste_mostra_os_numeros_com_aviso():
    loja2 = criar_loja("Loja 2")
    _msg(loja2, "5581911110001", "2026-11-03 11:00:00")
    r = resultado_do_periodo(loja2, HOJE, HOJE)
    assert r["conversas_atendidas"] == 1
    assert r["dados_de_teste"] is True and r["contando_desde"] is None


def test_depois_de_ir_ao_ar_o_resultado_ignora_o_teste():
    loja2 = criar_loja("Loja 2")
    _msg(loja2, "5581911110001", "2026-11-02 15:00:00")   # teste, dia anterior
    _msg(loja2, "5581911110002", "2026-11-03 11:00:00")   # teste, 08:00 do mesmo dia
    colocar_no_ar(loja2, agora=NO_AR)
    _msg(loja2, "5581911110003", "2026-11-03 12:30:00")   # cliente de verdade
    assert inicio_da_contagem(loja2) == "2026-11-03 12:00:00"
    r = resultado_do_periodo(loja2, date(2026, 11, 1), HOJE)
    assert r["conversas_atendidas"] == 1
    assert r["dados_de_teste"] is False
    assert r["contando_desde"] == "2026-11-03 12:00:00"
    assert sum(d["no_horario"] + d["fora_do_horario"] for d in r["por_dia"]) == 1
    assert _um("SELECT COUNT(*) FROM mensagens WHERE loja_id = ?", (loja2,)) == 3   # nada apagado


def test_periodo_todo_antes_de_ir_ao_ar_fica_zerado():
    loja2 = criar_loja("Loja 2")
    _msg(loja2, "5581911110001", "2026-11-02 15:00:00")
    colocar_no_ar(loja2, agora=NO_AR)
    r = resultado_do_periodo(loja2, date(2026, 11, 2), date(2026, 11, 2))
    assert r["conversas_atendidas"] == 0


def test_venda_do_periodo_de_teste_nao_conta():
    loja2 = criar_loja("Loja 2")
    _venda(loja2, "5581911110001", "2026-11-03", "2026-11-03 11:00:00")   # registrada no teste
    colocar_no_ar(loja2, agora=NO_AR)
    _venda(loja2, "5581911110002", "2026-11-03", "2026-11-03 12:30:00")   # de verdade
    _venda(loja2, "5581911110003", "2026-11-02", "2026-11-03 12:40:00")   # data antes do ar
    assert resultado_do_periodo(loja2, date(2026, 11, 1), HOJE)["vendas_registradas"] == 1


def test_chamado_e_visita_do_teste_nao_contam():
    loja2 = criar_loja("Loja 2")
    _sql("INSERT INTO handoffs (loja_id, lead_id, motivo, estado, criado_em, origem) "
         "VALUES (?, '5581911110001', 'x', 'aguardando_humano', '2026-11-03 11:00:00', 'leo')",
         (loja2,))
    _sql("INSERT INTO agendamentos (loja_id, lead_id, nome_cliente, tipo, data_hora, criado_em) "
         "VALUES (?, '5581911110001', 'Ana', 'visita', 'sábado', '2026-11-03 11:10:00')",
         (loja2,))
    colocar_no_ar(loja2, agora=NO_AR)
    r = resultado_do_periodo(loja2, HOJE, HOJE)
    assert r["passados_ao_vendedor"] == 0 and r["visitas_marcadas"] == 0


def test_sem_passar_pelo_botao_nao_ha_corte():
    loja2 = criar_loja("Loja 2")
    _sql("INSERT INTO estado_lojas (loja_id, estado, no_ar_em, alterado_por) "
         "VALUES (?, 'no_ar', '2026-11-03 12:00:00', 'Teste')", (loja2,))
    assert inicio_da_contagem(loja2) is None


# ------------------------------------------------------------ custos

def test_custo_da_loja_em_teste_e_todo_implantacao():
    loja2 = criar_loja("Loja 2")
    _custo(loja2, "2026-11-03 10:00:00", 0.5)
    _custo(loja2, "2026-11-03 11:00:00", 0.25)
    imp = resumo_implantacao(loja2)
    assert imp["em_teste"] is True and imp["ate"] is None
    assert imp["custo_total"] == pytest.approx(0.75)


def test_depois_do_ar_implantacao_fica_separada_e_o_total_nao_muda():
    loja2 = criar_loja("Loja 2")
    _custo(loja2, "2026-11-03 10:00:00", 0.5)
    colocar_no_ar(loja2, agora=NO_AR)
    _custo(loja2, "2026-11-03 12:30:00", 2.0)
    imp = resumo_implantacao(loja2)
    assert imp["em_teste"] is False and imp["ate"] == "2026-11-03 12:00:00"
    assert imp["custo_total"] == pytest.approx(0.5)
    assert resumo_mes(loja2, 2026, 11)["custo_total"] == pytest.approx(2.5)


def test_loja_que_ja_existia_nao_tem_implantacao():
    _custo(1, "2026-10-01 10:00:00", 1.0)
    assert resumo_implantacao(1) == {"em_teste": False, "ate": None, "conversas": 0,
                                     "custo_ia": 0.0, "custo_meta": 0.0, "custo_total": 0.0}


# ------------------------------------------------------------ áudio

def test_whatsapp_audio_de_quem_nao_e_teste_nem_e_transcrito(monkeypatch):
    wh = importar("app.api.webhook")
    loja2 = criar_loja("Loja 2")
    chamadas = []

    async def transcrever(id_audio, **kw):
        chamadas.append(id_audio)
        return "oi"

    monkeypatch.setattr(wh, "transcrever_audio", transcrever)
    asyncio.run(wh.processar_mensagem("5581999990000", None, "A1", loja2))
    assert chamadas == []
    assert _um("SELECT COUNT(*) FROM uso_custos WHERE loja_id = ?", (loja2,)) == 0
    assert _recusas(loja2) == 1


def test_whatsapp_audio_do_numero_de_teste_e_transcrito(monkeypatch):
    wh = importar("app.api.webhook")
    loja2 = criar_loja("Loja 2")
    cadastrar_numero_de_teste(loja2, "whatsapp", "5581999990000")
    chamadas, enviadas = [], []

    async def transcrever(id_audio, **kw):
        chamadas.append(id_audio)
        return ""                                    # não entendeu

    async def resposta(numero, texto, atraso=0, **kw):
        enviadas.append(texto)

    monkeypatch.setattr(wh, "transcrever_audio", transcrever)
    monkeypatch.setattr(wh, "pegar_uso_da_transcricao", lambda id_audio: None)
    monkeypatch.setattr(wh, "enviar_resposta_humanizada", resposta)
    asyncio.run(wh.processar_mensagem("5581999990000", None, "A1", loja2))
    assert chamadas == ["A1"]
    assert len(enviadas) == 1                        # "não consegui entender o áudio"
    assert _recusas(loja2) == 0


def test_telegram_audio_de_quem_nao_e_teste_nem_e_baixado(monkeypatch):
    tb = importar("app.api.telegram_bot")
    loja2 = criar_loja("Loja 2")
    monkeypatch.setattr(tb, "LOJA_DO_BOT", loja2)
    baixados = []

    class CanalFalso:
        async def baixar_midia(self, entrada):
            baixados.append(entrada.lead_id)
            return b"x"

        async def enviar_texto(self, chat_id, texto):
            pass

    asyncio.run(tb._responder_audio(CanalFalso(), SimpleNamespace(lead_id="777", mime="audio/ogg")))
    assert baixados == []
    assert _recusas(loja2) == 1

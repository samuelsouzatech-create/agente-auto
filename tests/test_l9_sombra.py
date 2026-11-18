"""
L9: modo sombra. OFFLINE, LLM falso, duas lojas (A em sombra, B normal).
Prova ZERO envio em todos os caminhos (turno, resposta fixa, mídia, áudio, foto,
remarketing, pós-venda, reativação), nenhuma ferramenta que grava executa, a sugestão
fica guardada (só texto), some depois de 30 dias e uma loja nunca vê a outra.
"""
import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from app import lojas, sombra

LOJA_A, LOJA_B = 1, 2
LEAD = "5581944443333"


def _sql(sql, parametros=()):
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


def _config(loja_id, config):
    texto = json.dumps(config)
    if _ler("SELECT id FROM lojas WHERE id = ?", (loja_id,)):
        _sql("UPDATE lojas SET config = ? WHERE id = ?", (texto, loja_id))
    else:
        _sql("INSERT INTO lojas (id, nome, segmento, config) VALUES (?, ?, 'veiculos', ?)",
             (loja_id, f"Loja {loja_id}", texto))
    lojas.limpar_cache()


@pytest.fixture
def duas_lojas():
    ligados = {"modulos": {"remarketing": True, "pos_venda": True}, "remarketing": {"limite_mensal": 100}}
    _config(LOJA_A, {"modo_sombra": True, **ligados})
    _config(LOJA_B, dict(ligados))


class GrafoFalso:
    def __init__(self, resposta="Temos o Civic! Quer ver fotos?", ferramentas=()):
        self.resposta = resposta
        self.ferramentas = ferramentas
        self.entradas = []

    def invoke(self, entrada, config=None):
        self.entradas.append(entrada)
        chamadas = [AIMessage(content="", tool_calls=[{"name": n, "args": {}, "id": f"t{i}"}])
                    for i, n in enumerate(self.ferramentas)]
        return {"messages": [HumanMessage(content=entrada["messages"][0].content), *chamadas,
                             AIMessage(content=self.resposta)]}


def _turno(loja_id, texto, grafo=None, lead=LEAD):
    from app.core.turno import executar_turno
    return asyncio.run(executar_turno(loja_id, "simulador", lead, texto, grafo=grafo or GrafoFalso()))


# ------------------------------------------------------------ cadastro e migração

def test_modo_sombra_desligado_por_padrao_e_so_do_operador():
    from app.config_tela import CAMPOS
    assert lojas.PADROES["modo_sombra"] is False
    assert "modo_sombra" in lojas.CHAVES_DO_OPERADOR
    campo = next(c for c in CAMPOS if c.chave == "modo_sombra")
    assert campo.tipo == "sim_nao" and campo.dono == "operador"
    with pytest.raises(ValueError):
        lojas.EDITAVEIS["modo_sombra"]("sim")


def test_migracao_20_e_aditiva_e_roda_de_novo():
    assert 20 in banco.MIGRACOES and banco.VERSAO_SCHEMA == 20
    colunas = {l["name"] for l in _ler("PRAGMA table_info(sombra_sugestoes)")}
    assert {"loja_id", "lead_id", "mensagem_cliente", "sugestao", "ferramentas", "criado_em"} <= colunas
    _config(LOJA_A, {})
    sombra.gravar(LOJA_A, LEAD, "simulador", "oi", "Oi!", [])
    _sql("PRAGMA user_version = 19")
    banco.migrar()
    assert _ler("PRAGMA user_version")[0]["user_version"] == 20
    assert len(_ler("SELECT id FROM sombra_sugestoes")) == 1


# ------------------------------------------------------------ turno: nada sai, nada grava

def test_loja_em_sombra_nao_envia_e_guarda_a_sugestao(duas_lojas):
    grafo = GrafoFalso(ferramentas=["consultar_estoque", "acionar_handoff"])
    r = _turno(LOJA_A, "tem civic?", grafo)
    assert r.silenciado and r.texto is None and r.midias == []
    assert grafo.entradas[0]["sombra"] is True
    [s] = _ler("SELECT * FROM sombra_sugestoes")
    assert (s["loja_id"], s["mensagem_cliente"], s["sugestao"]) == (LOJA_A, "tem civic?", "Temos o Civic! Quer ver fotos?")
    assert json.loads(s["ferramentas"]) == ["acionar_handoff", "consultar_estoque"]
    assert _ler("SELECT id FROM mensagens") == [] and _ler("SELECT id FROM handoffs") == []


def test_guardas_de_texto_valem_na_sugestao_mas_nada_grava(duas_lojas):
    r = _turno(LOJA_A, "me manda o pix pra reservar", GrafoFalso("Claro! Nossa chave pix é o CNPJ 12.345.678/0001-90."))
    assert r.silenciado
    [s] = _ler("SELECT sugestao FROM sombra_sugestoes")
    assert "chave pix" not in s["sugestao"].lower()
    assert _ler("SELECT id FROM handoffs") == []             # o pedido de pix não abre chamado em sombra


def test_loja_normal_continua_igual(duas_lojas):
    r = _turno(LOJA_B, "tem civic?")
    assert not r.silenciado and r.texto == "Temos o Civic! Quer ver fotos?"
    assert _ler("SELECT id FROM sombra_sugestoes") == []
    assert len(_ler("SELECT id FROM mensagens WHERE loja_id = 2")) == 2


def test_ferramenta_que_grava_nao_executa_em_sombra(duas_lojas):
    from app.core.agent import no_ferramentas
    chamada = AIMessage(content="", tool_calls=[
        {"name": "acionar_handoff", "args": {"motivo": "m", "resumo": "r"}, "id": "h1"},
        {"name": "registrar_troca", "args": {"modelo": "Gol", "ano": 2015, "km": 0, "estado": ""}, "id": "t1"}])
    saida = no_ferramentas({"messages": [chamada], "lead_id": LEAD, "loja_id": LOJA_A, "canal": "simulador",
                            "equipe": {}, "sombra": True})
    assert all(m.content == sombra.RESPOSTA_DA_FERRAMENTA for m in saida["messages"])
    assert _ler("SELECT id FROM handoffs") == [] and _ler("SELECT id FROM trocas") == []


def test_resposta_fixa_midia_e_audio_em_sombra_nao_saem(duas_lojas):
    from app.core.turno import turno_audio_falhou, turno_midia_nao_suportada
    assert turno_midia_nao_suportada(LOJA_A, "whatsapp", LEAD, "sticker").silenciado
    assert turno_audio_falhou(LOJA_A, "whatsapp", LEAD).silenciado
    assert len(_ler("SELECT id FROM sombra_sugestoes WHERE loja_id = 1")) == 2
    assert _ler("SELECT id FROM mensagens") == []


def test_foto_em_sombra_nao_e_lida_nem_guardada(duas_lojas):
    from app.core.turno import executar_turno_imagem
    lidas = []
    r = asyncio.run(executar_turno_imagem(LOJA_A, "simulador", LEAD, b"BYTES", "image/png", "olha", grafo=GrafoFalso(),
                                          leitor=lambda i, m: lidas.append(1)))
    assert r.silenciado and lidas == []
    assert "BYTES" not in str(_ler("SELECT * FROM sombra_sugestoes"))


# ------------------------------------------------------------ jobs: nada sai

def test_jobs_pulam_a_loja_em_sombra(duas_lojas, monkeypatch):
    from app.jobs import pos_venda, reativacao, remarketing
    vistos = []
    monkeypatch.setattr(remarketing, "elegiveis", lambda loja_id, agora: vistos.append(("rmk", loja_id)) or [])
    monkeypatch.setattr(pos_venda.regua, "vencidas", lambda loja_id, agora, limite: vistos.append(("pv", loja_id)) or [])
    monkeypatch.setattr(reativacao, "no_horario_de_envio", lambda loja, agora: vistos.append(("rea", loja.id)) or False)
    agora = datetime(2026, 11, 23, 13, 0, tzinfo=timezone.utc)
    remarketing.rodar_remarketing(agora, envio_real=True, pausa_s=0, lojas=[LOJA_A, LOJA_B])
    pos_venda.rodar_pos_venda(agora, envio_real=True, lojas=[LOJA_A, LOJA_B])
    reativacao.rodar_reativacao(agora, envio_real=True, lojas=[LOJA_A, LOJA_B])
    assert all(loja == LOJA_B for _, loja in vistos) and {t for t, _ in vistos} >= {"rmk", "pv"}


def test_envio_real_nunca_em_sombra(duas_lojas):
    from app.modo_envio import real_para
    _sql("INSERT OR REPLACE INTO estado_lojas (loja_id, estado) VALUES (1, 'no_ar'), (2, 'no_ar')")
    assert real_para(lojas.carregar_loja(LOJA_A), "remarketing", True) is False
    assert real_para(lojas.carregar_loja(LOJA_B), "remarketing", True) is True


# ------------------------------------------------------------ guarda e relatório

def test_sugestoes_somem_depois_de_30_dias_so_da_propria_loja(duas_lojas):
    velho = datetime(2026, 10, 1, tzinfo=timezone.utc)
    sombra.gravar(LOJA_A, LEAD, "simulador", "antiga A", "x", [], agora=velho)
    sombra.gravar(LOJA_B, LEAD, "simulador", "antiga B", "x", [], agora=velho)
    sombra.gravar(LOJA_A, LEAD, "simulador", "nova A", "x", [], agora=velho + timedelta(days=31))
    assert {l["mensagem_cliente"] for l in _ler("SELECT mensagem_cliente FROM sombra_sugestoes")} == {"nova A", "antiga B"}


def test_relatorio_do_dia_so_da_loja_pedida(duas_lojas):
    from scripts.relatorio_sombra import montar
    _turno(LOJA_A, "tem civic?")
    _sql("INSERT INTO mensagens (lead_id, loja_id, direcao, conteudo, canal) "
         "VALUES (?, 1, 'vendedor', 'Tenho sim, R$ 98 mil.', 'simulador')", (LEAD,))
    sombra.gravar(LOJA_B, "5581900001111", "simulador", "segredo da loja B", "x", [])
    from app.relogio import agora_utc, dia_local
    hoje = dia_local(lojas.carregar_loja(LOJA_A), agora_utc())
    texto = montar(LOJA_A, hoje)
    assert "tem civic?" in texto and "Temos o Civic!" in texto and "Tenho sim" in texto
    assert "…3333" in texto and LEAD not in texto
    assert "segredo da loja B" not in texto


def test_relatorio_exige_loja():
    from scripts.relatorio_sombra import main
    with pytest.raises(SystemExit):
        main([])


# ------------------------------------------------------------ bancada

def test_roteiro_49_offline(monkeypatch, tmp_path):
    from scripts import rodar_bancada as rb
    monkeypatch.setattr(rb, "_PASTA_TEMP", tmp_path / "bancada")
    (tmp_path / "bancada").mkdir()
    [roteiro] = [r for r in rb.carregar_roteiros() if r["nome"] == "loja_em_sombra"]
    rodada = asyncio.run(rb.rodar([roteiro], GrafoFalso(ferramentas=["acionar_handoff"]), teto=1.0))
    res = rodada.resultados[0]
    assert res.status == rb.PASSOU, (res.falhas, res.promessas)
    assert res.sugestoes_sombra == 3 and sum(len(t.bolhas) for t in res.turnos) == 0

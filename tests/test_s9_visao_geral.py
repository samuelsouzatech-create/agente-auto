"""
S9 (Fase 3): Visão geral e saúde do sistema.
- Redis fora: Redis vermelho e o resto "desconhecido", nunca verde (7A);
- relógio: verde, amarelo, vermelho e "parado" na hora; o runner grava (1A);
- receber mensagens pela tabela mensagens, sem o simulador (2A);
- IA: média e erros da última hora (4A);
- cliente esperando conta só o expediente (6A); limite 80/100 (3A);
- canal parado e "poucos dados" (5A); recusada só em teste; sem venda = Resumo;
- consultas não crescem com as lojas; cache por loja; saúde na hora (10A);
- a tela abre e não fala com o banco.
Tudo offline: banco temporário do conftest e Redis falso (fakeredis).
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fakeredis
import pytest
from streamlit.testing.v1 import AppTest

from banco import conectar
from app import alertas_config as cfg
from app import resumo_loja
from app import visao_geral as vg
from app.elegibilidade import enviados_no_mes
from app.jobs import batimento
from app.lojas import criar_loja, salvar_config
from app.relogio import para_banco

RAIZ = Path(__file__).resolve().parent.parent
TELA = RAIZ / "paginas" / "operador" / "visao_geral.py"
UTC = timezone.utc
AGORA = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)          # quinta, 12h no Recife


@pytest.fixture(autouse=True)
def cache_limpo():
    vg.limpar_cache()
    yield
    vg.limpar_cache()


class RedisFora:
    def ping(self):
        raise ConnectionError("fora")

    def get(self, chave):
        raise ConnectionError("fora")

    def set(self, *args, **kwargs):
        raise ConnectionError("fora")


def _redis():
    return fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)


def _sql(sql, parametros=()):
    conexao = conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


def _msg(loja, lead, canal, quando):
    _sql("INSERT INTO mensagens (loja_id, lead_id, canal, direcao, conteudo, criado_em) "
         "VALUES (?, ?, ?, 'cliente', 'oi', ?)", (loja, lead, canal, para_banco(quando)))


def _uso(tipo, ms, quando, n):
    _sql("INSERT INTO uso_custos (loja_id, execucao_id, criado_em, tipo, latencia_ms) "
         "VALUES (1, ?, ?, ?, ?)", (f"e{n}", para_banco(quando), tipo, ms))


def _niveis(s):
    return {i["chave"]: i["nivel"] for i in s["itens"]}


def _tipos(lista, loja=None):
    return [a["tipo"] for a in lista if loja is None or a["loja_id"] == loja]


def _dados(agora=AGORA):
    vg.limpar_cache()
    return vg.dados_das_lojas(agora)


def _da(lojas, loja_id):
    return next(d for d in lojas if d["loja_id"] == loja_id)


# ------------------------------------------------------------ saúde

def test_redis_fora_vermelho_e_o_resto_desconhecido():
    _msg(1, "a", "whatsapp", AGORA - timedelta(minutes=2))
    s = vg.saude(AGORA, cliente=RedisFora())
    niveis = _niveis(s)
    assert niveis["redis"] == vg.VERMELHO
    assert {niveis[c] for c in ("relogio", "webhook", "ia")} == {vg.DESCONHECIDO}
    assert vg.VERDE not in niveis.values()
    webhook = next(i for i in s["itens"] if i["chave"] == "webhook")
    assert webhook["detalhes"] and webhook["detalhes"][0].startswith("Só para informação")


def test_relogio_cores_e_parado_na_hora():
    r = _redis()
    assert _niveis(vg.saude(AGORA, r))["relogio"] == vg.VERMELHO        # nunca ligado
    batimento.marcar_giro(r, AGORA - timedelta(seconds=10))
    assert _niveis(vg.saude(AGORA, r))["relogio"] == vg.VERDE
    batimento.marcar_giro(r, AGORA - timedelta(seconds=cfg.RELOGIO_AMARELO_S + 5))
    assert _niveis(vg.saude(AGORA, r))["relogio"] == vg.AMARELO
    batimento.marcar_giro(r, AGORA - timedelta(seconds=cfg.RELOGIO_VERMELHO_S + 5))
    assert _niveis(vg.saude(AGORA, r))["relogio"] == vg.VERMELHO
    batimento.marcar_parado(r, AGORA - timedelta(seconds=1))
    s = vg.saude(AGORA, r)
    assert _niveis(s)["relogio"] == vg.VERMELHO
    assert vg.RELOGIO_PARADO in _tipos(vg.alertas([], s))


def test_runner_grava_o_giro_e_o_parado(monkeypatch):
    from app.jobs import runner
    servidor = fakeredis.FakeServer()
    monkeypatch.setattr(runner, "cliente_redis_sincrono",
                        lambda: fakeredis.FakeRedis(server=servidor, decode_responses=True))
    giros, original = [], batimento.marcar_giro
    monkeypatch.setattr(batimento, "marcar_giro",
                        lambda c, agora=None: giros.append(1) or original(c, agora))
    assert runner.main(["--uma-vez", "--sem-remarketing", "--sem-pos-venda",
                        "--sem-reativacao"]) == 0
    assert giros == [1]
    sinal = batimento.ler(fakeredis.FakeRedis(server=servidor, decode_responses=True))
    assert sinal["estado"] == batimento.PARADO


def test_gravar_o_sinal_nunca_derruba_o_runner():
    assert batimento.marcar_giro(RedisFora()) is False
    assert batimento.marcar_parado(RedisFora()) is False


def test_receber_mensagens_ultima_por_canal_sem_simulador():
    r = _redis()
    _msg(1, "s", "simulador", AGORA - timedelta(minutes=1))
    assert _niveis(vg.saude(AGORA, r))["webhook"] == vg.SEM_DADOS
    _msg(1, "a", "whatsapp", AGORA - timedelta(minutes=3))
    _msg(1, "b", "telegram", AGORA - timedelta(minutes=8))
    item = next(i for i in vg.saude(AGORA, r)["itens"] if i["chave"] == "webhook")
    assert item["nivel"] == vg.VERDE and len(item["detalhes"]) == 2


def test_ia_usa_a_media_e_conta_os_erros():
    r = _redis()
    assert _niveis(vg.saude(AGORA, r))["ia"] == vg.SEM_DADOS
    _uso("turno", 2000, AGORA - timedelta(minutes=10), 1)
    _uso("turno", 90000, AGORA - timedelta(hours=2), 2)          # fora da última hora
    assert _niveis(vg.saude(AGORA, r))["ia"] == vg.VERDE
    _uso("turno", 40000, AGORA - timedelta(minutes=5), 3)        # média 21 s
    assert _niveis(vg.saude(AGORA, r))["ia"] == vg.AMARELO
    for n in range(4, 4 + cfg.IA_ERROS_VERMELHO):
        _uso("erro", 100, AGORA - timedelta(minutes=1), n)
    assert _niveis(vg.saude(AGORA, r))["ia"] == vg.VERMELHO


def test_falha_da_ia_e_gravada_pelo_turno():
    fonte = (RAIZ / "app" / "core" / "turno.py").read_text(encoding="utf-8")
    assert 'tipo="erro"' in fonte


# ------------------------------------------------------------ alertas

def test_cliente_esperando_conta_so_o_expediente():
    _sql("INSERT INTO handoffs (loja_id, lead_id, motivo, resumo, estado, criado_em) "
         "VALUES (1, 'n', 'm', '', 'aguardando_humano', ?)",
         (para_banco(datetime(2026, 11, 5, 2, 0, tzinfo=UTC)),))   # 23h de ontem no Recife
    as_9h05 = datetime(2026, 11, 5, 12, 5, tzinfo=UTC)
    lojas = _dados(as_9h05)
    assert _da(lojas, 1)["esperando"] == 1 and _da(lojas, 1)["esperando_vermelho"] == 0
    assert vg.CLIENTE_ESPERANDO not in _tipos(vg.alertas(lojas))
    lojas = _dados(datetime(2026, 11, 5, 12, 30, tzinfo=UTC))      # 9h30: 30 min
    assert vg.CLIENTE_ESPERANDO in _tipos(vg.alertas(lojas), 1)
    noite = datetime(2026, 11, 6, 2, 30, tzinfo=UTC)                # 23h30: fora do horário
    assert _da(_dados(noite), 1)["esperando_vermelho"] == 0


def test_limite_80_amarelo_e_100_vermelho():
    b = criar_loja("Loja B")
    salvar_config(b, {"remarketing.limite_mensal": 10}, "Teste")
    quando = para_banco(AGORA - timedelta(hours=1))
    for n in range(8):
        _sql("INSERT INTO remarketing_envios (loja_id, lead_id, canal, toque, estado, enviado_em) "
             "VALUES (?, ?, 'whatsapp', 1, 'enviado', ?)", (b, f"l{n}", quando))
    lojas = _dados()
    assert _da(lojas, b)["envios"] == enviados_no_mes(b, AGORA) == 8
    [a] = [a for a in vg.alertas(lojas) if a["tipo"] == vg.LIMITE]
    assert a["nivel"] == vg.AMARELO
    for n in range(2):
        _sql("INSERT INTO reativacao (loja_id, contato_id, telefone, lote, meses_inativo, "
             "criado_por, estado, enviado_em) VALUES (?, ?, ?, 'L1', 6, 'Teste', 'enviado', ?)",
             (b, n, f"558199999000{n}", quando))
    lojas = _dados()
    assert _da(lojas, b)["envios"] == enviados_no_mes(b, AGORA) == 10
    [a] = [a for a in vg.alertas(lojas) if a["tipo"] == vg.LIMITE]
    assert a["nivel"] == vg.VERMELHO
    assert cfg.LIMITE_AMARELO == 0.80 and cfg.LIMITE_VERMELHO == 1.00


def test_canal_parado_ok_e_poucos_dados():
    b = criar_loja("Loja B")                                       # em teste
    fim = AGORA - timedelta(days=3)
    for n in range(12):
        _msg(1, f"w{n}", "whatsapp", fim - timedelta(hours=n))     # uma por hora, parou há 3 dias
        _msg(1, f"t{n}", "telegram", AGORA - timedelta(hours=2 + n))
    for n in range(3):
        _msg(b, f"b{n}", "telegram", AGORA - timedelta(hours=n + 1))
    lojas = _dados()
    situacoes = {c["canal"]: c["situacao"] for c in _da(lojas, 1)["canais"]}
    assert situacoes == {"telegram": vg.CANAL_OK, "whatsapp": vg.CANAL_SILENCIO}
    lista = vg.alertas(lojas)
    assert _tipos(lista, 1).count(vg.CANAL_PARADO) == 1
    assert vg.CANAL_PARADO not in _tipos(lista, b)
    linha_b = next(l for l, d in zip(vg.linhas_da_tabela(lojas), lojas) if d["loja_id"] == b)
    assert "poucos dados" in linha_b["Canais"]


def test_mensagem_recusada_so_em_loja_em_teste():
    b = criar_loja("Loja B")
    for loja, horas in ((1, 1), (b, 1), (b, cfg.RECUSA_JANELA_H + 6)):
        _sql("INSERT INTO registro_acoes (quando, loja_id, pessoa, papel, acao, alvo, origem) "
             "VALUES (?, ?, 'Sistema', 'sistema', ?, 'whatsapp:5581', 'webhook')",
             (para_banco(AGORA - timedelta(hours=horas)), loja, vg.EVENTO_RECUSADA))
    lojas = _dados()
    assert _da(lojas, b)["recusadas"] == 1
    lista = vg.alertas(lojas)
    assert _tipos(lista, b).count(vg.RECUSADA) == 1
    assert vg.RECUSADA not in _tipos(lista, 1)


def test_evento_recusada_igual_ao_do_turno():
    from app.core.turno import EVENTO_RECUSADA
    assert vg.EVENTO_RECUSADA == EVENTO_RECUSADA


def test_sem_venda_igual_ao_resumo_da_loja():
    _sql("UPDATE estado_lojas SET no_ar_em = ? WHERE loja_id = 1",
         (para_banco(AGORA - timedelta(days=20)),))
    lista = vg.alertas(_dados())
    assert vg.SEM_VENDA in _tipos(lista, 1)
    assert any("há 20 dias" in a["texto"] for a in lista if a["tipo"] == vg.SEM_VENDA)
    assert any("há 20 dias" in a["texto"] for a in resumo_loja.alertas_da_loja(1, agora=AGORA))
    _sql("INSERT INTO vendas (loja_id, lead_id, veiculo_id, data_venda, forma_pagamento) "
         "VALUES (1, 'c', 1, ?, 'avista')", ((AGORA - timedelta(days=2)).date().isoformat(),))
    assert vg.SEM_VENDA not in _tipos(vg.alertas(_dados()), 1)
    assert not any("venda" in a["texto"] for a in resumo_loja.alertas_da_loja(1, agora=AGORA))


def test_constantes_num_arquivo_so():
    assert resumo_loja.DIAS_SEM_VENDA is cfg.DIAS_SEM_VENDA == 14


# ------------------------------------------------------------ desempenho e cache

def _contar_consultas(monkeypatch):
    feitas, original = [], vg._ler

    def contando():
        conexao = original()
        conexao.set_trace_callback(feitas.append)
        return conexao
    monkeypatch.setattr(vg, "_ler", contando)
    return feitas


def _consultas(feitas):
    return sum(1 for s in feitas if s.lstrip().upper().startswith(("SELECT", "WITH")))


def test_consultas_nao_crescem_com_as_lojas(monkeypatch):
    feitas = _contar_consultas(monkeypatch)
    criar_loja("Loja B")
    _dados()
    com_duas = _consultas(feitas)
    for n in range(5):
        criar_loja(f"Extra {n}")
    feitas.clear()
    assert len(_dados()) == 7
    assert _consultas(feitas) == com_duas


def test_cache_por_loja_nao_mistura_e_expira(monkeypatch):
    b = criar_loja("Loja B")
    tempo = [1000.0]
    monkeypatch.setattr(vg, "_relogio_do_cache", lambda: tempo[0])
    _msg(1, "a", "whatsapp", AGORA - timedelta(hours=1))
    primeira = vg.dados_das_lojas(AGORA)
    assert {d["loja_id"]: d["nome"] for d in primeira} == {1: "Loja 1", b: "Loja B"}
    assert _da(primeira, 1)["conversas_hoje"] == 1 and _da(primeira, b)["conversas_hoje"] == 0
    _msg(b, "x", "telegram", AGORA - timedelta(hours=1))
    tempo[0] += 10
    assert _da(vg.dados_das_lojas(AGORA), b)["conversas_hoje"] == 0     # ainda no cache
    tempo[0] += cfg.CACHE_S
    depois = vg.dados_das_lojas(AGORA)
    assert _da(depois, b)["conversas_hoje"] == 1 and _da(depois, 1)["conversas_hoje"] == 1


def test_saude_e_lida_na_hora_mesmo_com_cache(monkeypatch):
    monkeypatch.setattr(vg, "_relogio_do_cache", lambda: 1000.0)
    r = _redis()
    batimento.marcar_giro(r, AGORA - timedelta(seconds=5))
    assert _niveis(vg.visao_geral(AGORA, r)["saude"])["relogio"] == vg.VERDE
    batimento.marcar_parado(r, AGORA)
    v = vg.visao_geral(AGORA, r)
    assert _niveis(v["saude"])["relogio"] == vg.VERMELHO
    assert vg.RELOGIO_PARADO in _tipos(v["alertas"])


# ------------------------------------------------------------ tela

def test_tela_abre_com_saude_alerta_e_lojas(monkeypatch):
    monkeypatch.setattr(vg, "cliente_redis", _redis)                # relógio sem sinal
    at = AppTest.from_file(str(TELA), default_timeout=30)
    at.session_state["_papel"] = "operador"
    at.session_state["loja_id"] = 1
    at.run()
    assert not at.exception, at.exception
    assert len(at.title) == 1
    subtitulos = [s.value for s in at.subheader]
    assert "Saúde do sistema" in subtitulos and "Lojas" in subtitulos
    assert any("Relógio parado" in e.value for e in at.error)


def test_tela_nao_fala_com_o_banco():
    fonte = TELA.read_text(encoding="utf-8")
    assert "conectar(" not in fonte and "SELECT" not in fonte and "import banco" not in fonte

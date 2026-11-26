"""
SE1 (Maratona Segurança): o vigia (app/vigia.py). OFFLINE: envio falso, Redis falso, sonda falsa.
Nada sai para o Telegram.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app import vigia
from app.jobs import batimento
from app.relogio import para_banco
from banco import conectar

AGORA = datetime(2026, 11, 25, 15, 0, tzinfo=timezone.utc)


class RedisFalso:
    def __init__(self, vivo=True, relogio="girando", idade_s=10):
        self.vivo, self.dados = vivo, {}
        if relogio:
            quando = (AGORA - timedelta(seconds=idade_s)).strftime(batimento.FORMATO)
            self.dados[batimento.CHAVE] = json.dumps({"estado": relogio, "quando": quando})

    def ping(self):
        if not self.vivo:
            raise ConnectionError("fora")
        return True

    def get(self, chave):
        if not self.vivo:
            raise ConnectionError("fora")
        return self.dados.get(chave)


def _conferir(**kw):
    kw.setdefault("cliente_redis", RedisFalso())
    kw.setdefault("pecas", {"webhook": "http://webhook:8000/"})
    kw.setdefault("sonda", lambda endereco: True)
    return vigia.conferir(AGORA, **kw)


def _exec(sql, args=()):
    c = conectar()
    c.execute(sql, args)
    c.commit()
    c.close()


# ------------------------------------------------------------------ o que ele confere
def test_tudo_certo_nao_tem_problema():
    assert _conferir() == {}


def test_banco_fora():
    problemas = _conferir(banco_ok=lambda: False)
    assert set(problemas) == {"banco"}


def test_redis_fora():
    assert "redis" in _conferir(cliente_redis=RedisFalso(vivo=False))


@pytest.mark.parametrize("redis", [RedisFalso(relogio="parado"), RedisFalso(idade_s=600), RedisFalso(relogio=None)])
def test_relogio_parado(redis):
    assert "relogio" in _conferir(cliente_redis=redis)


def test_peca_do_docker_sem_saude():
    problemas = _conferir(pecas={"webhook": "http://w/", "api-painel": "http://a/"},
                          sonda=lambda endereco: endereco != "http://a/")
    assert set(problemas) == {"peca:api-painel"}


def test_ia_errando_demais_na_ultima_hora():
    for i in range(3):
        _exec("INSERT INTO uso_custos (loja_id, lead_id, canal, execucao_id, criado_em, tipo) "
              "VALUES (1, 'x', 'whatsapp', ?, ?, 'erro')", (f"e{i}", para_banco(AGORA - timedelta(minutes=10))))
    assert "ia" in _conferir()
    _exec("UPDATE uso_custos SET criado_em = ?", (para_banco(AGORA - timedelta(hours=2)),))   # fora da hora
    assert "ia" not in _conferir()


def test_webhook_quieto_muito_mais_que_o_normal_da_loja(monkeypatch):
    from app import visao_geral as vg
    monkeypatch.setattr(vg, "dados_das_lojas", lambda agora=None: [
        {"loja_id": 1, "nome": "Loja A", "ativo": True, "estado": vg.NO_AR,
         "canais": [{"canal": "whatsapp", "situacao": vg.CANAL_SILENCIO, "silencio_s": 30 * 3600, "media_s": 1800}]},
        {"loja_id": 2, "nome": "Loja B", "ativo": True, "estado": vg.NO_AR,
         "canais": [{"canal": "whatsapp", "situacao": vg.CANAL_OK, "silencio_s": 60, "media_s": 1800}]},
        {"loja_id": 3, "nome": "Loja em teste", "ativo": True, "estado": "em_teste",
         "canais": [{"canal": "whatsapp", "situacao": vg.CANAL_SILENCIO, "silencio_s": 99 * 3600, "media_s": 60}]},
    ])
    problemas = _conferir()
    assert list(problemas) == ["webhook:1:whatsapp"]          # só a loja No ar em silêncio
    assert "Loja A" in problemas["webhook:1:whatsapp"]


def test_regra_do_canal_parado_e_a_da_visao_geral():
    """O vigia usa a mesma regra (5x a média, mínimo 18 h) da Visão geral: uma loja No ar com
    conversa toda hora e 2 dias de silêncio aparece."""
    from app.estado_loja import colocar_no_ar
    from app.lojas import criar_loja
    from app import visao_geral as vg
    loja = criar_loja("Loja Vigia")
    colocar_no_ar(loja)
    vg.limpar_cache()
    inicio = AGORA - timedelta(days=4)
    for h in range(40):
        _exec("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) VALUES (?, ?, 'whatsapp', 'cliente', 'oi', ?)",
              (f"55819{h:08d}", loja, para_banco(inicio + timedelta(hours=h))))
    assert f"webhook:{loja}:whatsapp" in _conferir()


# ------------------------------------------------------------------ quando ele avisa
def test_um_aviso_por_problema_a_cada_30_min_e_o_voltou():
    enviados = []
    v = vigia.Vigia(enviar=enviados.append)
    assert v.rodada({"banco": "O banco caiu."}, agora_s=0) == ["[Léo] Problema: O banco caiu."]
    for s in (60, 600, 1700):
        assert v.rodada({"banco": "O banco caiu."}, agora_s=s) == []          # nada de repetir
    assert v.rodada({"banco": "O banco caiu."}, agora_s=1800) == ["[Léo] Continua: O banco caiu."]
    assert v.rodada({}, agora_s=1900) == ["[Léo] Voltou ao normal: Banco de dados de volta."]
    assert v.rodada({}, agora_s=2000) == []
    assert enviados == ["[Léo] Problema: O banco caiu.", "[Léo] Continua: O banco caiu.",
                        "[Léo] Voltou ao normal: Banco de dados de volta."]


def test_problema_que_pisca_nao_vira_rajada():
    v = vigia.Vigia(enviar=lambda t: None)
    v.rodada({"peca:webhook": "A peça webhook caiu."}, agora_s=0)
    v.rodada({}, agora_s=60)                                                 # voltou
    assert v.rodada({"peca:webhook": "A peça webhook caiu."}, agora_s=120) == []   # caiu de novo: espera
    assert v.rodada({}, agora_s=180) == []                                  # e não diz "voltou" do que não avisou
    assert v.rodada({"peca:webhook": "A peça webhook caiu."}, agora_s=1900) == ["[Léo] Problema: A peça webhook caiu."]


def test_problemas_diferentes_sao_avisados_separados():
    v = vigia.Vigia(enviar=lambda t: None)
    assert len(v.rodada({"banco": "a", "redis": "b"}, agora_s=0)) == 2
    assert v.rodada({"banco": "a"}, agora_s=10) == ["[Léo] Voltou ao normal: Redis (memória rápida) de volta."]


def test_envio_que_falha_nao_derruba_o_vigia():
    def quebra(texto):
        raise RuntimeError("telegram fora")
    v = vigia.Vigia(enviar=quebra)
    assert v.rodada({"banco": "a"}, agora_s=0) == ["[Léo] Problema: a"]


def test_sem_chat_do_operador_nao_envia_nada(monkeypatch):
    from app import avisos
    chamados = []
    monkeypatch.setattr(avisos, "chat_do_operador", lambda: "")
    monkeypatch.setattr(avisos, "_enviar", lambda chat, texto: chamados.append(texto) or (True, None))
    assert vigia._enviar_ao_operador("oi") is False and chamados == []


def test_envio_vai_para_o_chat_do_operador(monkeypatch):
    from app import avisos
    chamados = []
    monkeypatch.setattr(avisos, "chat_do_operador", lambda: "chat-falso")
    monkeypatch.setattr(avisos, "_enviar", lambda chat, texto: chamados.append((chat, texto)) or (True, None))
    assert vigia._enviar_ao_operador("[Léo] Problema: x") is True
    assert chamados == [("chat-falso", "[Léo] Problema: x")]


def test_pecas_do_ambiente(monkeypatch):
    monkeypatch.delenv("VIGIA_PECAS", raising=False)
    assert set(vigia.pecas_do_ambiente()) == {"webhook", "api-painel", "operador", "porteiro"}
    monkeypatch.setenv("VIGIA_PECAS", "a=http://a/, b=http://b/,ruim")
    assert vigia.pecas_do_ambiente() == {"a": "http://a/", "b": "http://b/"}


def test_textos_sem_emoji():
    import re
    v = vigia.Vigia(enviar=lambda t: None)
    textos = v.rodada(_conferir(banco_ok=lambda: False, cliente_redis=RedisFalso(vivo=False),
                                sonda=lambda e: False), agora_s=0)
    textos += v.rodada({}, agora_s=10)
    assert textos and not any(re.search("[\U0001F300-\U0001FAFF☀-➿]", t) for t in textos)


def test_compose_tem_o_vigia_sem_docker_sock():
    from pathlib import Path
    texto = (Path(__file__).resolve().parent.parent / "docker-compose.yml").read_text(encoding="utf-8")
    assert "vigia:" in texto and "app.vigia" in texto
    assert "/var/run/docker.sock" not in texto           # nenhuma peça recebe o socket do Docker


def test_sinal_de_vida_do_vigia_para_a_saude_do_docker(tmp_path):
    import os
    import sys
    import time
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "docker"))
    import saude
    caminho = str(tmp_path / "vigia_ok")
    assert saude.vigia(caminho) is False                       # nunca conferiu: doente
    vigia.marcar_sinal(caminho)
    assert saude.vigia(caminho) is True
    velho = time.time() - 600
    os.utime(caminho, (velho, velho))
    assert saude.vigia(caminho) is False                       # parou há 10 min: doente

"""
Testes da Etapa 2, Bloco 9: modo de envio por loja.
Envio real = chave geral do servidor (.env) E chave da loja. Duas lojas, tudo offline.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from banco import conectar
from app import lojas, modo_envio
from app import painel_envios as pe
from app.config_tela import campo, grupos_do
from app.custos import Uso
from app.jobs import remarketing as rmk
from app.lojas import SemPermissao, carregar_loja, historico_config, salvar_config
from app.relogio import para_banco
from app.resultado_envio import ResultadoEnvio

RAIZ = Path(__file__).resolve().parent.parent
AGORA = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)   # terça, 09:00 em Recife
TIPOS = ("remarketing", "pos_venda", "reativacao")


def _geral(monkeypatch, ligado: bool):
    for var in modo_envio.VARIAVEIS.values():
        monkeypatch.setenv(var, "1" if ligado else "0")


class EnviadorFalso:
    def __init__(self):
        self.textos, self.modelos = [], []

    async def texto(self, loja_id, canal, lead_id, texto):
        self.textos.append((loja_id, canal, lead_id, texto))
        return ResultadoEnvio(ok=True, id_externo="x1")

    async def modelo(self, loja_id, lead_id, modelo, valores):
        self.modelos.append((loja_id, lead_id, modelo.nome))
        return ResultadoEnvio(ok=True, id_externo="x1")


def _redator(loja, lead_id, canal, toque, dados, historico):
    return "Oi! Quer ver de perto aquele carro?", Uso(10, 5, 0)


def _conversa(loja_id, lead_id):
    c = conectar()
    for direcao, horas in (("cliente", 72), ("leo", 71)):
        c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
                  "VALUES (?, ?, 'telegram', ?, 'oi', ?)",
                  (lead_id, loja_id, direcao, para_banco(AGORA - timedelta(hours=horas))))
    c.commit()
    c.close()


def _estado(loja_id):
    c = conectar()
    linha = c.execute("SELECT estado FROM remarketing_envios WHERE loja_id = ?", (loja_id,)).fetchone()
    c.close()
    return linha["estado"] if linha else None


# ---------------------------------------------------------------- configuração
def test_loja_nova_comeca_em_teste():
    loja2 = lojas.criar_loja("Loja 2")
    for loja_id in (1, loja2):
        loja = carregar_loja(loja_id)
        assert all(loja.get(f"envio_real.{t}") is False for t in TIPOS)


def test_cliente_nao_muda_o_modo_de_envio():
    with pytest.raises(SemPermissao):
        salvar_config(1, {"envio_real.remarketing": True}, "lojista", papel="cliente")
    assert carregar_loja(1).get("envio_real.remarketing") is False


def test_operador_muda_e_fica_no_historico():
    salvar_config(1, {"envio_real.pos_venda": True}, "Samuel", papel="operador")
    assert carregar_loja(1).get("envio_real.pos_venda") is True
    ultimo = historico_config(1)[0]
    assert (ultimo["chave"], ultimo["usuario"]) == ("envio_real.pos_venda", "Samuel")


# ---------------------------------------------------------------- duas chaves
@pytest.mark.parametrize("geral, da_loja, esperado", [
    (False, False, False), (True, False, False), (False, True, False), (True, True, True),
])
def test_envio_real_precisa_das_duas_chaves(monkeypatch, geral, da_loja, esperado):
    _geral(monkeypatch, geral)
    if da_loja:
        salvar_config(1, {"envio_real.remarketing": True}, "Samuel")
    assert modo_envio.real_para(carregar_loja(1), "remarketing") is esperado


def test_forcado_passa_por_cima(monkeypatch):
    _geral(monkeypatch, False)
    assert modo_envio.real_para(carregar_loja(1), "pos_venda", True) is True
    _geral(monkeypatch, True)
    salvar_config(1, {"envio_real.pos_venda": True}, "Samuel")
    assert modo_envio.real_para(carregar_loja(1), "pos_venda", False) is False


def test_tipo_desconhecido_e_recusado():
    with pytest.raises(ValueError):
        modo_envio.real_para(carregar_loja(1), "instagram")


@pytest.mark.parametrize("geral, da_loja, esperado", [
    (True, True, "real"), (True, False, "teste_loja"),
    (False, True, "teste_servidor"), (False, False, "teste"),
])
def test_situacao_explica_por_que_esta_em_teste(monkeypatch, geral, da_loja, esperado):
    _geral(monkeypatch, geral)
    if da_loja:
        salvar_config(1, {"envio_real.reativacao": True}, "Samuel")
    assert modo_envio.situacao(carregar_loja(1), "reativacao") == esperado


# ---------------------------------------------------------------- jobs
def test_duas_lojas_so_a_que_esta_em_real_envia(monkeypatch):
    _geral(monkeypatch, True)
    loja2 = lojas.criar_loja("Loja 2")
    for loja_id in (1, loja2):
        salvar_config(loja_id, {"modulos.remarketing": True, "remarketing.limite_mensal": 50}, "teste")
        _conversa(loja_id, "111")
    salvar_config(1, {"envio_real.remarketing": True}, "Samuel")
    env = EnviadorFalso()
    rmk.rodar_remarketing(AGORA, redator=_redator, enviador=env, pausa_s=0, lojas=[1, loja2])
    assert [t[0] for t in env.textos] == [1]
    assert _estado(1) == "enviado"
    assert _estado(loja2) == "simulado"


@pytest.mark.parametrize("arquivo, tipo", [
    ("app/jobs/remarketing.py", "remarketing"),
    ("app/jobs/pos_venda.py", "pos_venda"),
    ("app/jobs/reativacao.py", "reativacao"),
])
def test_cada_job_decide_pela_loja(arquivo, tipo):
    fonte = (RAIZ / arquivo).read_text(encoding="utf-8")
    assert f'real_para(loja, "{tipo}", envio_real)' in fonte
    assert "real = envio_real_ligado() if envio_real is None" not in fonte


# ---------------------------------------------------------------- telas
def test_campos_ficam_na_tela_do_operador():
    for t in TIPOS:
        assert campo(f"envio_real.{t}").dono == "operador"
    assert "Envios" in grupos_do("operador")
    assert "Envios" not in grupos_do("cliente")


def test_painel_mostra_o_modo_de_cada_loja(monkeypatch):
    _geral(monkeypatch, True)
    loja2 = lojas.criar_loja("Loja 2")
    salvar_config(1, {"envio_real.remarketing": True}, "Samuel")
    assert pe.modo_de_envio(carregar_loja(1))["remarketing"] is True
    assert pe.modo_de_envio(carregar_loja(loja2))["remarketing"] is False
    assert all(pe.modo_de_envio().values())          # sem loja: só a chave geral
    assert pe.situacao_do_modo(carregar_loja(loja2))["remarketing"] == "teste_loja"

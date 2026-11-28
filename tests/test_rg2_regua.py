"""
RG2 (Maratona 5): limite diário do remarketing e cópia da régua com confirmação. OFFLINE, duas lojas.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone

import pytest

from app import config_tela, lojas, regua, vendas
from app.ator import como
from app.custos import Uso
from app.estado_loja import colocar_no_ar
from app.jobs import remarketing as rmk
from app.lojas import criar_loja
from app.relogio import para_banco
from app.resultado_envio import ResultadoEnvio
from banco import conectar

AGORA = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)      # terça, 09:00 em Recife


def _sql(sql, args=()):
    c = conectar()
    cur = c.execute(sql, args)
    novo = cur.lastrowid
    if novo is None and "RETURNING" in sql:
        novo = cur.fetchone()[0]
    c.commit()
    c.close()
    return novo


def _ler(sql, args=()):
    c = conectar()
    try:
        return [dict(l) for l in c.execute(sql, args).fetchall()]
    finally:
        c.close()


class Enviador:
    def __init__(self):
        self.textos = []

    async def texto(self, loja_id, canal, lead_id, texto):
        self.textos.append((loja_id, lead_id))
        return ResultadoEnvio(ok=True, id_externo="x")

    async def modelo(self, loja_id, lead_id, modelo, valores):
        self.textos.append((loja_id, lead_id))
        return ResultadoEnvio(ok=True, id_externo="y")


def _redator(*a):
    return "Oi! Conseguiu pensar no carro? Se quiser, separo um horário para você ver de perto.", Uso(100, 20, 0)


def _preparar(loja_id, clientes, por_dia=None):
    colocar_no_ar(loja_id)
    mudancas = {"modulos.remarketing": True, "remarketing.limite_mensal": 1000}
    if por_dia is not None:
        mudancas["remarketing.max_por_dia"] = por_dia
    lojas.salvar_config(loja_id, mudancas, "teste")
    for n in range(clientes):
        lead = f"55817{loja_id:02d}{n:06d}"
        for direcao, desloca in (("cliente", 0), ("leo", 1)):
            _sql("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) VALUES (?, ?, 'telegram', ?, 'x', ?)",
                 (lead, loja_id, direcao, para_banco(AGORA - timedelta(hours=72) + timedelta(minutes=desloca))))


def _rodar(agora=AGORA, real=True, lojas_=None):
    env = Enviador()
    totais = rmk.rodar_remarketing(agora, envio_real=real, redator=_redator, enviador=env, pausa_s=0,
                                   lojas=lojas_ or [1], max_por_loja=100)
    return totais, env


# ================================================================== 1. limite diário
def test_padrao_e_50_e_aparece_em_plano_e_limites():
    assert lojas.carregar_loja(1).get("remarketing.max_por_dia") == 50
    assert "remarketing.max_por_dia" in config_tela.CAMPOS_AVULSOS_DO_ASSUNTO[config_tela.PLANO_E_LIMITES]
    campo = next(c for c in config_tela.CAMPOS if c.chave == "remarketing.max_por_dia")
    assert campo.dono == "operador"
    assert "remarketing.max_por_dia" in lojas.CHAVES_DO_OPERADOR       # o servidor também barra o lojista


def test_para_no_limite_do_dia_e_o_resto_nao_e_falha():
    _preparar(1, 8, por_dia=5)
    totais, env = _rodar()
    assert len(env.textos) == 5 and totais["enviado"] == 5
    assert totais["falhou"] == 0 and totais["erro"] == 0
    _, env2 = _rodar(AGORA + timedelta(hours=2))                     # mesmo dia: nada mais
    assert env2.textos == []


def test_no_dia_seguinte_volta_a_enviar():
    _preparar(1, 8, por_dia=5)
    _rodar()
    _, env = _rodar(AGORA + timedelta(days=1))                       # quarta, 09:00 em Recife
    assert len(env.textos) == 3


def test_o_dia_e_o_da_loja():
    """22:30 de terça em Recife já é quarta em UTC: conta como terça (o dia da loja)."""
    _preparar(1, 3, por_dia=2)
    lojas.salvar_config(1, {"remarketing.horario_envio": "08:00-21:00"}, "teste")
    _sql("INSERT INTO remarketing_envios (loja_id, lead_id, canal, toque, estado, enviado_em, criado_em) "
         "VALUES (1, 'outro', 'telegram', 1, 'enviado', ?, ?)", (para_banco(AGORA - timedelta(hours=1)),) * 2)
    loja = lojas.carregar_loja(1)
    assert rmk.enviados_hoje(loja, AGORA, real=True) == 1
    assert rmk.enviados_hoje(loja, AGORA + timedelta(days=1), real=True) == 0
    assert rmk.enviados_hoje(loja, datetime(2026, 11, 4, 1, 30, tzinfo=timezone.utc), real=True) == 1   # 22:30 terça


def test_simulacao_conta_os_simulados():
    _preparar(1, 6, por_dia=4)
    totais, _ = _rodar(real=False)
    assert totais["simulado"] == 4


def test_limite_de_uma_loja_nao_mexe_na_outra():
    b = criar_loja("Loja B Limite")
    _preparar(1, 6, por_dia=2)
    _preparar(b, 6, por_dia=5)
    _, env = _rodar(lojas_=[1, b])
    assert sum(1 for l, _ in env.textos if l == 1) == 2
    assert sum(1 for l, _ in env.textos if l == b) == 5


def test_zero_nao_envia():
    _preparar(1, 3, por_dia=0)
    _, env = _rodar()
    assert env.textos == []


# ================================================================== 2. copiar a régua com confirmação
def _venda(loja_id=1, lead="5581944440001"):
    carro = _sql("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) VALUES "
                 "(?, 'Honda', 'Civic', 2019, 50000, 'Prata', 'Automático', 98000, 'disponivel') RETURNING id", (loja_id,))
    _sql("INSERT INTO leads (lead_id, loja_id, nome) VALUES (?, ?, 'Ana') ON CONFLICT DO NOTHING", (lead, loja_id))
    with como("Teste", "cliente", "painel", loja_id):
        vendas.registrar_venda(loja_id, lead, carro, date(2026, 11, 2), "avista", vendedor="V",
                               agora=datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc))


def _agendados(loja_id=1):
    return _ler("SELECT COUNT(*) AS n FROM regua_execucoes WHERE loja_id = ? AND estado = 'agendado'", (loja_id,))[0]["n"]


def test_previa_diz_quantos_serao_cancelados_e_sem_confirmar_nao_copia():
    lojas.salvar_config(1, {"modulos.pos_venda": True}, "teste")
    _venda()
    n = _agendados()
    assert n > 0
    previa = regua.previa_da_copia(1, "essencial")
    assert (previa["modelo"], previa["agendados"]) == ("essencial", n)
    antes = regua.regua_ativa(1)["id"]
    with pytest.raises(regua.ConfirmacaoNecessaria, match=f"cancela {n}"):
        regua.copiar_regua_modelo(1, "essencial")
    assert regua.regua_ativa(1)["id"] == antes and _agendados() == n          # nada mudou


def test_com_confirmacao_copia_e_cancela_com_regua_trocada():
    lojas.salvar_config(1, {"modulos.pos_venda": True}, "teste")
    _venda()
    n = _agendados()
    regua.copiar_regua_modelo(1, "essencial", confirmar=True)
    assert _agendados() == 0
    assert _ler("SELECT COUNT(*) AS n FROM regua_execucoes WHERE loja_id = 1 AND motivo = 'regua_trocada'")[0]["n"] == n
    assert regua.modelo_em_uso(1) == "essencial"


def test_copiar_na_loja_a_nao_cancela_a_loja_b():
    b = criar_loja("Loja B Copia")
    colocar_no_ar(b)
    for loja_id in (1, b):
        lojas.salvar_config(loja_id, {"modulos.pos_venda": True}, "teste")
        _venda(loja_id, f"558194444{loja_id:04d}")
    nb = _agendados(b)
    regua.copiar_regua_modelo(1, None, confirmar=True)
    assert _agendados(b) == nb > 0


def test_script_pergunta_e_so_copia_com_sim():
    from scripts import copiar_regua as script
    lojas.salvar_config(1, {"modulos.pos_venda": True}, "teste")
    _venda()
    n = _agendados()
    saida = []
    script.main(["--loja", "1", "--modelo", "essencial"], entrada=lambda _: "não", saida=saida.append)
    assert _agendados() == n and any(f"{n} passo(s) agendado(s)" in s for s in saida) and "Nada mudou." in saida
    script.main(["--loja", "1", "--modelo", "essencial"], entrada=lambda _: "SIM", saida=saida.append)
    assert _agendados() == 0 and regua.modelo_em_uso(1) == "essencial"


def test_script_com_confirmar_e_todas_usa_a_regua_de_cada_loja():
    from scripts import copiar_regua as script
    b = criar_loja("Loja B Todas")
    regua.garantir_regua(1)
    regua.copiar_regua_modelo(b, "essencial", confirmar=True)
    saida = []
    script.main(["--todas", "--confirmar"], saida=saida.append)
    assert regua.modelo_em_uso(1) == "proxima" and regua.modelo_em_uso(b) == "essencial"
    assert any("Loja 1: régua copiada" in s for s in saida)


def test_regua_nova_tem_os_passos_do_rg1():
    regua.garantir_regua(1)
    nomes = [p["nome"] for p in regua.regua_ativa(1)["passos"]]
    assert "conferir_transferencia" in nomes
    avaliacao = next(p for p in regua.regua_ativa(1)["passos"] if p["nome"] == "avaliacao")
    assert avaliacao["deslocamento_dias"] == 15


def test_reiniciar_a_demo_cria_a_regua_nova():
    from app.demo import criar_loja_demo, reiniciar_demo
    loja = criar_loja_demo(indexar=False)
    with como("Teste", "operador", "painel", None):
        reiniciar_demo(loja, indexar=False)
    ativa = regua.regua_ativa(loja)
    assert ativa is not None
    nomes = [p["nome"] for p in ativa["passos"]]
    assert "conferir_transferencia" in nomes
    assert next(p for p in ativa["passos"] if p["nome"] == "avaliacao")["deslocamento_dias"] == 15

"""
P5 do Plano Mestre: bloqueios de envio (escolha da loja) e carência.
- "Não enviar" segura UMA mensagem; "Não procurar mais" (todos) segura tudo.
- Bloqueio NÃO é opt-out e pode ser desfeito (a linha fica, com quem desfez).
- A reconferência logo antes de enviar também barra (remarketing, pós-venda, reativação).
- Carência: sem retomada por 7 dias depois do vendedor ou da visita marcada.
Tudo offline: banco temporário do conftest, sem IA, duas lojas.
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import banco
from banco import conectar
from app import painel_envios
from app import reativacao as rv
from app.bloqueios import (
    BloqueioInvalido, bloquear, bloqueado, desfazer, listar_ativos,
)
from app.chaves import LojaNaoInformada
from app.custos import Uso
from app.elegibilidade import avaliar
from app.lojas import ConfigInvalida, SemPermissao, carregar_loja, criar_loja, salvar_config

RAIZ = Path(__file__).resolve().parent.parent
AGORA = datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc)   # terça, 10:00 em Recife
LEAD = "5581999990000"
CANAL = "telegram"


def _sql(sql, parametros=()):
    conexao = conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


def _contar(sql, parametros=()):
    conexao = conectar()
    try:
        return conexao.execute(sql, parametros).fetchone()[0]
    finally:
        conexao.close()


def _preparar(loja_id=1):
    """Remarketing ligado e um cliente que falou há 3 dias: pode receber agora."""
    salvar_config(loja_id, {"modulos.remarketing": True, "remarketing.limite_mensal": 100}, "teste")
    _sql("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
         "VALUES (?, ?, ?, 'cliente', 'quero ver o Gol', '2026-10-31 13:00:00')",
         (LEAD, loja_id, CANAL))


def _decisao(agora=AGORA, loja_id=1):
    return avaliar(loja_id, LEAD, CANAL, agora)


def _redator(*args, **kwargs):
    return "Oi! Ainda posso te ajudar com o Gol?", Uso()


# ------------------------------------------------------------ migração

def test_migracao_9_cria_a_tabela():
    assert banco.VERSAO_SCHEMA >= 9
    assert _contar("SELECT COUNT(*) FROM sqlite_master WHERE name = 'bloqueios_envio'") == 1


def test_todos_nao_aceita_passo_no_banco():
    with pytest.raises(sqlite3.IntegrityError):
        _sql("INSERT INTO bloqueios_envio (loja_id, lead_id, tipo, passo, criado_por) "
             "VALUES (1, ?, 'todos', 1, 'Ana')", (LEAD,))


# ------------------------------------------------------------ bloqueio

def test_sem_bloqueio_pode_receber():
    _preparar()
    d = _decisao()
    assert d.elegivel, d.motivo


def test_nao_enviar_segura_o_toque_e_desfazer_libera():
    _preparar()
    id_bloqueio = bloquear(1, LEAD, "remarketing", 1, "Ana", agora=AGORA)
    assert _decisao().motivo == "bloqueado_pela_loja"
    assert desfazer(1, id_bloqueio, "Ana", agora=AGORA)
    assert _decisao().elegivel


def test_bloqueio_de_outro_toque_nao_segura_este():
    _preparar()
    bloquear(1, LEAD, "remarketing", 2, "Ana", agora=AGORA)
    assert _decisao().elegivel


def test_nao_procurar_mais_segura_tudo():
    _preparar()
    bloquear(1, LEAD, "todos", 5, "Ana", agora=AGORA)
    assert _decisao().motivo == "bloqueado_pela_loja"
    assert bloqueado(1, LEAD, "pos_venda", 77)
    assert bloqueado(1, LEAD, "reativacao", None)
    assert listar_ativos(1)[0]["passo"] is None        # 'todos' nunca guarda passo


def test_bloqueio_nao_e_optout():
    bloquear(1, LEAD, "todos", None, "Ana", agora=AGORA)
    assert _contar("SELECT COUNT(*) FROM optouts") == 0
    assert _contar("SELECT COUNT(*) FROM situacao_lead") == 0


def test_marcar_duas_vezes_nao_duplica():
    a = bloquear(1, LEAD, "remarketing", 1, "Ana", agora=AGORA)
    b = bloquear(1, LEAD, "remarketing", 1, "Beto", agora=AGORA)
    assert a == b
    assert len(listar_ativos(1)) == 1


def test_desfazer_guarda_quem_desfez_e_nao_apaga():
    id_bloqueio = bloquear(1, LEAD, "todos", None, "Ana", agora=AGORA)
    assert desfazer(1, id_bloqueio, "Beto", agora=AGORA)
    assert not desfazer(1, id_bloqueio, "Beto", agora=AGORA)     # já estava desfeito
    assert listar_ativos(1) == []
    assert _contar("SELECT COUNT(*) FROM bloqueios_envio WHERE desfeito_por = 'Beto'") == 1


def test_desfazer_de_outra_loja_nao_faz_nada():
    loja2 = criar_loja("Loja 2")
    id_bloqueio = bloquear(1, LEAD, "todos", None, "Ana", agora=AGORA)
    assert not desfazer(loja2, id_bloqueio, "Intruso", agora=AGORA)
    assert len(listar_ativos(1)) == 1


def test_bloqueio_de_uma_loja_nao_vale_na_outra():
    loja2 = criar_loja("Loja 2")
    _preparar(1)
    bloquear(loja2, LEAD, "todos", None, "Ana", agora=AGORA)
    assert _decisao().elegivel
    assert bloqueado(loja2, LEAD, "remarketing", 1)


def test_loja_obrigatoria():
    with pytest.raises(LojaNaoInformada):
        bloquear(None, LEAD, "todos", None, "Ana")
    with pytest.raises(LojaNaoInformada):
        bloqueado(None, LEAD, "todos", None)
    with pytest.raises(LojaNaoInformada):
        listar_ativos(None)


@pytest.mark.parametrize("lead, tipo, autor", [
    (LEAD, "retomada", "Ana"),     # o nome no banco é 'remarketing'
    (LEAD, "todos", "   "),
    ("", "todos", "Ana"),
])
def test_validacoes(lead, tipo, autor):
    with pytest.raises(BloqueioInvalido):
        bloquear(1, lead, tipo, None, autor)


# ------------------------------------------------------------ reconferência

def test_reconferencia_do_job_barra_bloqueio_feito_depois_da_fila():
    from app.jobs.remarketing import processar_lead
    _preparar()
    d = _decisao()
    assert d.elegivel
    bloquear(1, LEAD, "remarketing", d.toque, "Ana", agora=AGORA)   # marcou depois da fila
    estado = processar_lead(carregar_loja(1), d, AGORA, real=False,
                            redator=_redator, enviador=None)
    assert estado == "pulado"
    assert _contar("SELECT COUNT(*) FROM remarketing_envios") == 0


def test_rodada_do_remarketing_nao_grava_nada_para_bloqueado():
    from app.jobs.remarketing import rodar_remarketing
    _preparar()
    bloquear(1, LEAD, "todos", None, "Ana", agora=AGORA)
    rodar_remarketing(AGORA, envio_real=False, redator=_redator, enviador=object(),
                      pausa_s=0, lojas=[1])
    assert _contar("SELECT COUNT(*) FROM remarketing_envios") == 0
    desfazer(1, listar_ativos(1)[0]["id"], "Ana", agora=AGORA)
    rodar_remarketing(AGORA, envio_real=False, redator=_redator, enviador=object(),
                      pausa_s=0, lojas=[1])
    assert _contar("SELECT COUNT(*) FROM remarketing_envios") == 1


def test_pos_venda_bloqueado_fica_esperando():
    from app.jobs import pos_venda
    bloquear(1, LEAD, "pos_venda", 77, "Ana", agora=AGORA)
    passo = {"id": 77, "evento_tipo": "teste", "lead_id": LEAD,
             "passo_nome": "Revisão", "passo_ativo": 1}
    assert pos_venda.processar(carregar_loja(1), passo, AGORA, real=False, enviador=None) == "adiado"
    assert not bloqueado(1, LEAD, "pos_venda", 78)


def test_reativacao_respeita_bloqueio_na_montagem_e_antes_de_enviar():
    from app.jobs import reativacao as job
    id_bloqueio = bloquear(1, LEAD, "reativacao", None, "Ana", agora=AGORA)
    foto = rv.fotografia(1, AGORA)
    contato = {"telefone": LEAD, "consentimento": 1}
    assert rv.motivo_para_nao_reativar(foto, contato, AGORA, 6) == "bloqueado_pela_loja"
    linha = {"id": 1, "telefone": LEAD, "consentimento": 1, "meses_inativo": 6}
    assert job.processar(carregar_loja(1), linha, AGORA, foto, real=False, enviador=None) == "adiado"
    desfazer(1, id_bloqueio, "Ana", agora=AGORA)
    assert rv.motivo_para_nao_reativar(rv.fotografia(1, AGORA), contato, AGORA, 6) is None


def test_fila_mostra_quem_marcou():
    _preparar()
    bloquear(1, LEAD, "remarketing", 1, "Ana", agora=AGORA)
    itens = [i for i in painel_envios.fila(1, AGORA) if i["lead_id"] == LEAD]
    assert len(itens) == 1
    assert itens[0]["situacao"] == "Não será enviada"
    assert itens[0]["bloqueio"]["criado_por"] == "Ana"


# ------------------------------------------------------------ carência

def test_carencia_depois_do_vendedor():
    _preparar()
    _sql("INSERT INTO handoffs (lead_id, loja_id, motivo, estado, vendedor, criado_em, "
         "assumido_em, encerrado_em) VALUES (?, 1, 'teste', 'encerrado', 'Ana', "
         "'2026-11-01 13:00:00', '2026-11-01 13:05:00', '2026-11-01 14:00:00')", (LEAD,))
    d = _decisao()
    assert d.motivo == "carencia"
    assert d.proximo_em >= datetime(2026, 11, 8, 14, 0, tzinfo=timezone.utc)
    assert _decisao(AGORA + timedelta(days=6)).elegivel     # segunda 09/11, carência acabou


def test_carencia_depois_da_visita_marcada():
    _preparar()
    _sql("INSERT INTO agendamentos (lead_id, loja_id, nome_cliente, tipo, data_hora, criado_em) "
         "VALUES (?, 1, 'Cliente', 'visita', 'sábado 10h', '2026-11-02 12:00:00')", (LEAD,))
    assert _decisao().motivo == "carencia"


def test_carencia_zero_desliga():
    _preparar()
    salvar_config(1, {"remarketing.carencia_dias": 0}, "teste")
    _sql("INSERT INTO agendamentos (lead_id, loja_id, nome_cliente, tipo, data_hora, criado_em) "
         "VALUES (?, 1, 'Cliente', 'visita', 'sábado 10h', '2026-11-02 12:00:00')", (LEAD,))
    assert _decisao().elegivel


def test_carencia_padrao_7_e_so_o_operador_muda():
    assert carregar_loja(1).get("remarketing.carencia_dias") == 7
    with pytest.raises(ConfigInvalida):
        salvar_config(1, {"remarketing.carencia_dias": 91}, "teste")
    with pytest.raises(SemPermissao):
        salvar_config(1, {"remarketing.carencia_dias": 3}, "dono", papel="cliente")


# ------------------------------------------------------------ telas e atendimento

def test_tela_tem_os_botoes_e_nao_fala_com_o_banco():
    texto = (RAIZ / "paginas" / "envios.py").read_text(encoding="utf-8")
    for frase in ("Não enviar esta mensagem", "Não procurar mais", "Desfazer"):
        assert frase in texto
    assert "conectar" not in texto and "import banco" not in texto


def test_atendimento_nao_usa_bloqueios():
    texto = (RAIZ / "app" / "core" / "turno.py").read_text(encoding="utf-8")
    assert "bloqueios" not in texto

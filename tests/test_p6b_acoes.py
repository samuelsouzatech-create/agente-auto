"""
P6b do Plano Mestre: as ações relevantes deixam rastro (quem, quando, antes e depois).
- toda ação de ACOES_RELEVANTES tem um cenário aqui (ação nova sem teste = falha);
- cada ação grava com o nome do ATOR, não com o nome que a função recebe;
- sem ator, a ação falha e nada fica (nem a ação, nem o registro);
- ator de uma loja não age na outra.
Tudo offline, banco temporário do conftest (ator "Teste", operador, painel).
"""
import importlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from banco import conectar
from app import bloqueios, importacao, pausa, reativacao, vendas
from app.ator import AtorInvalido, SemAtor, como, sem_ator
from app.lojas import criar_loja, salvar_config
from app.registro import ACOES_RELEVANTES, HISTORICO_PROPRIO

RAIZ = Path(__file__).resolve().parent.parent
HOJE = date(2026, 10, 30)
AGORA = datetime(2026, 10, 30, 13, 0, tzinfo=timezone.utc)   # sexta, 10h no Recife
LEAD = "5581999990000"
CSV = (
    "nome;telefone;carro;data_compra;pagamento\n"
    "Ana Souza;(81) 99999-8888;Honda Civic 2019;10/01/2024;à vista\n"
    "Carlos Lima;(81) 98888-7777;;;\n"
)


def _um(sql, parametros=()):
    conexao = conectar()
    try:
        return conexao.execute(sql, parametros).fetchone()[0]
    finally:
        conexao.close()


def _registros(acao):
    conexao = conectar()
    try:
        return [dict(l) for l in conexao.execute(
            "SELECT * FROM registro_acoes WHERE acao = ? ORDER BY id", (acao,))]
    finally:
        conexao.close()


def _carro(loja_id=1):
    conexao = conectar()
    try:
        novo = conexao.execute(
            "INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) "
            "VALUES (?, 'Hyundai', 'HB20', 2020, 40000, 'Prata', 'Manual', 60000, 'disponivel')",
            (loja_id,)).lastrowid
        conexao.commit()
        return novo
    finally:
        conexao.close()


def _importar(loja_id=1):
    return importacao.importar(loja_id, importacao.ler_planilha(CSV.encode("utf-8"), hoje=HOJE),
                               usuario="Ana", consentimento=True, arquivo="base.csv")


# ------------------------------------------------------------ cenários
# acao -> (preparar, executar(estado), consulta que conta o efeito da ação)

def _prep_nada():
    return {}


def _prep_pausado():
    pausa.pausar(1, usuario="Ana", papel="cliente")
    return {}


def _prep_bloqueio():
    return {"id": bloqueios.bloquear(1, LEAD, "todos", None, "Ana")}


def _prep_carro():
    return {"carro": _carro()}


def _prep_importado():
    return {"imp": _importar()["importacao_id"]}


def _prep_base_ligada():
    salvar_config(1, {"modulos.remarketing": True, "remarketing.limite_mensal": 30}, "Samuel")
    _importar()
    return {}


def _prep_fila_montada():
    _prep_base_ligada()
    reativacao.montar_fila(1, usuario="Ana", agora=AGORA)
    return {}


CENARIOS = {
    "pausar_envios": (
        _prep_nada,
        lambda s: pausa.pausar(1, usuario="Ana", papel="cliente"),
        "SELECT COUNT(*) FROM pausas_envio WHERE acao = 'pausar'"),
    "retomar_envios": (
        _prep_pausado,
        lambda s: pausa.retomar(1, usuario="Ana", papel="cliente"),
        "SELECT COUNT(*) FROM pausas_envio WHERE acao = 'retomar'"),
    "bloquear_envio": (
        _prep_nada,
        lambda s: bloqueios.bloquear(1, LEAD, "todos", None, "Ana"),
        "SELECT COUNT(*) FROM bloqueios_envio"),
    "desfazer_bloqueio": (
        _prep_bloqueio,
        lambda s: bloqueios.desfazer(1, s["id"], "Ana"),
        "SELECT COUNT(*) FROM bloqueios_envio WHERE desfeito_em IS NOT NULL"),
    "registrar_venda": (
        _prep_carro,
        lambda s: vendas.registrar_venda(1, LEAD, s["carro"], HOJE, "avista",
                                         vendedor="Ana", agora=AGORA),
        "SELECT COUNT(*) FROM vendas"),
    "importar_base": (
        _prep_nada,
        lambda s: _importar(),
        "SELECT COUNT(*) FROM importacoes"),
    "desfazer_importacao": (
        _prep_importado,
        lambda s: importacao.desfazer_importacao(1, s["imp"]),
        "SELECT COUNT(*) FROM importacoes WHERE desfeita_em IS NOT NULL"),
    "montar_fila_reativacao": (
        _prep_base_ligada,
        lambda s: reativacao.montar_fila(1, usuario="Ana", agora=AGORA),
        "SELECT COUNT(*) FROM reativacao"),
    "cancelar_fila_reativacao": (
        _prep_fila_montada,
        lambda s: reativacao.cancelar_fila(1, agora=AGORA),
        "SELECT COUNT(*) FROM reativacao WHERE estado = 'cancelado'"),
}


# ------------------------------------------------------------ a lista

def test_toda_acao_relevante_tem_cenario():
    assert set(CENARIOS) == set(ACOES_RELEVANTES)


def test_historico_proprio_so_tem_acoes_da_lista():
    assert set(HISTORICO_PROPRIO) <= set(ACOES_RELEVANTES)


@pytest.mark.parametrize("acao", sorted(ACOES_RELEVANTES))
def test_funcao_da_lista_existe(acao):
    modulo, _, nome = ACOES_RELEVANTES[acao].rpartition(".")
    assert callable(getattr(importlib.import_module(modulo), nome))


@pytest.mark.parametrize("acao", sorted(ACOES_RELEVANTES))
def test_cada_acao_deixa_rastro_com_o_ator(acao):
    preparar, executar, efeito = CENARIOS[acao]
    estado = preparar()
    antes = _um(efeito)
    executar(estado)
    assert _um(efeito) > antes
    linhas = _registros(acao)
    if acao in HISTORICO_PROPRIO:
        assert linhas == []                       # não duplica: já tem histórico próprio
        return
    assert len(linhas) == 1
    l = linhas[0]
    # A função recebeu "Ana"; quem fica no Registro é o ATOR ("Teste").
    assert (l["pessoa"], l["papel"], l["origem"], l["loja_id"]) == ("Teste", "operador", "painel", 1)
    assert l["quando"] and l["depois"]


@pytest.mark.parametrize("acao", sorted(ACOES_RELEVANTES))
def test_sem_ator_a_acao_falha_e_nada_fica(acao):
    preparar, executar, efeito = CENARIOS[acao]
    estado = preparar()
    antes_efeito = _um(efeito)
    antes_registro = _um("SELECT COUNT(*) FROM registro_acoes")
    with sem_ator(), pytest.raises(SemAtor):
        executar(estado)
    assert _um(efeito) == antes_efeito
    assert _um("SELECT COUNT(*) FROM registro_acoes") == antes_registro


# ------------------------------------------------------------ detalhes

def test_venda_sem_ator_nao_tira_o_carro_do_estoque():
    carro = _carro()
    with sem_ator(), pytest.raises(SemAtor):
        vendas.registrar_venda(1, LEAD, carro, HOJE, "avista", vendedor="Ana", agora=AGORA)
    assert _um("SELECT status FROM estoque WHERE id = ?", (carro,)) == "disponivel"
    assert _um("SELECT COUNT(*) FROM resultados") == 0


def test_venda_grava_antes_e_depois():
    carro = _carro()
    r = vendas.registrar_venda(1, LEAD, carro, HOJE, "financiado", meses_financiamento=48,
                               vendedor="Ana", agora=AGORA)
    l = _registros("registrar_venda")[0]
    assert l["alvo"] == f"lead:{LEAD}"
    assert json.loads(l["antes"])["status_do_carro"] == "disponivel"
    depois = json.loads(l["depois"])
    assert depois["venda_id"] == r["venda_id"]
    assert depois["carro"] == "Hyundai HB20 2020"
    assert depois["meses"] == 48 and depois["data_venda"] == "2026-10-30"


def test_importar_grava_as_contagens():
    r = _importar()
    l = _registros("importar_base")[0]
    d = json.loads(l["depois"])
    assert l["alvo"] == f"importacao:{r['importacao_id']}"
    assert d["contatos_novos"] == 2 and d["compras_novas"] == 1 and d["consentimento"] is True


def test_montar_fila_grava_o_resumo():
    _prep_base_ligada()
    reativacao.montar_fila(1, usuario="Ana", agora=AGORA, meses=6)
    d = json.loads(_registros("montar_fila_reativacao")[0]["depois"])
    assert d["na_fila"] == 2 and d["meses"] == 6 and d["publico"] == "todos"


def test_bloqueio_repetido_nao_grava_de_novo():
    bloqueios.bloquear(1, LEAD, "todos", None, "Ana")
    bloqueios.bloquear(1, LEAD, "todos", None, "Ana")
    assert len(_registros("bloquear_envio")) == 1


def test_desfazer_duas_vezes_grava_uma():
    bid = bloqueios.bloquear(1, LEAD, "todos", None, "Ana")
    assert bloqueios.desfazer(1, bid, "Ana") is True
    assert bloqueios.desfazer(1, bid, "Ana") is False
    assert len(_registros("desfazer_bloqueio")) == 1


# ------------------------------------------------------------ duas lojas

def test_ator_da_loja_1_nao_bloqueia_na_loja_2():
    loja2 = criar_loja("Loja 2")
    with como("Ana", "cliente", "painel", loja_id=1):
        with pytest.raises(AtorInvalido):
            bloqueios.bloquear(loja2, LEAD, "todos", None, "Ana")
        bloqueios.bloquear(1, LEAD, "todos", None, "Ana")
    assert _um("SELECT COUNT(*) FROM bloqueios_envio WHERE loja_id = ?", (loja2,)) == 0
    l = _registros("bloquear_envio")[0]
    assert (l["pessoa"], l["papel"], l["loja_id"]) == ("Ana", "cliente", 1)


def test_ator_da_loja_1_nao_pausa_a_loja_2():
    loja2 = criar_loja("Loja 2")
    with como("Ana", "cliente", "painel", loja_id=1):
        with pytest.raises(AtorInvalido):
            pausa.pausar(loja2, usuario="Ana", papel="cliente")
    assert pausa.pausado(loja2) is False


# ------------------------------------------------------------ telas

def test_entradas_definem_o_ator_antes_da_pagina():
    for nome in ("operador.py", "painel.py"):
        texto = (RAIZ / nome).read_text(encoding="utf-8")
        assert "definir_ator_da_sessao()" in texto
        assert texto.index("definir_ator_da_sessao()") < texto.index("navegacao.run()")

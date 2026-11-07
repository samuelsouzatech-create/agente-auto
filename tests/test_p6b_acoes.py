"""
P6b/P6c/P7a do Plano Mestre: as ações relevantes deixam rastro (quem, quando, antes e depois).
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
from app import (autenticacao, bloqueios, estado_loja, handoff, implantacao, importacao,
                 lojas_admin, pausa, reativacao, vendas)
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


def _prep_handoff():
    """O Léo passou a conversa (handoff esperando vendedor)."""
    conexao = conectar()
    try:
        conexao.execute(
            "INSERT INTO handoffs (loja_id, lead_id, motivo, resumo, estado) "
            "VALUES (1, ?, 'teste', '', 'aguardando_humano')", (LEAD,))
        conexao.commit()
    finally:
        conexao.close()
    return {}


def _prep_loja_em_teste():
    """A loja 1 entrou no ar na migração 11; aqui volta a 'em teste' só para o cenário."""
    conexao = conectar()
    try:
        conexao.execute("DELETE FROM estado_lojas WHERE loja_id = 1")
        conexao.commit()
    finally:
        conexao.close()
    return {}


SENHA_BOA = "Carro-Azul-2026"


def _prep_usuario_antigo():
    """Usuário de antes do P8: sem e-mail e sem senha."""
    from app.usuarios import criar_usuario
    return {"id": criar_usuario(1, "Ana", "vendedor")}


def _prep_item_marcado():
    """S2: item manual já marcado, para o cenário de desmarcar."""
    implantacao.marcar_item(1, "teste_conversa")
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
    # P6c
    "assumir_atendimento": (
        _prep_handoff,
        lambda s: handoff.assumir_handoff(LEAD, "Ana", 1),
        "SELECT COUNT(*) FROM handoffs WHERE estado = 'humano_assumiu'"),
    "assumir_conversa": (
        _prep_nada,
        lambda s: handoff.assumir_conversa(LEAD, "Ana", 1),
        "SELECT COUNT(*) FROM handoffs WHERE estado = 'humano_assumiu'"),
    "devolver_ao_agente": (
        _prep_handoff,
        lambda s: handoff.devolver_ao_agente(LEAD, 1),
        "SELECT COUNT(*) FROM handoffs WHERE estado = 'encerrado'"),
    "salvar_configuracao": (
        _prep_nada,
        lambda s: salvar_config(1, {"cidade": "Recife"}, "Ana", papel="cliente"),
        "SELECT COUNT(*) FROM config_historico"),
    # P7a
    "colocar_no_ar": (
        _prep_loja_em_teste,
        lambda s: estado_loja.colocar_no_ar(1, agora=AGORA),
        "SELECT COUNT(*) FROM estado_lojas WHERE loja_id = 1 AND estado = 'no_ar'"),
    # P8
    "criar_acesso": (
        _prep_nada,
        lambda s: autenticacao.criar_usuario_com_login(1, "Ana", "vendedor", "ana@loja.com", SENHA_BOA),
        "SELECT COUNT(*) FROM usuarios WHERE email IS NOT NULL"),
    "definir_email_acesso": (
        _prep_usuario_antigo,
        lambda s: autenticacao.definir_email(s["id"], "ana@loja.com"),
        "SELECT COUNT(*) FROM usuarios WHERE email IS NOT NULL"),
    "redefinir_senha": (
        _prep_usuario_antigo,
        lambda s: autenticacao.definir_senha(s["id"], SENHA_BOA),
        "SELECT COUNT(*) FROM usuarios WHERE senha_hash IS NOT NULL"),
    # S2
    "criar_loja": (
        _prep_nada,
        lambda s: lojas_admin.criar_loja("Loja Nova", "Caruaru", "America/Recife", "veiculos"),
        "SELECT COUNT(*) FROM lojas"),
    "marcar_item_implantacao": (
        _prep_nada,
        lambda s: implantacao.marcar_item(1, "teste_conversa"),
        "SELECT COUNT(*) FROM checklist_implantacao"),
    "desmarcar_item_implantacao": (
        _prep_item_marcado,
        lambda s: implantacao.desmarcar_item(1, "teste_conversa"),
        "SELECT -COUNT(*) FROM checklist_implantacao"),   # desmarcar tira a linha
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
    resultado = executar(estado)
    assert _um(efeito) > antes
    linhas = _registros(acao)
    if acao in HISTORICO_PROPRIO:
        assert linhas == []                       # não duplica: já tem histórico próprio
        return
    assert len(linhas) == 1
    l = linhas[0]
    # A função recebeu "Ana"; quem fica no Registro é o ATOR ("Teste").
    # S2: criar_loja grava na loja que acabou de nascer; as outras, na loja 1.
    # S8: preço e recálculo valem para todas as lojas: Registro sem loja.
    if acao in ("cadastrar_preco", "apagar_preco", "recalcular_custos"):
        loja_esperada = None
    else:
        loja_esperada = resultado if acao == "criar_loja" else 1
    assert (l["pessoa"], l["papel"], l["origem"], l["loja_id"]) == (
        "Teste", "operador", "painel", loja_esperada)
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


# ------------------------------------------------------------ S4b
from app import canais as _canais, usuarios as _usuarios


def _prep_pessoa():
    return {"id": _usuarios.criar_usuario(1, "Ana", "vendedor")}


def _prep_pessoa_desativada():
    estado = _prep_pessoa()
    _usuarios.definir_ativo(estado["id"], 1, False)
    return estado


def _prep_canal():
    _canais.cadastrar_canal(1, "telegram", "777")
    return {"id": _canais.listar_canais(1)[0]["id"]}


def _prep_numero():
    return {"id": estado_loja.cadastrar_numero_de_teste(1, "telegram", "123456", "Ana")}


CENARIOS.update({
    "criar_pessoa_equipe": (
        _prep_nada, lambda s: _usuarios.criar_usuario(1, "Ana", "vendedor"),
        "SELECT COUNT(*) FROM usuarios"),
    "alterar_pessoa_equipe": (
        _prep_pessoa, lambda s: _usuarios.atualizar_usuario(s["id"], 1, "Ana Maria", "vendedor"),
        "SELECT COUNT(*) FROM usuarios WHERE nome = 'Ana Maria'"),
    "desativar_pessoa_equipe": (
        _prep_pessoa, lambda s: _usuarios.definir_ativo(s["id"], 1, False),
        "SELECT COUNT(*) FROM usuarios WHERE ativo = 0"),
    "reativar_pessoa_equipe": (
        _prep_pessoa_desativada, lambda s: _usuarios.definir_ativo(s["id"], 1, True),
        "SELECT COUNT(*) FROM usuarios WHERE ativo = 1"),
    "cadastrar_canal": (
        _prep_nada, lambda s: _canais.cadastrar_canal(1, "telegram", "777"),
        "SELECT COUNT(*) FROM canais"),
    "desativar_canal": (
        _prep_canal, lambda s: _canais.desativar_canal_da_loja(1, s["id"]),
        "SELECT COUNT(*) FROM canais WHERE ativo = 0"),
    "cadastrar_numero_teste": (
        _prep_nada,
        lambda s: estado_loja.cadastrar_numero_de_teste(1, "telegram", "123456", "Ana"),
        "SELECT COUNT(*) FROM numeros_de_teste"),
    "desativar_numero_teste": (
        _prep_numero, lambda s: estado_loja.desativar_numero_de_teste(1, s["id"]),
        "SELECT COUNT(*) FROM numeros_de_teste WHERE ativo = 0"),
})


# ------------------------------------------------------------ S4c: Estoque e Conhecimento
from app import conhecimento as _conhecimento, estoque as _estoque


class _IndiceFalsoS4c:
    def get(self, where):
        return {"ids": []}

    def delete(self, ids):
        pass

    def add_texts(self, texts, metadatas, ids):
        pass


@pytest.fixture(autouse=True)
def _indice_falso_s4c(monkeypatch):
    monkeypatch.setattr(_conhecimento, "_indice", lambda: _IndiceFalsoS4c())


def _prep_documento():
    return {"doc": _conhecimento.salvar_documento(1, "Troca", "Aceitamos troca.")}


CENARIOS.update({
    "cadastrar_carro": (
        _prep_nada,
        lambda s: _estoque.adicionar_carro("Fiat", "Argo", 2021, 30000, "Prata", "Manual",
                                           62000.0, loja_id=1),
        "SELECT COUNT(*) FROM estoque"),
    "alterar_carro": (
        _prep_carro,
        lambda s: _estoque.atualizar_carro(s["carro"], "Hyundai", "HB20", 2020, 40000, "Prata",
                                           "Manual", 59000.0, "disponivel", loja_id=1),
        "SELECT COUNT(*) FROM estoque WHERE preco = 59000"),
    "criar_documento": (
        _prep_nada,
        lambda s: _conhecimento.salvar_documento(1, "Troca", "Aceitamos troca."),
        "SELECT COUNT(*) FROM conhecimento"),
    "alterar_documento": (
        _prep_documento,
        lambda s: _conhecimento.salvar_documento(1, "Troca", "Não aceitamos.", s["doc"]),
        "SELECT COUNT(*) FROM conhecimento WHERE texto = 'Não aceitamos.'"),
    "apagar_documento": (
        _prep_documento,
        lambda s: _conhecimento.apagar_documento(1, s["doc"]),
        "SELECT -COUNT(*) FROM conhecimento"),
})


# ------------------------------------------------------------ S8: Custos e preços
from app import custos as _custos, custos_precos as _custos_precos, precos as _precos


def _prep_preco():
    _precos.cadastrar_preco("ia.entrada", 0.10, "2026-01-01", "USD")
    return {"id": _precos.listar_precos()[0]["id"]}


def _prep_custo_sem_preco():
    _custos.registrar_uso(1, LEAD, "simulador", _custos.Uso(1000, 100), agora=AGORA)
    _precos.cadastrar_preco("ia.entrada", 0.10, "2026-01-01", "USD")
    _precos.cadastrar_preco("ia.saida", 0.40, "2026-01-01", "USD")
    _precos.cadastrar_preco("cambio.usd_brl", 5.0, "2026-01-01")
    return {}


CENARIOS.update({
    "cadastrar_preco": (
        _prep_nada,
        lambda s: _custos_precos.cadastrar_preco("ia.saida", 0.40, "2026-01-01", "USD"),
        "SELECT COUNT(*) FROM precos"),
    "apagar_preco": (
        _prep_preco, lambda s: _custos_precos.apagar_preco(s["id"]),
        "SELECT -COUNT(*) FROM precos"),
    "recalcular_custos": (
        _prep_custo_sem_preco,
        lambda s: _custos_precos.recalcular_periodo(date(2026, 10, 1), date(2026, 10, 31)),
        "SELECT COUNT(*) FROM uso_custos WHERE custo_completo = 1"),
})

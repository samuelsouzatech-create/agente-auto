"""
P6c do Plano Mestre: handoff (assumir/devolver), configuração e canal sem cadastro.
- tentativa que não muda nada não grava no Registro;
- assumir_conversa com handoff aberto grava UMA vez (como assumir_atendimento);
- ator do painel da loja não salva campo do operador nem mexe em outra loja;
- canal sem cadastro vai para o Registro (sem loja, ator de sistema) e nunca derruba nada;
- a Fila de handoff define o ator dentro do pedaço que se atualiza sozinho.
Tudo offline, banco temporário do conftest (ator "Teste", operador, painel).
"""
import importlib
import json
import sqlite3
from pathlib import Path

import pytest

from banco import conectar
from app import logs
from app.ator import AtorInvalido, ator_atual, como
from app.handoff import assumir_conversa, assumir_handoff, devolver_ao_agente, estado_do_handoff
from app.lojas import SemPermissao, carregar_loja, criar_loja, salvar_config
from app.registro import ACOES_RELEVANTES, EVENTOS_DE_SISTEMA

RAIZ = Path(__file__).resolve().parent.parent
LEAD = "5581999990000"


def _registros(acao):
    conexao = conectar()
    try:
        return [dict(l) for l in conexao.execute(
            "SELECT * FROM registro_acoes WHERE acao = ? ORDER BY id", (acao,))]
    finally:
        conexao.close()


def _handoff_aguardando(loja_id=1):
    conexao = conectar()
    try:
        conexao.execute(
            "INSERT INTO handoffs (loja_id, lead_id, motivo, resumo, estado) "
            "VALUES (?, ?, 'teste', '', 'aguardando_humano')", (loja_id, LEAD))
        conexao.commit()
    finally:
        conexao.close()


# ------------------------------------------------------------ handoff

def test_assumir_grava_antes_e_depois():
    _handoff_aguardando()
    assert assumir_handoff(LEAD, "Ana", 1) == "Lead assumido por Ana."
    l = _registros("assumir_atendimento")[0]
    assert l["alvo"] == f"lead:{LEAD}"
    assert json.loads(l["antes"]) == {"estado": "aguardando_humano", "vendedor": None}
    d = json.loads(l["depois"])
    assert d["estado"] == "humano_assumiu" and d["vendedor"] == "Ana" and d["handoff_id"]


def test_assumir_de_novo_pelo_mesmo_vendedor_nao_grava():
    _handoff_aguardando()
    assumir_handoff(LEAD, "Ana", 1)
    assert assumir_handoff(LEAD, "Ana", 1) == "Lead já estava com você, Ana."
    assert len(_registros("assumir_atendimento")) == 1


def test_assumir_o_que_outro_ja_assumiu_nao_grava():
    _handoff_aguardando()
    assumir_handoff(LEAD, "Ana", 1)
    assert assumir_handoff(LEAD, "Bia", 1) == "Lead já assumido por Ana."
    assert len(_registros("assumir_atendimento")) == 1


def test_assumir_conversa_com_handoff_aberto_grava_uma_vez_so():
    _handoff_aguardando()
    assert assumir_conversa(LEAD, "Ana", 1) == "Lead assumido por Ana."
    assert len(_registros("assumir_atendimento")) == 1
    assert _registros("assumir_conversa") == []


def test_devolver_sem_handoff_nao_grava():
    assert devolver_ao_agente(LEAD, 1) == "Nenhum handoff aberto para devolver."
    assert _registros("devolver_ao_agente") == []


def test_ator_da_loja_1_nao_assume_na_loja_2():
    loja2 = criar_loja("Loja 2")
    _handoff_aguardando(loja2)
    with como("Ana", "cliente", "painel", loja_id=1):
        with pytest.raises(AtorInvalido):
            assumir_handoff(LEAD, "Ana", loja2)
    assert estado_do_handoff(LEAD, loja2) == "aguardando_humano"
    assert _registros("assumir_atendimento") == []


# ------------------------------------------------------------ configuração

def test_ator_cliente_nao_salva_campo_do_operador():
    with como("Ana", "cliente", "painel", loja_id=1):
        with pytest.raises(SemPermissao):
            salvar_config(1, {"modulos.remarketing": True}, "Ana", papel="operador")
        # O campo da própria loja ele salva normalmente.
        salvar_config(1, {"cidade": "Recife"}, "Ana", papel="operador")
    loja = carregar_loja(1)
    assert loja.get("modulos.remarketing") is False
    assert loja.get("cidade") == "Recife"


def test_ator_da_loja_1_nao_salva_config_da_loja_2():
    loja2 = criar_loja("Loja 2")
    with como("Ana", "cliente", "painel", loja_id=1):
        with pytest.raises(AtorInvalido):
            salvar_config(loja2, {"cidade": "Olinda"}, "Ana", papel="cliente")
    assert carregar_loja(loja2).get("cidade") == ""


# ------------------------------------------------------------ canal sem cadastro

def test_canal_sem_cadastro_vai_para_o_registro():
    assert logs.registrar_canal_desconhecido("telegram", "123") is True
    l = _registros("mensagem_canal_sem_cadastro")[0]
    assert l["loja_id"] is None
    assert (l["pessoa"], l["papel"], l["origem"]) == ("Sistema", "sistema", "webhook")
    assert l["alvo"] == "canal:telegram:123"
    assert json.loads(l["depois"]) == {"tipo_canal": "telegram", "id_externo": "123"}


def test_canal_sem_cadastro_continua_no_arquivo():
    logs.registrar_canal_desconhecido("whatsapp", "999")
    with open(logs.caminho_recusadas(), encoding="utf-8") as arquivo:
        assert "canal_sem_cadastro" in arquivo.read()


def test_canal_sem_cadastro_nao_quebra_se_o_banco_falhar(monkeypatch):
    def banco_fora():
        raise sqlite3.OperationalError("banco fora do ar")
    monkeypatch.setattr("app.registro.conectar", banco_fora)
    assert logs.registrar_canal_desconhecido("telegram", "123") is True
    assert _registros("mensagem_canal_sem_cadastro") == []


def test_canal_sem_cadastro_devolve_o_ator_anterior():
    logs.registrar_canal_desconhecido("telegram", "123")
    assert ator_atual().pessoa == "Teste"


def test_eventos_de_sistema_existem_e_nao_sao_acoes_de_pessoa():
    for acao, caminho in EVENTOS_DE_SISTEMA.items():
        assert acao not in ACOES_RELEVANTES
        modulo, _, nome = caminho.rpartition(".")
        assert callable(getattr(importlib.import_module(modulo), nome))


# ------------------------------------------------------------ tela

def test_fila_de_handoff_define_o_ator_dentro_do_fragmento():
    texto = (RAIZ / "paginas" / "handoff.py").read_text(encoding="utf-8")
    corpo = texto.split("def mostrar_fila", 1)[1]
    assert "definir_ator_da_sessao()" in corpo
    assert corpo.index("definir_ator_da_sessao()") < corpo.index("assumir_handoff(")

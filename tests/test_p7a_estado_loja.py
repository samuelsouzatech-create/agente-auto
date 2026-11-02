"""
P7a do Plano Mestre: estado da loja (Em teste e No ar).
- migração 11: tabela estado_lojas; lojas que já existiam entram no ar;
  loja nova nasce em teste; rodar a migração de novo não muda ninguém;
- só o operador coloca no ar, e isso vai para o Registro;
- terceira trava: loja em teste não envia de verdade nem com as duas chaves
  (nem com 'forcado');
- números de teste: só valem na loja deles; WhatsApp normalizado;
- duas lojas em estados diferentes.
Tudo offline, banco temporário do conftest (ator "Teste", operador, painel).
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

import banco
from banco import conectar
from app import modo_envio
from app import painel_envios as pe
from app.ator import SemAtor, como, sem_ator
from app.estado_loja import (
    NumeroInvalido, SoOperador, cadastrar_numero_de_teste, colocar_no_ar,
    desativar_numero_de_teste, estado_da_loja, listar_numeros_de_teste, pode_responder,
    situacao_da_loja,
)
from app.lojas import carregar_loja, criar_loja, salvar_config
from app.registro import ACOES_RELEVANTES
from app.registro_leitura import ROTULOS

RAIZ = Path(__file__).resolve().parent.parent
AGORA = datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc)
TIPOS = ("remarketing", "pos_venda", "reativacao")


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


def _duas_chaves(monkeypatch, *lojas_ids):
    for var in modo_envio.VARIAVEIS.values():
        monkeypatch.setenv(var, "1")
    for loja_id in lojas_ids:
        salvar_config(loja_id, {f"envio_real.{t}": True for t in TIPOS}, "Samuel")


# ------------------------------------------------------------ migração

def test_migracao_11_cria_as_tabelas():
    assert banco.VERSAO_SCHEMA >= 11
    for tabela in ("estado_lojas", "numeros_de_teste"):
        assert _um("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
                   (tabela,)) == 1


def test_sobe_da_v10_e_lojas_existentes_ficam_no_ar(monkeypatch, tmp_path):
    monkeypatch.setattr(banco, "CAMINHO_BANCO", str(tmp_path / "v10.db"))
    completas = dict(banco.MIGRACOES)
    monkeypatch.setattr(banco, "MIGRACOES", {v: s for v, s in completas.items() if v <= 10})
    banco.criar_tabelas()
    conexao = conectar()
    try:
        conexao.execute("INSERT INTO lojas (nome, segmento, config) VALUES ('Loja 2', 'veiculos', '{}')")
        conexao.execute("INSERT INTO pausas_envio (loja_id, acao, usuario, papel) "
                        "VALUES (1, 'pausar', 'Ana', 'cliente')")
        conexao.commit()
        assert conexao.execute("PRAGMA user_version").fetchone()[0] == 10
    finally:
        conexao.close()

    monkeypatch.setattr(banco, "MIGRACOES", completas)
    banco.migrar()
    assert _um("PRAGMA user_version") == banco.VERSAO_SCHEMA
    assert _um("SELECT COUNT(*) FROM lojas") == 2
    assert _um("SELECT COUNT(*) FROM estado_lojas WHERE estado = 'no_ar' "
               "AND no_ar_em IS NOT NULL") == 2
    assert _um("SELECT COUNT(*) FROM pausas_envio") == 1


def test_migracao_11_pode_rodar_de_novo_sem_mudar_o_estado():
    loja2 = criar_loja("Loja 2")                 # nasce em teste
    conexao = conectar()
    try:
        conexao.execute("PRAGMA user_version = 10")
        conexao.commit()
    finally:
        conexao.close()
    banco.migrar()                               # não pode quebrar
    assert _um("PRAGMA user_version") == banco.VERSAO_SCHEMA
    assert estado_da_loja(loja2) == "em_teste"   # não virou 'no ar' na repetição
    assert estado_da_loja(1) == "no_ar"


def test_loja_nova_nasce_em_teste():
    loja2 = criar_loja("Loja 2")
    s = situacao_da_loja(loja2)
    assert (s["estado"], s["rotulo"], s["no_ar_em"]) == ("em_teste", "Em teste", None)
    assert estado_da_loja(1) == "no_ar"


def test_estado_invalido_e_recusado_pelo_banco():
    conexao = conectar()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conexao.execute("UPDATE estado_lojas SET estado = 'desligada' WHERE loja_id = 1")
    finally:
        conexao.close()


# ------------------------------------------------------------ colocar no ar

def test_colocar_no_ar_grava_estado_e_registro():
    loja2 = criar_loja("Loja 2")
    assert colocar_no_ar(loja2, agora=AGORA) is True
    s = situacao_da_loja(loja2)
    assert (s["estado"], s["no_ar_em"], s["alterado_por"]) == ("no_ar", "2026-11-03 13:00:00", "Teste")
    linhas = _registros("colocar_no_ar")
    assert len(linhas) == 1
    l = linhas[0]
    assert (l["pessoa"], l["papel"], l["loja_id"], l["alvo"]) == ("Teste", "operador", loja2, "loja")
    assert json.loads(l["antes"]) == {"estado": "em_teste"}
    assert json.loads(l["depois"])["estado"] == "no_ar"


def test_colocar_no_ar_duas_vezes_grava_uma():
    loja2 = criar_loja("Loja 2")
    assert colocar_no_ar(loja2) is True
    assert colocar_no_ar(loja2) is False
    assert colocar_no_ar(1) is False          # já entrou no ar na migração
    assert len(_registros("colocar_no_ar")) == 1


def test_cliente_nao_coloca_no_ar():
    loja2 = criar_loja("Loja 2")
    with como("Ana", "cliente", "painel", loja_id=loja2):
        with pytest.raises(SoOperador):
            colocar_no_ar(loja2)
    assert estado_da_loja(loja2) == "em_teste"
    assert _registros("colocar_no_ar") == []


def test_sem_ator_nao_coloca_no_ar():
    loja2 = criar_loja("Loja 2")
    with sem_ator(), pytest.raises(SemAtor):
        colocar_no_ar(loja2)
    assert estado_da_loja(loja2) == "em_teste"
    assert _registros("colocar_no_ar") == []


def test_duas_lojas_em_estados_diferentes():
    loja2, loja3 = criar_loja("Loja 2"), criar_loja("Loja 3")
    colocar_no_ar(loja2)
    assert (estado_da_loja(1), estado_da_loja(loja2), estado_da_loja(loja3)) == (
        "no_ar", "no_ar", "em_teste")


def test_colocar_no_ar_esta_na_lista_e_tem_rotulo():
    assert ACOES_RELEVANTES["colocar_no_ar"] == "app.estado_loja.colocar_no_ar"
    assert ROTULOS["colocar_no_ar"] == "Colocou a loja no ar"


# ------------------------------------------------------------ terceira trava

def test_loja_em_teste_nao_envia_nem_com_as_duas_chaves(monkeypatch):
    loja2 = criar_loja("Loja 2")
    _duas_chaves(monkeypatch, 1, loja2)
    for t in TIPOS:
        assert modo_envio.real_para(carregar_loja(loja2), t) is False
        assert modo_envio.situacao(carregar_loja(loja2), t) == "loja_em_teste"
        assert modo_envio.real_para(carregar_loja(1), t) is True
        assert modo_envio.situacao(carregar_loja(1), t) == "real"


def test_forcado_nao_passa_por_cima_da_loja_em_teste():
    loja2 = criar_loja("Loja 2")
    assert modo_envio.real_para(carregar_loja(loja2), "pos_venda", True) is False
    assert modo_envio.real_para(carregar_loja(1), "pos_venda", True) is True


def test_depois_de_colocar_no_ar_envia(monkeypatch):
    loja2 = criar_loja("Loja 2")
    _duas_chaves(monkeypatch, loja2)
    colocar_no_ar(loja2)
    assert modo_envio.real_para(carregar_loja(loja2), "remarketing") is True
    assert modo_envio.situacao(carregar_loja(loja2), "remarketing") == "real"


def test_tela_tem_rotulo_para_loja_em_teste(monkeypatch):
    loja2 = criar_loja("Loja 2")
    _duas_chaves(monkeypatch, loja2)
    assert pe.situacao_do_modo(carregar_loja(loja2))["remarketing"] == "loja_em_teste"
    assert pe.ROTULOS_MODO["loja_em_teste"] == "Bloqueado: loja em teste"
    assert pe.modo_de_envio(carregar_loja(loja2))["remarketing"] is False


# ------------------------------------------------------------ números de teste

def test_simulador_sempre_responde():
    loja2 = criar_loja("Loja 2")
    assert pode_responder(loja2, "simulador", "qualquer") is True


def test_loja_no_ar_responde_a_todos():
    assert pode_responder(1, "telegram", "999") is True
    assert pode_responder(1, "whatsapp", "5581988887777") is True


def test_loja_em_teste_so_responde_ao_numero_de_teste():
    loja2 = criar_loja("Loja 2")
    cadastrar_numero_de_teste(loja2, "telegram", " 123456 ", "Samuel")
    assert pode_responder(loja2, "telegram", "123456") is True
    assert pode_responder(loja2, "telegram", "654321") is False
    assert pode_responder(loja2, "whatsapp", "123456") is False


def test_whatsapp_com_ou_sem_o_9_e_o_mesmo_numero():
    loja2 = criar_loja("Loja 2")
    cadastrar_numero_de_teste(loja2, "whatsapp", "(81) 99999-0000", "Samuel")
    assert pode_responder(loja2, "whatsapp", "558199990000") is True     # como o WhatsApp manda
    assert pode_responder(loja2, "whatsapp", "5581999990000") is True
    assert pode_responder(loja2, "whatsapp", "5581999991111") is False


def test_numero_desativado_nao_responde_e_recadastro_reativa():
    loja2 = criar_loja("Loja 2")
    nid = cadastrar_numero_de_teste(loja2, "telegram", "123456")
    assert desativar_numero_de_teste(loja2, nid) is True
    assert desativar_numero_de_teste(loja2, nid) is False
    assert pode_responder(loja2, "telegram", "123456") is False
    assert cadastrar_numero_de_teste(loja2, "telegram", "123456", "Samuel") == nid
    assert pode_responder(loja2, "telegram", "123456") is True


def test_numero_de_uma_loja_nao_vale_na_outra():
    loja2, loja3 = criar_loja("Loja 2"), criar_loja("Loja 3")
    nid = cadastrar_numero_de_teste(loja2, "telegram", "123456")
    assert pode_responder(loja3, "telegram", "123456") is False
    assert desativar_numero_de_teste(loja3, nid) is False
    assert pode_responder(loja2, "telegram", "123456") is True


@pytest.mark.parametrize("tipo, numero", [("sms", "123"), ("whatsapp", "12"), ("telegram", "   ")])
def test_numero_invalido(tipo, numero):
    loja2 = criar_loja("Loja 2")
    with pytest.raises(NumeroInvalido):
        cadastrar_numero_de_teste(loja2, tipo, numero)


def test_cliente_nao_cadastra_numero_de_teste():
    loja2 = criar_loja("Loja 2")
    with como("Ana", "cliente", "painel", loja_id=loja2):
        with pytest.raises(SoOperador):
            cadastrar_numero_de_teste(loja2, "telegram", "123456")
    assert listar_numeros_de_teste(loja2) == []


def test_listar_numeros():
    loja2 = criar_loja("Loja 2")
    cadastrar_numero_de_teste(loja2, "telegram", "111", "Samuel")
    nid = cadastrar_numero_de_teste(loja2, "telegram", "222", "Ana")
    desativar_numero_de_teste(loja2, nid)
    assert [n["id_externo"] for n in listar_numeros_de_teste(loja2)] == ["111"]
    assert len(listar_numeros_de_teste(loja2, so_ativos=False)) == 2


def test_estado_loja_sem_streamlit():
    texto = (RAIZ / "app" / "estado_loja.py").read_text(encoding="utf-8")
    assert "import streamlit" not in texto
    assert "from paginas" not in texto

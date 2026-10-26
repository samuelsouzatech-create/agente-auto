"""Etapa 1, Bloco 1: migração, lead único por loja e configuração por loja."""
import json
import sqlite3

import pytest

import banco
from app import lojas
from app.lojas import (
    PADROES, ConfigInvalida, carregar_loja, criar_loja, historico_config,
    modulo_ativo, pendentes, salvar_config,
)


def _sem_meta(config):
    return {k: v for k, v in config.items() if not k.startswith("_")}


# ---------- Migração ----------

def test_migracao_cria_tabelas_e_semeia_loja_1():
    con = banco.conectar()
    assert banco.versao_schema(con) == banco.VERSAO_SCHEMA
    tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    for t in ("lojas", "canais", "usuarios", "optouts", "uso_custos",
              "precos", "conhecimento", "config_historico"):
        assert t in tabelas
    loja = carregar_loja(1)
    assert loja.segmento == "veiculos" and loja.ativo


def test_migracao_pode_rodar_varias_vezes():
    banco.criar_tabelas()
    banco.criar_tabelas()
    con = banco.conectar()
    assert con.execute("SELECT COUNT(*) FROM lojas").fetchone()[0] == 1
    con.close()


def test_mesmo_telefone_em_duas_lojas_vira_dois_leads():
    loja_b = criar_loja("Loja B")
    con = banco.conectar()
    con.execute("INSERT INTO leads (lead_id, loja_id, nome) VALUES ('5581', 1, 'Ana')")
    con.execute("INSERT INTO leads (lead_id, loja_id, nome) VALUES ('5581', ?, 'Ana')", (loja_b,))
    con.commit()
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO leads (lead_id, loja_id) VALUES ('5581', 1)")
    con.close()


def test_migracao_preserva_os_dados_do_banco_antigo(tmp_path, monkeypatch):
    caminho = tmp_path / "antigo.db"
    con = sqlite3.connect(caminho)
    con.execute("""CREATE TABLE leads (id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id TEXT UNIQUE, loja_id INTEGER NOT NULL DEFAULT 1, nome TEXT,
        interesse TEXT, forma_pagamento TEXT, tem_troca TEXT, prazo TEXT,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    con.execute("INSERT INTO leads (lead_id, nome) VALUES ('5581999', 'Ana')")
    con.commit()
    con.close()

    monkeypatch.setattr(banco, "CAMINHO_BANCO", str(caminho))
    lojas.limpar_cache()
    banco.criar_tabelas()

    con = banco.conectar()
    lead = con.execute("SELECT * FROM leads WHERE lead_id = '5581999'").fetchone()
    assert lead["nome"] == "Ana" and lead["loja_id"] == 1
    con.execute("INSERT INTO lojas (id, nome) VALUES (2, 'B')")
    con.execute("INSERT INTO leads (lead_id, loja_id) VALUES ('5581999', 2)")  # não pode falhar
    con.commit()
    con.close()


# ---------- Configuração ----------

def test_config_vazia_usa_todos_os_padroes():
    assert _sem_meta(carregar_loja(1).config) == PADROES


def test_config_parcial_e_completada_com_padroes():
    con = banco.conectar()
    con.execute("UPDATE lojas SET config = ?, versao_config = versao_config + 1 WHERE id = 1",
                (json.dumps({"financiamento": {"taxa_mensal": 0.025}}),))
    con.commit()
    con.close()
    loja = carregar_loja(1)
    assert loja.get("financiamento.taxa_mensal") == 0.025
    assert loja.get("remarketing.max_toques") == 3


def test_config_corrompida_nao_derruba():
    con = banco.conectar()
    con.execute("UPDATE lojas SET config = 'isso não é json', versao_config = 9 WHERE id = 1")
    con.commit()
    con.close()
    assert _sem_meta(carregar_loja(1).config) == PADROES


@pytest.mark.parametrize("valor", [0, 4, 10, True, "3"])
def test_max_toques_fora_da_faixa_e_recusado(valor):
    with pytest.raises(ConfigInvalida):
        salvar_config(1, {"remarketing.max_toques": valor}, "teste")


@pytest.mark.parametrize("faixa", ["02:00-05:00", "19:00-09:00", "9h-19h", "07:00-19:00"])
def test_horario_de_envio_invalido_e_recusado(faixa):
    with pytest.raises(ConfigInvalida):
        salvar_config(1, {"remarketing.horario_envio": faixa}, "teste")


def test_regra_de_produto_nao_e_editavel():
    with pytest.raises(ConfigInvalida, match="regra do produto"):
        salvar_config(1, {"atendimento.max_bolhas": 5}, "teste")


def test_chave_desconhecida_e_recusada():
    with pytest.raises(ConfigInvalida, match="desconhecida"):
        salvar_config(1, {"desconto_maximo": 0.1}, "teste")


def test_um_erro_impede_a_gravacao_de_tudo():
    antes = carregar_loja(1)
    with pytest.raises(ConfigInvalida):
        salvar_config(1, {"nome_agente": "Bia", "remarketing.max_toques": 9}, "teste")
    depois = carregar_loja(1)
    assert depois.versao_config == antes.versao_config
    assert depois.get("nome_agente") == "Léo"
    assert historico_config(1) == []


def test_mudanca_vale_na_proxima_leitura_e_fica_no_historico():
    v1 = carregar_loja(1)
    salvar_config(1, {"financiamento.taxa_mensal": 0.022, "nome_agente": "Bia"}, "samuel")
    v2 = carregar_loja(1)
    assert v2.get("financiamento.taxa_mensal") == 0.022
    assert v2.get("nome_agente") == "Bia"
    assert v2.versao_config == v1.versao_config + 1
    hist = {h["chave"]: h for h in historico_config(1)}
    assert json.loads(hist["financiamento.taxa_mensal"]["valor_antigo"]) == 0.019
    assert json.loads(hist["financiamento.taxa_mensal"]["valor_novo"]) == 0.022
    assert hist["nome_agente"]["usuario"] == "samuel"


def test_duas_lojas_tem_configs_independentes():
    loja_b = criar_loja("Loja B", config={"financiamento.taxa_mensal": 0.03})
    assert carregar_loja(1).get("financiamento.taxa_mensal") == 0.019
    assert carregar_loja(loja_b).get("financiamento.taxa_mensal") == 0.03


def test_modulo_ativo_e_o_disjuntor():
    loja = carregar_loja(1)
    assert modulo_ativo(loja, "agendamento") is True
    assert modulo_ativo(loja, "remarketing") is False
    assert modulo_ativo(loja, "modulo_que_nao_existe") is False
    loja = salvar_config(1, {"modulos.remarketing": True}, "teste")
    assert modulo_ativo(loja, "remarketing") is True


def test_confirmar_o_padrao_tira_da_lista_de_pendentes():
    assert "remarketing.max_toques" in pendentes(carregar_loja(1))
    loja = salvar_config(1, {"remarketing.max_toques": 3}, "teste")  # mesmo valor do padrão
    assert "remarketing.max_toques" not in pendentes(loja)


def test_segmento_inexistente_e_recusado():
    with pytest.raises(ConfigInvalida):
        criar_loja("Clínica X", segmento="clinica")

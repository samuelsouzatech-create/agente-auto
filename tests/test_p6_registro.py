"""
P6a do Plano Mestre: a base do Registro (quem fez o quê).
- migração 10: tabela registro_acoes, sobe da v9 sem perder dado;
- app/ator.py: quem age vem do contexto (tela, API ou job), não de parâmetro;
- app/registro.py: sem ator, falha; com a conexão da ação, é atômico;
- ator de uma loja não grava na outra.
Tudo offline. O conftest define um ator de teste ("Teste", operador).
"""
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import banco
from banco import conectar
from app.ator import (
    AtorInvalido, SemAtor, ator_atual, como, como_sistema, definir_ator, exigir_ator, sem_ator,
)
from app.chaves import LojaNaoInformada
from app.lojas import criar_loja
from app.registro import RegistroInvalido, registrar

RAIZ = Path(__file__).resolve().parent.parent
AGORA = datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc)
LEAD = "5581999990000"
INSERIR_BLOQUEIO = ("INSERT INTO bloqueios_envio (loja_id, lead_id, tipo, criado_por) "
                    "VALUES (1, ?, 'todos', 'Teste')")


def _contar(sql, parametros=()):
    conexao = conectar()
    try:
        return conexao.execute(sql, parametros).fetchone()[0]
    finally:
        conexao.close()


def _linhas():
    conexao = conectar()
    try:
        return [dict(l) for l in conexao.execute("SELECT * FROM registro_acoes ORDER BY id")]
    finally:
        conexao.close()


# ------------------------------------------------------------ migração

def test_migracao_10_cria_a_tabela_e_o_indice():
    assert banco.VERSAO_SCHEMA == 10
    assert _contar("SELECT COUNT(*) FROM sqlite_master WHERE name = 'registro_acoes'") == 1
    assert _contar("SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' "
                   "AND name = 'idx_registro_loja'") == 1


def test_sobe_da_v9_sem_perder_dado(monkeypatch, tmp_path):
    monkeypatch.setattr(banco, "CAMINHO_BANCO", str(tmp_path / "v9.db"))
    completas = dict(banco.MIGRACOES)
    monkeypatch.setattr(banco, "MIGRACOES", {v: s for v, s in completas.items() if v <= 9})
    banco.criar_tabelas()
    conexao = conectar()
    try:
        conexao.execute(INSERIR_BLOQUEIO, (LEAD,))
        conexao.execute("INSERT INTO pausas_envio (loja_id, acao, usuario, papel) "
                        "VALUES (1, 'pausar', 'Ana', 'cliente')")
        conexao.commit()
        assert conexao.execute("PRAGMA user_version").fetchone()[0] == 9
    finally:
        conexao.close()

    monkeypatch.setattr(banco, "MIGRACOES", completas)
    banco.migrar()
    assert _contar("PRAGMA user_version") == 10
    assert _contar("SELECT COUNT(*) FROM bloqueios_envio") == 1
    assert _contar("SELECT COUNT(*) FROM pausas_envio") == 1
    assert _contar("SELECT COUNT(*) FROM registro_acoes") == 0


# ------------------------------------------------------------ ator

def test_conftest_define_ator_de_teste():
    a = exigir_ator()
    assert (a.pessoa, a.papel, a.origem, a.loja_id) == ("Teste", "operador", "painel", None)


def test_como_restaura_o_anterior():
    with como("Ana", "cliente", "painel", loja_id=1):
        assert ator_atual().pessoa == "Ana"
        with como_sistema("Relógio", "job"):
            assert ator_atual().papel == "sistema"
        assert ator_atual().pessoa == "Ana"
    assert ator_atual().pessoa == "Teste"


def test_sem_ator_falha():
    with sem_ator():
        assert ator_atual() is None
        with pytest.raises(SemAtor):
            exigir_ator()
    assert ator_atual().pessoa == "Teste"


def test_definir_ator_limpa_espacos():
    with sem_ator():
        definir_ator("  Samuel   Souza ", "operador", "painel")
        assert ator_atual().pessoa == "Samuel Souza"


@pytest.mark.parametrize("pessoa, papel, origem, loja", [
    ("", "operador", "painel", None),
    ("Ana", "gerente", "painel", None),        # papéis novos só no P8
    ("Ana", "operador", "telefone", None),
    ("Ana", "cliente", "painel", None),        # painel da loja sem loja
    ("A" * 81, "operador", "painel", None),
])
def test_ator_invalido(pessoa, papel, origem, loja):
    with pytest.raises(AtorInvalido):
        definir_ator(pessoa, papel, origem, loja_id=loja)


def test_ator_com_loja_invalida():
    with pytest.raises(LojaNaoInformada):
        definir_ator("Ana", "cliente", "painel", loja_id=0)


# ------------------------------------------------------------ registrar

def test_registrar_grava_quem_quando_antes_e_depois():
    registrar("salvar_configuracao", 1, {"a": 1}, {"a": 2}, alvo="config", agora=AGORA)
    linha = _linhas()[0]
    assert linha["pessoa"] == "Teste"
    assert linha["papel"] == "operador"
    assert linha["origem"] == "painel"
    assert linha["loja_id"] == 1
    assert linha["acao"] == "salvar_configuracao"
    assert linha["alvo"] == "config"
    assert linha["quando"] == "2026-11-03 13:00:00"
    assert json.loads(linha["antes"]) == {"a": 1}
    assert json.loads(linha["depois"]) == {"a": 2}


def test_sem_antes_ou_depois_fica_vazio():
    registrar("pausar_envios", 1, None, None)
    linha = _linhas()[0]
    assert linha["antes"] is None and linha["depois"] is None and linha["alvo"] is None


def test_texto_com_acento_fica_legivel():
    registrar("salvar_configuracao", 1, None, {"nome": "João"})
    assert "João" in _linhas()[0]["depois"]


def test_escrita_sem_ator_falha_e_nao_grava():
    with sem_ator(), pytest.raises(SemAtor):
        registrar("pausar_envios", 1, None, {"motivo": "teste"})
    assert _contar("SELECT COUNT(*) FROM registro_acoes") == 0


def test_registrar_nao_recebe_nome_de_pessoa():
    parametros = inspect.signature(registrar).parameters
    for proibido in ("pessoa", "usuario", "autor", "papel", "vendedor"):
        assert proibido not in parametros


def test_com_conexao_da_acao_so_vale_com_o_commit():
    conexao = conectar()
    try:
        conexao.execute(INSERIR_BLOQUEIO, (LEAD,))
        registrar("bloquear_envio", 1, None, {"tipo": "todos"}, conexao=conexao, alvo=f"lead:{LEAD}")
        assert _contar("SELECT COUNT(*) FROM registro_acoes") == 0    # ainda não confirmou
        conexao.commit()
    finally:
        conexao.close()
    assert _contar("SELECT COUNT(*) FROM bloqueios_envio") == 1
    assert _contar("SELECT COUNT(*) FROM registro_acoes") == 1


def test_desistir_desfaz_acao_e_registro():
    conexao = conectar()
    try:
        conexao.execute(INSERIR_BLOQUEIO, (LEAD,))
        registrar("bloquear_envio", 1, None, {"tipo": "todos"}, conexao=conexao)
    finally:
        conexao.close()     # fechou sem commit
    assert _contar("SELECT COUNT(*) FROM bloqueios_envio") == 0
    assert _contar("SELECT COUNT(*) FROM registro_acoes") == 0


def test_erro_no_meio_nao_deixa_acao_sem_registro():
    conexao = conectar()
    try:
        conexao.execute(INSERIR_BLOQUEIO, (LEAD,))
        with sem_ator(), pytest.raises(SemAtor):
            registrar("bloquear_envio", 1, None, {"tipo": "todos"}, conexao=conexao)
    finally:
        conexao.close()
    assert _contar("SELECT COUNT(*) FROM bloqueios_envio") == 0
    assert _contar("SELECT COUNT(*) FROM registro_acoes") == 0


def test_ator_de_uma_loja_nao_grava_na_outra():
    loja2 = criar_loja("Loja 2")
    with como("Ana", "cliente", "painel", loja_id=1):
        with pytest.raises(AtorInvalido):
            registrar("pausar_envios", loja2, None, None)
        with pytest.raises(AtorInvalido):
            registrar("canal_sem_cadastro", None, None, None)
        registrar("pausar_envios", 1, None, None)
    assert _contar("SELECT COUNT(*) FROM registro_acoes WHERE loja_id = ?", (loja2,)) == 0
    assert _contar("SELECT COUNT(*) FROM registro_acoes WHERE loja_id = 1") == 1


def test_operador_e_sistema_gravam_em_qualquer_loja_e_sem_loja():
    loja2 = criar_loja("Loja 2")
    registrar("pausar_envios", loja2, None, None)
    with como_sistema("Webhook", "webhook"):
        registrar("canal_sem_cadastro", None, None, {"canal": "telegram"}, alvo="canal:telegram:123")
    primeira, segunda = _linhas()
    assert primeira["loja_id"] == loja2 and primeira["papel"] == "operador"
    assert segunda["loja_id"] is None
    assert (segunda["pessoa"], segunda["papel"], segunda["origem"]) == ("Webhook", "sistema", "webhook")


@pytest.mark.parametrize("acao", ["", "Pausar", "pausar envios", "1pausar", None])
def test_acao_invalida(acao):
    with pytest.raises(RegistroInvalido):
        registrar(acao, 1, None, None)


def test_loja_invalida():
    with pytest.raises(LojaNaoInformada):
        registrar("pausar_envios", 0, None, None)


def test_alvo_longo_e_cortado():
    registrar("pausar_envios", 1, None, None, alvo="x" * 500)
    assert len(_linhas()[0]["alvo"]) == 120


def test_base_nao_importa_telas():
    for nome in ("ator.py", "registro.py"):
        texto = (RAIZ / "app" / nome).read_text(encoding="utf-8")
        assert "import streamlit" not in texto
        assert "from paginas" not in texto

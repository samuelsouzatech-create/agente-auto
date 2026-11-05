"""
S4b (Fase 3): Equipe e Canais na Configuração do operador.
- pessoas: criar, alterar, desativar e reativar vão para o Registro com o ator;
- conflito: cadastro mudado por outra pessoa não é sobrescrito;
- canais: a tela nova não move canal de outra loja; a chave nunca aparece;
- "Testar conexão" usa as mesmas regras do envio;
- duas lojas; a tela abre e grava (AppTest); as telas antigas continuam abrindo.
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import lojas_admin
from app.ator import AtorInvalido, como
from app.canais import (
    CanalDeOutraLoja, cadastrar_canal, desativar_canal_da_loja, listar_canais,
    reativar_canal_da_loja,
)
from app.credenciais import (
    ENCONTRADA, NAO_ENCONTRADA, OUTRO_ROBO, SemCredencial, situacao_da_chave, token_telegram,
)
from app.equipe_canais import (
    canais_da_loja, equipe_da_loja, testar_conexao, ultima_alteracao, validar_canal_novo,
)
from app.estado_loja import cadastrar_numero_de_teste, desativar_numero_de_teste
from app.registro_leitura import filtrar_registro
from app.registro_tela import linhas_do_registro
from app.usuarios import PessoaMudou, atualizar_usuario, criar_usuario, definir_ativo

RAIZ = Path(__file__).resolve().parent.parent
TELA = RAIZ / "paginas" / "operador" / "configuracao.py"


def _loja_b():
    return lojas_admin.criar_loja("Loja B", "Caruaru", "America/Recife", "veiculos")


def _detalhes(loja, acao):
    return [l["Detalhe"] for l in linhas_do_registro(filtrar_registro(loja, acao=acao),
                                                      com_loja=False)]


# ------------------------------------------------------------ equipe

def test_pessoa_criar_alterar_desativar_reativar_no_registro():
    uid = criar_usuario(1, "Ana", "vendedor", "123456789", "5581999998888")
    atualizar_usuario(uid, 1, "Ana Maria", "gestor", "123456789", "5581999998888")
    definir_ativo(uid, 1, False)
    definir_ativo(uid, 1, True)
    assert _detalhes(1, "criar_pessoa_equipe") == ["Ana · Vendedor"]
    assert _detalhes(1, "alterar_pessoa_equipe") == [
        "Ana Maria · Nome: Ana → Ana Maria, Papel: Vendedor → Gerente"]
    assert _detalhes(1, "desativar_pessoa_equipe") == ["Ana Maria · Gerente"]
    assert _detalhes(1, "reativar_pessoa_equipe") == ["Ana Maria · Gerente"]
    assert ultima_alteracao(1, "Equipe")["quem"] == "Teste"


def test_salvar_sem_mudar_nada_nao_registra():
    uid = criar_usuario(1, "Ana", "vendedor")
    atualizar_usuario(uid, 1, "Ana", "vendedor")
    definir_ativo(uid, 1, True)
    assert _detalhes(1, "alterar_pessoa_equipe") == []
    assert _detalhes(1, "reativar_pessoa_equipe") == []


def test_conflito_nao_sobrescreve():
    uid = criar_usuario(1, "Ana", "vendedor")
    visto = equipe_da_loja(1)[0]["versao"]
    atualizar_usuario(uid, 1, "Ana Paula", "vendedor")           # outra pessoa salva
    with pytest.raises(PessoaMudou):
        atualizar_usuario(uid, 1, "Ana", "gestor", esperado=visto)
    p = equipe_da_loja(1)[0]
    assert (p["nome"], p["papel"]) == ("Ana Paula", "vendedor")


def test_recebe_avisos_e_calculado():
    criar_usuario(1, "Ana", "vendedor", "123456789")
    uid = criar_usuario(1, "Caio", "vendedor")
    criar_usuario(1, "Bia", "gestor", "987654321")
    definir_ativo(uid, 1, False)
    avisos = {p["nome"]: p["recebe_avisos"] for p in equipe_da_loja(1)}
    assert avisos == {"Ana": True, "Caio": False, "Bia": True}


def test_duas_lojas_na_equipe():
    b = _loja_b()
    uid = criar_usuario(b, "Bruno", "vendedor")
    assert atualizar_usuario(uid, 1, "Intruso", "gestor") is False
    assert definir_ativo(uid, 1, False) is False
    assert [p["nome"] for p in equipe_da_loja(1)] == []
    with como("Ana", "cliente", "painel", loja_id=1):
        with pytest.raises(AtorInvalido):
            criar_usuario(b, "Outro", "vendedor")


# ------------------------------------------------------------ canais

def test_tela_nova_nao_move_canal_de_outra_loja():
    b = _loja_b()
    cadastrar_canal(b, "telegram", "777")
    with pytest.raises(CanalDeOutraLoja):
        cadastrar_canal(1, "telegram", "777", permitir_mover=False)
    assert listar_canais(1) == []
    cadastrar_canal(1, "telegram", "777")                         # tela antiga: move
    assert [c["id_externo"] for c in listar_canais(1)] == ["777"]
    assert _detalhes(1, "cadastrar_canal") == ["Telegram · trazido de outra loja"]


def test_desativar_e_reativar_so_na_propria_loja():
    b = _loja_b()
    cadastrar_canal(b, "telegram", "777")
    canal = listar_canais(b)[0]["id"]
    assert desativar_canal_da_loja(1, canal) is False
    assert desativar_canal_da_loja(b, canal) is True
    assert desativar_canal_da_loja(b, canal) is False
    assert reativar_canal_da_loja(b, canal) is True
    assert _detalhes(b, "desativar_canal") == ["Telegram · desativado"]
    assert _detalhes(b, "cadastrar_canal") == ["Telegram · reativado",
                                               "Telegram · ligado a esta loja"]


def test_cadastrar_igual_nao_registra_de_novo():
    cadastrar_canal(1, "telegram", "777", "TG_X")
    cadastrar_canal(1, "telegram", "777", "TG_X")
    assert len(_detalhes(1, "cadastrar_canal")) == 1


def test_situacao_da_chave_igual_ao_envio(monkeypatch):
    monkeypatch.setenv("TG_CERTO", "777:segredo-certo")
    monkeypatch.setenv("TG_OUTRO", "888:segredo-outro")
    cadastrar_canal(1, "telegram", "777", "TG_CERTO")
    assert situacao_da_chave(listar_canais(1)[0]) == ENCONTRADA
    assert token_telegram(1) == "777:segredo-certo"
    cadastrar_canal(1, "telegram", "777", "TG_OUTRO")
    assert situacao_da_chave(listar_canais(1)[0]) == OUTRO_ROBO
    cadastrar_canal(1, "telegram", "777", "TG_NAO_EXISTE")
    assert situacao_da_chave(listar_canais(1)[0]) == NAO_ENCONTRADA
    with pytest.raises(SemCredencial):
        token_telegram(1)


def test_chave_e_nome_da_chave_nunca_aparecem(monkeypatch):
    monkeypatch.setenv("TG_CERTO", "777123:segredo-certo")
    cadastrar_canal(1, "telegram", "777123", "TG_CERTO")
    canal = listar_canais(1)[0]["id"]
    textos = str(canais_da_loja(1)) + str(testar_conexao(1, canal)) + \
        str(linhas_do_registro(filtrar_registro(1), com_loja=False))
    assert "segredo" not in textos and "TG_CERTO" not in textos
    assert canais_da_loja(1)[0]["nome"] == "Telegram · final 7123"
    assert testar_conexao(1, canal)[0] is True
    assert testar_conexao(_loja_b(), canal) == (False, "Este canal não é desta loja.")


def test_validar_canal_novo_recusa_chave_colada():
    assert validar_canal_novo("telegram", "777", "777:ABC")
    assert validar_canal_novo("telegram", "", "")
    assert validar_canal_novo("telegram", "777", "TG_OK") == []


def test_numeros_de_teste_no_registro_sem_o_numero():
    nid = cadastrar_numero_de_teste(1, "whatsapp", "(81) 99999-0000", "Samuel")
    desativar_numero_de_teste(1, nid)
    textos = _detalhes(1, "cadastrar_numero_teste") + _detalhes(1, "desativar_numero_teste")
    assert textos == ["WhatsApp · Samuel", "WhatsApp · Samuel"]
    assert ultima_alteracao(1, "Canais")["quem"] == "Teste"


# ------------------------------------------------------------ tela

@pytest.fixture
def nome_operador(monkeypatch):
    monkeypatch.setenv("OPERADOR_NOME", "Samuel Tela")


def _abrir(assunto):
    at = AppTest.from_file(str(TELA), default_timeout=30)
    at.session_state["_papel"] = "operador"
    at.session_state["loja_id"] = 1
    at.run()
    at.radio(key="config_assunto").set_value(assunto).run()
    assert not at.exception, at.exception
    return at


def _botao(at, rotulo):
    return next(b for b in at.button if str(b.label) == rotulo)


def test_tela_equipe_cadastra_pessoa(nome_operador):
    at = _abrir("Equipe")
    next(t for t in at.text_input if str(t.label) == "Nome").set_value("Zé")
    _botao(at, "💾 Cadastrar pessoa").click().run()
    assert not at.exception, at.exception
    assert [p["nome"] for p in equipe_da_loja(1)] == ["Zé"]
    linhas = linhas_do_registro(filtrar_registro(1, acao="criar_pessoa_equipe"), com_loja=False)
    assert linhas[0]["Quem"] == "Samuel Tela"


def test_tela_canais_testa_conexao(nome_operador, monkeypatch):
    monkeypatch.setenv("TG_CERTO", "777:segredo")
    cadastrar_canal(1, "telegram", "777", "TG_CERTO")
    at = _abrir("Canais")
    _botao(at, "🔌 Testar conexão").click().run()
    assert not at.exception, at.exception
    assert any("Chave encontrada" in s.value for s in at.success)


def test_telas_antigas_continuam_abrindo(nome_operador):
    for arquivo, papel in (("usuarios.py", "cliente"), ("usuarios.py", "operador"),
                           ("lojas_canais.py", "operador")):
        at = AppTest.from_file(str(RAIZ / "paginas" / arquivo), default_timeout=30)
        at.session_state["_papel"] = papel
        at.session_state["_loja_cliente"] = 1
        at.session_state["loja_id"] = 1
        at.run()
        assert not at.exception, (arquivo, papel, at.exception)

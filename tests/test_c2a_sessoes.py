"""
C2a (Plano Mestre, bloco C2), parte de app/: migração 15 (sessoes),
app/sessoes.py, autenticacao.trocar_senha e o módulo Estoque (decisão D2).
A parte HTTP (app/api_painel/) chega na parte 2, com os próprios testes.
Tudo offline, banco temporário do conftest (ator "Teste", operador, painel), duas lojas.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

import banco
from banco import conectar
from app import autenticacao, sessoes
from app.ator import AtorInvalido, SemAtor, como, sem_ator
from app.config_tela import PLANO_E_LIMITES, campos_do_assunto
from app.lojas import MODULOS, PADROES, SemPermissao, carregar_loja, criar_loja, salvar_config

SENHA = "Carro-Azul-2026"
NOVA = "Moto-Verde-2027"
AGORA = datetime(2026, 11, 9, 13, 0, tzinfo=timezone.utc)


def _um(sql, parametros=()):
    conexao = conectar()
    try:
        return conexao.execute(sql, parametros).fetchone()[0]
    finally:
        conexao.close()


def _executar(sql, parametros=()):
    conexao = conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


def _colunas(tabela):
    conexao = conectar()
    try:
        return {l[1] for l in conexao.execute(f"PRAGMA table_info({tabela})")}
    finally:
        conexao.close()


def _pessoa(loja=1, papel="gestor", email="ana@loja.com"):
    return autenticacao.criar_usuario_com_login(loja, "Ana Lima", papel, email, SENHA)


def _sessao(uid, loja=1, papel="gestor", **extra):
    return sessoes.criar_sessao(uid, loja, papel, **extra)


# ------------------------------------------------------------ migração 15

def test_migracao_15_sobe_da_14_sem_perder_nada():
    uid = _pessoa()
    _executar("DROP TABLE sessoes")
    _executar("PRAGMA user_version = 14")
    banco.migrar()
    assert _um("PRAGMA user_version") == banco.VERSAO_SCHEMA >= 15
    assert _um("SELECT COUNT(*) FROM sessoes") == 0
    assert _um("SELECT email FROM usuarios WHERE id = ?", (uid,)) == "ana@loja.com"
    assert _colunas("sessoes") == {"id", "token_hash", "usuario_id", "loja_id", "papel", "escopo",
                                   "lead_id", "criado_em", "expira_em", "revogada_em"}
    assert "senha_provisoria" not in _colunas("usuarios")


def test_migracao_15_roda_de_novo_sem_perder_sessao():
    uid = _pessoa()
    token = _sessao(uid)
    _executar("PRAGMA user_version = 11")
    banco.migrar()
    assert _um("PRAGMA user_version") == banco.VERSAO_SCHEMA
    assert sessoes.ler_sessao(token)["usuario_id"] == uid


# ------------------------------------------------------------ sessões

def test_token_so_em_hash_no_banco():
    token = _sessao(_pessoa())
    conexao = conectar()
    try:
        linha = dict(conexao.execute("SELECT * FROM sessoes").fetchone())
    finally:
        conexao.close()
    assert token not in json.dumps(linha, default=str)
    assert linha["token_hash"] != token and len(token) >= 40


def test_sessao_valida_traz_loja_papel_e_nome():
    uid = _pessoa()
    s = sessoes.ler_sessao(_sessao(uid))
    assert (s["usuario_id"], s["loja_id"], s["papel"], s["escopo"], s["lead_id"]) == (
        uid, 1, "gestor", "completo", None)
    assert s["nome"] == "Ana Lima"


def test_cada_sessao_tem_token_proprio():
    uid = _pessoa()
    assert _sessao(uid) != _sessao(uid)


def test_sessao_vence_em_7_dias():
    token = _sessao(_pessoa(), agora=AGORA)
    assert sessoes.ler_sessao(token, agora=AGORA + timedelta(days=6, hours=23))
    assert sessoes.ler_sessao(token, agora=AGORA + timedelta(days=7, seconds=1)) is None


def test_sessao_revogada_nao_vale():
    token = _sessao(_pessoa())
    assert sessoes.revogar(token) is True
    assert sessoes.ler_sessao(token) is None
    assert sessoes.revogar(token) is False


@pytest.mark.parametrize("token", [None, "", "curto", 123, "x" * 200, "y" * 43])
def test_token_ruim_ou_desconhecido(token):
    _sessao(_pessoa())
    assert sessoes.ler_sessao(token) is None


def test_pessoa_desativada_ou_com_outro_papel_perde_a_sessao():
    uid = _pessoa()
    token = _sessao(uid)
    _executar("UPDATE usuarios SET papel = 'vendedor' WHERE id = ?", (uid,))
    assert sessoes.ler_sessao(token) is None
    _executar("UPDATE usuarios SET papel = 'gestor', ativo = 0 WHERE id = ?", (uid,))
    assert sessoes.ler_sessao(token) is None


def test_loja_desligada_derruba_a_sessao():
    token = _sessao(_pessoa())
    _executar("UPDATE lojas SET ativo = 0 WHERE id = 1")
    assert sessoes.ler_sessao(token) is None


def test_duas_lojas_sessao_so_na_loja_da_pessoa():
    loja2 = criar_loja("Loja 2")
    uid = _pessoa()
    with pytest.raises(sessoes.SessaoInvalida):
        _sessao(uid, loja=loja2)
    bia = _pessoa(loja=loja2, email="bia@loja2.com")
    assert sessoes.ler_sessao(_sessao(bia, loja=loja2))["loja_id"] == loja2
    assert sessoes.ler_sessao(_sessao(uid))["loja_id"] == 1


def test_operador_e_suporte_nao_ganham_sessao():
    op = autenticacao.criar_usuario_com_login(None, "Samuel", "operador", "samuel@leo.com", SENHA)
    for papel in ("operador", "suporte", "cliente"):
        with pytest.raises(sessoes.SessaoInvalida):
            sessoes.criar_sessao(op, 1, papel)


def test_sessao_de_operador_gravada_direto_no_banco_nao_vale():
    op = autenticacao.criar_usuario_com_login(None, "Samuel", "operador", "samuel@leo.com", SENHA)
    token = "t" * 43
    _executar("INSERT INTO sessoes (token_hash, usuario_id, loja_id, papel, escopo, expira_em) "
              "VALUES (?, ?, 1, 'operador', 'completo', '2999-01-01 00:00:00')",
              (sessoes._hash(token), op))
    assert sessoes.ler_sessao(token) is None


def test_vendedor_com_login_ganha_sessao():
    uid = _pessoa(papel="vendedor")
    s = sessoes.ler_sessao(_sessao(uid, papel="vendedor"))
    assert (s["papel"], s["escopo"]) == ("vendedor", "atendimento")
    with pytest.raises(sessoes.SessaoInvalida):
        _sessao(uid, papel="vendedor", escopo="completo")


def test_papel_da_sessao_precisa_ser_o_da_pessoa():
    uid = _pessoa(papel="vendedor")
    with pytest.raises(sessoes.SessaoInvalida):
        _sessao(uid, papel="gestor")


def test_escopo_de_link_so_com_a_conversa():
    uid = _pessoa(papel="vendedor")
    with pytest.raises(sessoes.SessaoInvalida):
        _sessao(uid, papel="vendedor_link", escopo="link")
    with pytest.raises(sessoes.SessaoInvalida):
        _sessao(uid, papel="vendedor", lead_id="5581999990001")
    s = sessoes.ler_sessao(_sessao(uid, papel="vendedor_link", escopo="link",
                                   lead_id="5581999990001"))
    assert (s["escopo"], s["lead_id"]) == ("link", "5581999990001")


def test_csrf_vem_do_token_e_nao_e_o_token():
    token = _sessao(_pessoa())
    csrf = sessoes.csrf_da(token)
    assert csrf not in (token, sessoes._hash(token)) and csrf == sessoes.csrf_da(token)
    assert sessoes.conferir_csrf(token, csrf) is True
    outro = _sessao(_pessoa(email="bia@loja.com"))
    for ruim in ("", None, sessoes.csrf_da(outro), csrf[:-1]):
        assert sessoes.conferir_csrf(token, ruim) is False


def test_revogar_todas_menos_a_atual():
    uid = _pessoa()
    a, b, c = _sessao(uid), _sessao(uid), _sessao(uid)
    assert sessoes.revogar_todas_da_pessoa(uid, exceto_token=a) == 2
    assert sessoes.ler_sessao(a)
    assert sessoes.ler_sessao(b) is None and sessoes.ler_sessao(c) is None


# ------------------------------------------------------------ trocar senha

def test_trocar_senha_com_sucesso():
    uid = _pessoa()
    atual, outra = _sessao(uid), _sessao(uid)
    assert autenticacao.trocar_senha(uid, SENHA, NOVA, manter_sessao=atual) == 1
    assert autenticacao.autenticar("ana@loja.com", NOVA)["id"] == uid
    assert autenticacao.autenticar("ana@loja.com", SENHA) is None
    assert sessoes.ler_sessao(atual) and sessoes.ler_sessao(outra) is None


def test_trocar_senha_vai_ao_registro_sem_a_senha():
    uid = _pessoa()
    autenticacao.trocar_senha(uid, SENHA, NOVA)
    conexao = conectar()
    try:
        linhas = [dict(l) for l in conexao.execute(
            "SELECT * FROM registro_acoes WHERE acao = 'trocar_senha'")]
    finally:
        conexao.close()
    assert len(linhas) == 1
    assert linhas[0]["loja_id"] == 1 and linhas[0]["alvo"] == f"usuario:{uid}"
    texto = json.dumps(linhas, default=str)
    assert NOVA not in texto and SENHA not in texto
    assert json.loads(linhas[0]["depois"])["senha"] == "trocada"


def test_senha_atual_errada_nao_troca_e_conta_tentativa():
    uid = _pessoa()
    hash_antes = _um("SELECT senha_hash FROM usuarios WHERE id = ?", (uid,))
    with pytest.raises(autenticacao.SenhaAtualErrada):
        autenticacao.trocar_senha(uid, "Errada-Demais-1", NOVA)
    assert _um("SELECT senha_hash FROM usuarios WHERE id = ?", (uid,)) == hash_antes
    assert _um("SELECT COUNT(*) FROM acessos WHERE usuario_id = ? AND resultado = 'senha_errada'",
               (uid,)) == 1


def test_erros_demais_bloqueiam_troca_e_login():
    uid = _pessoa()
    for _ in range(autenticacao.MAX_TENTATIVAS):
        with pytest.raises(autenticacao.SenhaAtualErrada):
            autenticacao.trocar_senha(uid, "Errada-Demais-1", NOVA)
    with pytest.raises(autenticacao.MuitasTentativas):
        autenticacao.trocar_senha(uid, SENHA, NOVA)
    assert autenticacao.autenticar("ana@loja.com", SENHA) is None


@pytest.mark.parametrize("nova", ["curta", "1234567890", SENHA])
def test_senha_nova_fraca_ou_igual_e_recusada(nova):
    uid = _pessoa()
    with pytest.raises(autenticacao.SenhaFraca):
        autenticacao.trocar_senha(uid, SENHA, nova)
    assert autenticacao.autenticar("ana@loja.com", SENHA)["id"] == uid


def test_trocar_senha_sem_ator_nada_acontece():
    uid = _pessoa()
    token = _sessao(uid)
    with sem_ator(), pytest.raises(SemAtor):
        autenticacao.trocar_senha(uid, SENHA, NOVA)
    assert autenticacao.autenticar("ana@loja.com", SENHA)["id"] == uid
    assert sessoes.ler_sessao(token)
    assert _um("SELECT COUNT(*) FROM registro_acoes WHERE acao = 'trocar_senha'") == 0


def test_ator_de_outra_loja_nao_troca_senha():
    loja2 = criar_loja("Loja 2")
    uid = _pessoa()
    with como("Bia", "cliente", "api", loja_id=loja2), pytest.raises(AtorInvalido):
        autenticacao.trocar_senha(uid, SENHA, NOVA)
    assert autenticacao.autenticar("ana@loja.com", SENHA)["id"] == uid


def test_pessoa_desativada_nao_troca_senha():
    uid = _pessoa()
    _executar("UPDATE usuarios SET ativo = 0 WHERE id = ?", (uid,))
    with pytest.raises(autenticacao.DadosInvalidos):
        autenticacao.trocar_senha(uid, SENHA, NOVA)


# ------------------------------------------------------------ módulo Estoque (D2)

def test_modulo_estoque_existe_e_nasce_ligado():
    assert "estoque" in MODULOS and PADROES["modulos"]["estoque"] is True
    loja2 = criar_loja("Loja 2")
    assert carregar_loja(1).get("modulos.estoque") is True
    assert carregar_loja(loja2).get("modulos.estoque") is True


def test_desligar_estoque_numa_loja_nao_mexe_na_outra():
    loja2 = criar_loja("Loja 2")
    salvar_config(loja2, {"modulos.estoque": False}, "Samuel")
    assert carregar_loja(loja2).get("modulos.estoque") is False
    assert carregar_loja(1).get("modulos.estoque") is True


def test_so_o_operador_liga_e_desliga_o_estoque():
    with como("Ana", "cliente", "painel", loja_id=1), pytest.raises(SemPermissao):
        salvar_config(1, {"modulos.estoque": False}, "Ana", papel="cliente")
    assert carregar_loja(1).get("modulos.estoque") is True


def test_estoque_aparece_em_plano_e_limites():
    assert "modulos.estoque" in {c.chave for c in campos_do_assunto(PLANO_E_LIMITES)}

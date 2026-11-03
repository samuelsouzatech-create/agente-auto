"""
P8b do Plano Mestre: login sem HTTP (app/autenticacao.py).
- o hash é Argon2id e nunca guarda a senha; o Registro nunca vê senha nem hash;
- senha fraca recusada; e-mail repetido recusado (sem diferença de maiúsculas);
- papel inválido recusado; operador e suporte sem loja;
- limite de tentativas por e-mail, que passa depois da janela;
- usuário antigo ganha e-mail e senha e entra;
- só o operador cria acesso e redefine senha.
Hash leve nos testes (mesmo algoritmo, menos memória) para a suíte não ficar lenta.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from argon2 import PasswordHasher

from banco import conectar
from app import autenticacao as aut
from app.ator import como
from app.chaves import LojaNaoInformada
from app.estado_loja import SoOperador
from app.lojas import criar_loja
from app.usuarios import criar_usuario, definir_ativo

RAIZ = Path(__file__).resolve().parent.parent
SENHA = "Carro-Azul-2026"
T = datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def hash_leve(monkeypatch):
    monkeypatch.setattr(aut, "_hasher", PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))


def _um(sql, parametros=()):
    conexao = conectar()
    try:
        return conexao.execute(sql, parametros).fetchone()[0]
    finally:
        conexao.close()


def _resultados(email):
    conexao = conectar()
    try:
        return [l[0] for l in conexao.execute(
            "SELECT resultado FROM acessos WHERE email = ? ORDER BY id", (email,))]
    finally:
        conexao.close()


def _ana(email="ana@loja.com", loja=1, papel="gestor"):
    return aut.criar_usuario_com_login(loja, "Ana Souza", papel, email, SENHA)


# ------------------------------------------------------------ criar e entrar

def test_criar_e_autenticar():
    uid = _ana()
    r = aut.autenticar("ana@loja.com", SENHA, agora=T)
    assert r == {"id": uid, "nome": "Ana Souza", "papel": "gestor", "rotulo_papel": "Gerente",
                 "loja_id": 1, "email": "ana@loja.com"}
    assert _um("SELECT ultimo_acesso FROM usuarios WHERE id = ?", (uid,)) == "2026-11-03 13:00:00"
    assert _resultados("ana@loja.com") == ["ok"]


def test_email_com_maiusculas_e_espacos_e_o_mesmo():
    _ana(email="  Ana@Loja.COM ")
    assert _um("SELECT email FROM usuarios") == "ana@loja.com"
    assert aut.autenticar(" ANA@loja.com ", SENHA) is not None


def test_hash_nunca_guarda_a_senha_nem_vai_ao_registro():
    _ana()
    guardado = _um("SELECT senha_hash FROM usuarios")
    assert guardado.startswith("$argon2id$") and SENHA not in guardado
    conexao = conectar()
    try:
        textos = " ".join(str(c) for l in conexao.execute("SELECT * FROM registro_acoes") for c in l)
    finally:
        conexao.close()
    assert SENHA not in textos and "$argon2" not in textos


@pytest.mark.parametrize("fraca", ["curta1!", "senha12345", "1234567890", "aaaaaaaaaaaa",
                                   "abababababab", "SENHA12345", "x" * 129])
def test_senha_fraca_recusada(fraca):
    with pytest.raises(aut.SenhaFraca):
        aut.criar_usuario_com_login(1, "Ana", "vendedor", "ana@loja.com", fraca)
    assert _um("SELECT COUNT(*) FROM usuarios") == 0


def test_email_repetido_recusado():
    _ana()
    loja2 = criar_loja("Loja 2")
    with pytest.raises(aut.DadosInvalidos):
        _ana(email="ANA@loja.com", loja=loja2)
    assert _um("SELECT COUNT(*) FROM usuarios") == 1


@pytest.mark.parametrize("papel", ["gerente", "cliente", "admin", ""])
def test_papel_invalido_recusado(papel):
    with pytest.raises(aut.DadosInvalidos):
        _ana(papel=papel)


@pytest.mark.parametrize("email", ["", "ana", "ana@", "ana@loja", "a b@loja.com"])
def test_email_invalido_recusado(email):
    with pytest.raises(aut.DadosInvalidos):
        _ana(email=email)


def test_operador_e_suporte_sem_loja():
    op = aut.criar_usuario_com_login(None, "Samuel", "operador", "samuel@leo.com", SENHA)
    su = aut.criar_usuario_com_login(None, "Suporte", "suporte", "suporte@leo.com", SENHA)
    assert _um("SELECT COUNT(*) FROM usuarios WHERE id IN (?, ?) AND loja_id IS NULL", (op, su)) == 2
    assert aut.autenticar("samuel@leo.com", SENHA)["loja_id"] is None
    with pytest.raises(aut.DadosInvalidos):
        aut.criar_usuario_com_login(1, "Samuel", "operador", "s2@leo.com", SENHA)
    with pytest.raises(aut.DadosInvalidos):
        aut.criar_usuario_com_login(None, "Ana", "vendedor", "ana@loja.com", SENHA)


def test_loja_invalida_ou_inexistente():
    with pytest.raises(LojaNaoInformada):
        _ana(loja=0)
    with pytest.raises(aut.DadosInvalidos):
        _ana(loja=999)


# ------------------------------------------------------------ recusas e limite

def test_senha_errada_email_desconhecido_e_desativado():
    uid = _ana()
    assert aut.autenticar("ana@loja.com", "outra-senha-qualquer") is None
    assert aut.autenticar("ninguem@loja.com", SENHA) is None
    definir_ativo(uid, 1, False)
    assert aut.autenticar("ana@loja.com", SENHA) is None
    assert _resultados("ana@loja.com") == ["senha_errada", "desativado"]
    assert _resultados("ninguem@loja.com") == ["email_desconhecido"]


def test_limite_de_tentativas_e_libera_depois_da_janela():
    _ana()
    for i in range(aut.MAX_TENTATIVAS):
        assert aut.autenticar("ana@loja.com", f"errada-{i}-xxxx", agora=T) is None
    assert aut.bloqueado_por_tentativas("ana@loja.com", agora=T) is True
    assert aut.autenticar("ana@loja.com", SENHA, agora=T + timedelta(minutes=1)) is None
    assert _resultados("ana@loja.com")[-1] == "bloqueado"
    depois = T + timedelta(minutes=aut.JANELA_TENTATIVAS_MIN + 1)
    assert aut.bloqueado_por_tentativas("ana@loja.com", agora=depois) is False
    assert aut.autenticar("ana@loja.com", SENHA, agora=depois) is not None


def test_login_certo_zera_a_contagem():
    _ana()
    for i in range(aut.MAX_TENTATIVAS - 1):
        aut.autenticar("ana@loja.com", f"errada-{i}-xxxx", agora=T)
    assert aut.autenticar("ana@loja.com", SENHA, agora=T) is not None
    aut.autenticar("ana@loja.com", "errada-de-novo-x", agora=T)
    assert aut.bloqueado_por_tentativas("ana@loja.com", agora=T) is False


def test_erro_num_email_nao_bloqueia_outro():
    _ana()
    _ana(email="bia@loja.com")
    for i in range(aut.MAX_TENTATIVAS):
        aut.autenticar("ana@loja.com", f"errada-{i}-xxxx", agora=T)
    assert aut.autenticar("bia@loja.com", SENHA, agora=T) is not None


# ------------------------------------------------------------ usuário antigo

def test_usuario_antigo_ganha_email_e_senha_e_entra():
    uid = criar_usuario(1, "Carlos", "vendedor")          # como antes do P8
    assert aut.autenticar("carlos@loja.com", SENHA) is None
    assert aut.definir_email(uid, "Carlos@Loja.com") is True
    assert aut.definir_email(uid, "carlos@loja.com") is False   # mesmo e-mail: nada muda
    assert aut.autenticar("carlos@loja.com", SENHA) is None    # ainda sem senha
    assert _resultados("carlos@loja.com")[-1] == "sem_senha"
    aut.definir_senha(uid, SENHA)
    assert aut.autenticar("carlos@loja.com", SENHA)["id"] == uid


def test_definir_email_repetido_e_usuario_inexistente():
    _ana()
    uid = criar_usuario(1, "Carlos", "vendedor")
    with pytest.raises(aut.DadosInvalidos):
        aut.definir_email(uid, "ANA@loja.com")
    with pytest.raises(aut.DadosInvalidos):
        aut.definir_senha(999, SENHA)


# ------------------------------------------------------------ só o operador

def test_cliente_nao_cria_acesso_nem_redefine_senha():
    uid = criar_usuario(1, "Carlos", "vendedor")
    with como("Ana", "cliente", "painel", 1):
        with pytest.raises(SoOperador):
            _ana()
        with pytest.raises(SoOperador):
            aut.definir_senha(uid, SENHA)
    assert _um("SELECT COUNT(*) FROM usuarios WHERE senha_hash IS NOT NULL") == 0


def test_rotulos_e_sem_streamlit():
    assert aut.rotulo_papel("gestor") == "Gerente"
    assert aut.listar_logins() == [] or "senha_hash" not in aut.listar_logins()[0]
    texto = (RAIZ / "app" / "autenticacao.py").read_text(encoding="utf-8")
    assert "import streamlit" not in texto and "from paginas" not in texto

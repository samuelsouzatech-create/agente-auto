"""
Login (P8 do Plano Mestre), ainda sem HTTP: a API do painel (C2) vai chamar
estas funções. Sem Streamlit.

- E-mail é o login: único, guardado em minúsculas e sem espaços.
- Senha só em hash Argon2id (argon2-cffi). A senha nunca é guardada nem vai
  para o Registro; o Registro só diz "senha trocada".
- Senha forte: pelo menos MIN_SENHA caracteres, fora da lista de comuns e
  sem ser quase tudo o mesmo caractere.
- Limite de tentativas por e-mail: MAX_TENTATIVAS erros em
  JANELA_TENTATIVAS_MIN minutos bloqueiam aquele e-mail até os erros saírem
  da janela. Login certo zera a contagem.
- Toda tentativa vai para a tabela acessos (não para o Registro: na hora do
  login ainda não se sabe quem é a pessoa).
- E-mail desconhecido gasta o mesmo tempo que uma senha errada, para ninguém
  descobrir quais e-mails existem cronometrando a resposta.
- Só o operador cria acesso, muda e-mail e redefine senha (decisão A5), e
  isso vai para o Registro na mesma transação.
- Papéis: vendedor, gestor ("Gerente" nas telas), dono, operador e suporte.
  Operador e suporte não têm loja. Suporte só fica gravado (sem telas).
- TOTP não é construído agora (o operador fica atrás do proxy, decisão D5).
"""
from __future__ import annotations

import re
import sqlite3
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from banco import conectar
from app.chaves import exigir_loja
from app.estado_loja import SoOperador
from app.relogio import agora_utc, para_banco

PAPEIS = ("vendedor", "gestor", "dono", "operador", "suporte")
PAPEIS_SEM_LOJA = ("operador", "suporte")
ROTULOS_PAPEL = {"vendedor": "Vendedor", "gestor": "Gerente", "dono": "Dono",
                 "operador": "Operador", "suporte": "Suporte"}
MIN_SENHA = 10
MAX_SENHA = 128
MAX_NOME = 80
MAX_EMAIL = 254
MAX_TENTATIVAS = 5
JANELA_TENTATIVAS_MIN = 15
OK = "ok"
BLOQUEADO = "bloqueado"
FALHAS = ("senha_errada", "email_desconhecido", "sem_senha", "desativado")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Senhas que aparecem no topo das listas de vazamentos (comparadas em minúsculas).
SENHAS_COMUNS = frozenset({
    "1234567890", "12345678910", "0123456789", "123456789a", "1234567890a",
    "senha12345", "senha123456", "senha1234567", "minhasenha", "minhasenha1",
    "minhasenha123", "password1", "password12", "password123", "password1234",
    "qwertyuiop", "qwerty1234", "qwerty12345", "asdfghjkl1", "abc1234567",
    "abcdefghij", "iloveyou12", "brasil1234", "brasil12345", "flamengo123",
    "corinthians", "palmeiras1", "admin12345", "administrador", "trocar123",
    "mudar12345", "mudar123456", "senhasenha", "leo1234567", "loja123456",
    "1q2w3e4r5t", "1qaz2wsx3edc", "q1w2e3r4t5", "987654321a", "0987654321",
})

_hasher = PasswordHasher()                 # padrão da biblioteca (Argon2id)
_FALSO = {"hasher": None, "hash": None}


class DadosInvalidos(ValueError):
    pass


class SenhaFraca(ValueError):
    pass


def rotulo_papel(papel: str) -> str:
    return ROTULOS_PAPEL.get(papel, papel)


def normalizar_email(email) -> str:
    texto = str(email or "").strip().lower()
    if len(texto) > MAX_EMAIL or not _EMAIL.match(texto):
        raise DadosInvalidos("E-mail inválido. Exemplo: ana@loja.com")
    return texto


def validar_senha(senha) -> None:
    if not isinstance(senha, str) or len(senha) < MIN_SENHA:
        raise SenhaFraca(f"A senha precisa ter pelo menos {MIN_SENHA} caracteres.")
    if len(senha) > MAX_SENHA:
        raise SenhaFraca(f"A senha pode ter no máximo {MAX_SENHA} caracteres.")
    if senha.lower() in SENHAS_COMUNS or len(set(senha)) < 4:
        raise SenhaFraca("Essa senha é fácil de adivinhar. Escolha outra.")


def _loja_do_papel(loja_id, papel):
    if papel not in PAPEIS:
        raise DadosInvalidos(f"Papel inválido (use: {', '.join(PAPEIS)}).")
    if papel in PAPEIS_SEM_LOJA:
        if loja_id is not None:
            raise DadosInvalidos("Operador e suporte não ficam presos a uma loja.")
        return None
    if loja_id is None:
        raise DadosInvalidos(f"{rotulo_papel(papel)} precisa de uma loja.")
    return exigir_loja(loja_id)


def _exigir_operador(loja_id):
    from app.registro import conferir_ator # aqui dentro: evita import circular
    ator = conferir_ator(loja_id)
    if ator.papel != "operador":
        raise SoOperador("Só o operador cria acessos, muda e-mail e redefine senhas.")
    return ator


def _verificar(hash_guardado, senha) -> bool:
    try:
        return _hasher.verify(hash_guardado, senha)
    except (VerificationError, InvalidHashError):
        return False


def _hash_falso() -> str:
    if _FALSO["hasher"] is not _hasher:
        _FALSO["hash"] = _hasher.hash("nenhuma-pessoa-tem-esta-senha")
        _FALSO["hasher"] = _hasher
    return _FALSO["hash"]


def _usuario(conexao, usuario_id):
    linha = conexao.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if linha is None:
        raise DadosInvalidos(f"Usuário {usuario_id} não existe.")
    return linha


# ------------------------------------------------------------ escrita (só operador)

def criar_usuario_com_login(loja_id, nome: str, papel: str, email: str, senha: str) -> int:
    """Cria a pessoa já com e-mail e senha. loja_id None só para operador e suporte."""
    loja = _loja_do_papel(loja_id, papel)
    nome_limpo = " ".join(str(nome or "").split())
    if not 1 <= len(nome_limpo) <= MAX_NOME:
        raise DadosInvalidos(f"Nome: precisa ter entre 1 e {MAX_NOME} caracteres.")
    email_limpo = normalizar_email(email)
    validar_senha(senha)
    _exigir_operador(loja)
    from app.registro import registrar
    hash_senha = _hasher.hash(senha)
    conexao = conectar()
    try:
        if loja is not None and not conexao.execute(
                "SELECT 1 FROM lojas WHERE id = ?", (loja,)).fetchone():
            raise DadosInvalidos(f"Loja {loja} não existe.")
        if conexao.execute("SELECT 1 FROM usuarios WHERE email = ?", (email_limpo,)).fetchone():
            raise DadosInvalidos("Esse e-mail já é usado por outra pessoa.")
        novo = conexao.execute(
            "INSERT INTO usuarios (loja_id, nome, papel, email, senha_hash) VALUES (?, ?, ?, ?, ?)",
            (loja, nome_limpo, papel, email_limpo, hash_senha)).lastrowid
        registrar("criar_acesso", loja, None,
                  {"usuario_id": novo, "nome": nome_limpo, "papel": papel, "email": email_limpo},
                  conexao=conexao, alvo=f"usuario:{novo}")
        conexao.commit()
    except sqlite3.IntegrityError as erro:
        raise DadosInvalidos("Esse e-mail já é usado por outra pessoa.") from erro
    finally:
        conexao.close()
    return novo


def definir_email(usuario_id: int, email: str) -> bool:
    """Dá (ou troca) o e-mail de acesso. False se já era esse e-mail."""
    email_limpo = normalizar_email(email)
    from app.registro import registrar
    conexao = conectar()
    try:
        u = _usuario(conexao, usuario_id)
        _exigir_operador(u["loja_id"])
        if (u["email"] or "") == email_limpo:
            return False
        if conexao.execute("SELECT 1 FROM usuarios WHERE email = ? AND id != ?",
                           (email_limpo, usuario_id)).fetchone():
            raise DadosInvalidos("Esse e-mail já é usado por outra pessoa.")
        conexao.execute("UPDATE usuarios SET email = ? WHERE id = ?", (email_limpo, usuario_id))
        registrar("definir_email_acesso", u["loja_id"], {"email": u["email"]},
                  {"email": email_limpo}, conexao=conexao, alvo=f"usuario:{usuario_id}")
        conexao.commit()
    except sqlite3.IntegrityError as erro:
        raise DadosInvalidos("Esse e-mail já é usado por outra pessoa.") from erro
    finally:
        conexao.close()
    return True


def definir_senha(usuario_id: int, senha: str) -> bool:
    """O operador define ou redefine a senha (A5). O Registro só diz 'trocada'."""
    validar_senha(senha)
    from app.registro import registrar
    conexao = conectar()
    try:
        u = _usuario(conexao, usuario_id)
        _exigir_operador(u["loja_id"])
        conexao.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?",
                        (_hasher.hash(senha), usuario_id))
        registrar("redefinir_senha", u["loja_id"], {"tinha_senha": bool(u["senha_hash"])},
                  {"senha": "trocada"}, conexao=conexao, alvo=f"usuario:{usuario_id}")
        conexao.commit()
    finally:
        conexao.close()
    return True


# ------------------------------------------------------------ login

def bloqueado_por_tentativas(email, agora=None) -> bool:
    email_limpo = str(email or "").strip().lower()[:MAX_EMAIL]
    momento = agora or agora_utc()
    desde = para_banco(momento - timedelta(minutes=JANELA_TENTATIVAS_MIN))
    marcas = ", ".join("?" for _ in FALHAS)
    conexao = conectar()
    try:
        erros = conexao.execute(
            f"SELECT COUNT(*) FROM acessos WHERE email = ? AND quando >= ? AND quando <= ? "
            f"AND resultado IN ({marcas}) AND id > COALESCE((SELECT MAX(id) FROM acessos "
            f"WHERE email = ? AND resultado = ?), 0)",
            (email_limpo, desde, para_banco(momento), *FALHAS, email_limpo, OK)).fetchone()[0]
    finally:
        conexao.close()
    return erros >= MAX_TENTATIVAS


def autenticar(email, senha, agora=None) -> dict | None:
    """Devolve os dados da pessoa se e-mail e senha conferem; senão None.
    Nunca diz o motivo para quem tentou (o motivo fica na tabela acessos)."""
    email_limpo = str(email or "").strip().lower()[:MAX_EMAIL]
    senha_texto = senha if isinstance(senha, str) else ""
    momento = para_banco(agora or agora_utc())
    sql_acesso = "INSERT INTO acessos (usuario_id, email, quando, resultado) VALUES (?, ?, ?, ?)"
    if bloqueado_por_tentativas(email_limpo, agora):
        conexao = conectar()
        try:
            conexao.execute(sql_acesso, (None, email_limpo, momento, BLOQUEADO))
            conexao.commit()
        finally:
            conexao.close()
        return None
    conexao = conectar()
    try:
        u = conexao.execute("SELECT * FROM usuarios WHERE email = ?",
                            (email_limpo,)).fetchone() if email_limpo else None
        if u is None or not u["senha_hash"]:
            _verificar(_hash_falso(), senha_texto)          # mesmo tempo de uma senha errada
            resultado = "email_desconhecido" if u is None else "sem_senha"
        else:
            certa = _verificar(u["senha_hash"], senha_texto)
            resultado = (OK if u["ativo"] else "desativado") if certa else "senha_errada"
        conexao.execute(sql_acesso, (u["id"] if u is not None else None, email_limpo,
                                     momento, resultado))
        if resultado == OK:
            conexao.execute("UPDATE usuarios SET ultimo_acesso = ? WHERE id = ?", (momento, u["id"]))
            if _hasher.check_needs_rehash(u["senha_hash"]):
                conexao.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?",
                                (_hasher.hash(senha_texto), u["id"]))
        conexao.commit()
    finally:
        conexao.close()
    if resultado != OK:
        return None
    return {"id": u["id"], "nome": u["nome"], "papel": u["papel"],
            "rotulo_papel": rotulo_papel(u["papel"]), "loja_id": u["loja_id"], "email": email_limpo}


def listar_logins() -> list[dict]:
    """Todas as pessoas, com e sem acesso (só para o operador). Nunca devolve o hash."""
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT id, loja_id, nome, papel, email, ativo, senha_hash IS NOT NULL AS tem_senha, "
            "ultimo_acesso FROM usuarios ORDER BY loja_id IS NOT NULL, loja_id, id").fetchall()
    finally:
        conexao.close()
    return [{**dict(l), "rotulo_papel": rotulo_papel(l["papel"])} for l in linhas]

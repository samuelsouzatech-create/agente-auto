"""Qual loja é dona de cada canal (item 1.5; revisão da Etapa 1).

Tabela canais: tipo (whatsapp/telegram/instagram) + id_externo
(phone_number_id, id do bot, id da conta) -> loja_id.
token_ref guarda só o NOME da variável do .env com o token do canal.

Regra de resolução:
  1. id cadastrado e ativo -> loja dona dele
  2. NENHUM canal desse tipo cadastrado (nem desativado) -> loja 1
     (modo de transição, loja única)
  3. existem canais desse tipo, mas não este id (ou ele está desativado)
     -> None (a mensagem é ignorada). Desativar o único canal NÃO volta
     para a loja 1.
"""
import re

from banco import conectar
from app.chaves import LOJA_PADRAO

TIPOS_DE_CANAL = ("whatsapp", "telegram", "instagram")
_NOME_DE_VARIAVEL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,59}$")


def resolver_loja(tipo: str, id_externo) -> int | None:
    conexao = conectar()
    try:
        if id_externo:
            linha = conexao.execute(
                "SELECT loja_id FROM canais WHERE tipo = ? AND id_externo = ? AND ativo = 1",
                (tipo, str(id_externo)),
            ).fetchone()
            if linha:
                return linha["loja_id"]
        algum = conexao.execute(
            "SELECT 1 FROM canais WHERE tipo = ? LIMIT 1", (tipo,)
        ).fetchone()
    finally:
        conexao.close()
    return LOJA_PADRAO if algum is None else None


def existe_canal_do_tipo(tipo: str) -> bool:
    """Algum canal desse tipo já foi cadastrado (ativo ou desativado)?"""
    conexao = conectar()
    try:
        return conexao.execute(
            "SELECT 1 FROM canais WHERE tipo = ? LIMIT 1", (tipo,)
        ).fetchone() is not None
    finally:
        conexao.close()


def canal_ativo_da_loja(loja_id: int, tipo: str) -> dict | None:
    """O canal ativo daquele tipo nesta loja (o primeiro cadastrado), ou None."""
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT * FROM canais WHERE loja_id = ? AND tipo = ? AND ativo = 1 ORDER BY id LIMIT 1",
            (loja_id, tipo),
        ).fetchone()
    finally:
        conexao.close()
    return dict(linha) if linha else None


def cadastrar_canal(loja_id: int, tipo: str, id_externo: str, token_ref: str = "") -> None:
    """Liga um canal a uma loja. Se o canal já existia, move para esta loja e reativa."""
    if tipo not in TIPOS_DE_CANAL:
        raise ValueError(f"Tipo de canal inválido: {tipo}. Use: {', '.join(TIPOS_DE_CANAL)}.")
    if not str(id_externo).strip():
        raise ValueError("id_externo vazio.")
    token_ref = (token_ref or "").strip()
    if token_ref and not _NOME_DE_VARIAVEL.match(token_ref):
        raise ValueError("token_ref é o NOME de uma variável do .env "
                         "(ex.: WHATSAPP_TOKEN_LOJA2), nunca o token.")
    conexao = conectar()
    try:
        if not conexao.execute("SELECT 1 FROM lojas WHERE id = ?", (loja_id,)).fetchone():
            raise ValueError(f"Loja {loja_id} não existe.")
        conexao.execute(
            """INSERT INTO canais (loja_id, tipo, id_externo, token_ref, ativo)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT (tipo, id_externo) DO UPDATE SET
                   loja_id = excluded.loja_id,
                   token_ref = excluded.token_ref,
                   ativo = 1""",
            (loja_id, tipo, str(id_externo).strip(), token_ref),
        )
        conexao.commit()
    finally:
        conexao.close()


def desativar_canal(tipo: str, id_externo: str) -> None:
    conexao = conectar()
    try:
        conexao.execute("UPDATE canais SET ativo = 0 WHERE tipo = ? AND id_externo = ?",
                        (tipo, str(id_externo)))
        conexao.commit()
    finally:
        conexao.close()


def listar_canais(loja_id: int | None = None) -> list[dict]:
    conexao = conectar()
    try:
        if loja_id is None:
            linhas = conexao.execute("SELECT * FROM canais ORDER BY loja_id, tipo").fetchall()
        else:
            linhas = conexao.execute("SELECT * FROM canais WHERE loja_id = ? ORDER BY tipo",
                                     (loja_id,)).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]


def id_bot_telegram(token: str | None) -> str:
    """O id do bot é a parte do token antes dos dois-pontos ("123456:ABC" -> "123456")."""
    if not token or ":" not in token:
        return ""
    return token.split(":", 1)[0]

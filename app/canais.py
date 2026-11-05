"""Qual loja é dona de cada canal (item 1.5; P1 do Plano Mestre).

Tabela canais: tipo (whatsapp/telegram/instagram) + id_externo
(phone_number_id, id do bot, id da conta) -> loja_id.
token_ref guarda só o NOME da variável do .env com o token do canal.

Regra única: id cadastrado e ativo -> loja dona dele. Qualquer outro caso
(id desconhecido, desativado ou vazio) -> None, e a mensagem é ignorada.
Não existe loja padrão: mensagem sem dono não vai para loja nenhuma.

S4b (Fase 3): cadastrar e desativar exigem um ator e vão para o Registro na
mesma transação. A tela nova passa permitir_mover=False: canal que já é de
outra loja é recusado (CanalDeOutraLoja). A tela antiga continua movendo,
como antes, até sair no S10. Nada muda quando o canal já está igual.
"""
import re

from banco import conectar

TIPOS_DE_CANAL = ("whatsapp", "telegram", "instagram")
_NOME_DE_VARIAVEL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,59}$")


class CanalDeOutraLoja(ValueError):
    """O canal já está ligado a outra loja (a tela nova não move canal)."""


def nome_de_chave_valido(nome) -> bool:
    """O nome da variável do .env que guarda a chave (nunca a chave)."""
    return bool(_NOME_DE_VARIAVEL.match(str(nome or "")))


def resolver_loja(tipo: str, id_externo) -> int | None:
    """Loja dona do canal, ou None se o id não está cadastrado ou está desativado."""
    if not id_externo:
        return None
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT loja_id FROM canais WHERE tipo = ? AND id_externo = ? AND ativo = 1",
            (tipo, str(id_externo)),
        ).fetchone()
    finally:
        conexao.close()
    return linha["loja_id"] if linha else None


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


def _validar(tipo, id_externo, token_ref) -> tuple[str, str]:
    if tipo not in TIPOS_DE_CANAL:
        raise ValueError(f"Tipo de canal inválido: {tipo}. Use: {', '.join(TIPOS_DE_CANAL)}.")
    id_limpo = str(id_externo or "").strip()
    if not id_limpo:
        raise ValueError("id_externo vazio.")
    ref = (token_ref or "").strip()
    if ref and not nome_de_chave_valido(ref):
        raise ValueError("token_ref é o NOME de uma variável do .env "
                         "(ex.: WHATSAPP_TOKEN_LOJA2), nunca o token.")
    return id_limpo, ref


def cadastrar_canal(loja_id: int, tipo: str, id_externo: str, token_ref: str = "",
                    *, permitir_mover: bool = True) -> None:
    """Liga um canal a uma loja. Se o canal já existia, reativa (e, com
    permitir_mover=True, move para esta loja). Vai para o Registro."""
    id_limpo, ref = _validar(tipo, id_externo, token_ref)
    from app.registro import conferir_ator, registrar   # aqui dentro: evita import circular
    conexao = conectar()
    try:
        if not conexao.execute("SELECT 1 FROM lojas WHERE id = ?", (loja_id,)).fetchone():
            raise ValueError(f"Loja {loja_id} não existe.")
        conferir_ator(loja_id)
        linha = conexao.execute(
            "SELECT id, loja_id, token_ref, ativo FROM canais WHERE tipo = ? AND id_externo = ?",
            (tipo, id_limpo)).fetchone()
        if linha is not None and linha["loja_id"] != loja_id and not permitir_mover:
            raise CanalDeOutraLoja("Este canal já está ligado a outra loja. Nada foi mudado.")
        if linha is None:
            canal_id = conexao.execute(
                "INSERT INTO canais (loja_id, tipo, id_externo, token_ref, ativo) "
                "VALUES (?, ?, ?, ?, 1)", (loja_id, tipo, id_limpo, ref)).lastrowid
            antes = None
        else:
            mesma_loja = linha["loja_id"] == loja_id
            if mesma_loja and linha["ativo"] and (linha["token_ref"] or "") == ref:
                return                                   # nada mudou
            conexao.execute("UPDATE canais SET loja_id = ?, token_ref = ?, ativo = 1 WHERE id = ?",
                            (loja_id, ref, linha["id"]))
            canal_id = linha["id"]
            antes = {"tipo": tipo, "ativo": bool(linha["ativo"]),
                     "chave_no_servidor": bool(linha["token_ref"])}
            if not mesma_loja:
                antes["veio_de_outra_loja"] = True
        registrar("cadastrar_canal", loja_id, antes,
                  {"tipo": tipo, "ativo": True, "chave_no_servidor": bool(ref)},
                  conexao=conexao, alvo=f"canal:{canal_id}")
        conexao.commit()
    finally:
        conexao.close()


def _desativar(conexao, linha) -> None:
    from app.registro import registrar                  # aqui dentro: evita import circular
    conexao.execute("UPDATE canais SET ativo = 0 WHERE id = ?", (linha["id"],))
    registrar("desativar_canal", linha["loja_id"], {"tipo": linha["tipo"], "ativo": True},
              {"tipo": linha["tipo"], "ativo": False},
              conexao=conexao, alvo=f"canal:{linha['id']}")
    conexao.commit()


def desativar_canal(tipo: str, id_externo: str) -> None:
    """Tela antiga e scripts. Vai para o Registro da loja dona do canal."""
    from app.ator import exigir_ator                    # aqui dentro: evita import circular
    exigir_ator()
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT id, loja_id, tipo, ativo FROM canais WHERE tipo = ? AND id_externo = ?",
            (tipo, str(id_externo))).fetchone()
        if linha is None or not linha["ativo"]:
            return
        _desativar(conexao, linha)
    finally:
        conexao.close()


def desativar_canal_da_loja(loja_id: int, canal_id: int) -> bool:
    """Tela nova: só desativa canal DESTA loja. False se não achou ou já estava desativado."""
    from app.registro import conferir_ator              # aqui dentro: evita import circular
    conferir_ator(loja_id)
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT id, loja_id, tipo, ativo FROM canais WHERE id = ? AND loja_id = ?",
            (canal_id, loja_id)).fetchone()
        if linha is None or not linha["ativo"]:
            return False
        _desativar(conexao, linha)
        return True
    finally:
        conexao.close()


def reativar_canal_da_loja(loja_id: int, canal_id: int) -> bool:
    """Tela nova: reativa canal DESTA loja, com a mesma chave. False se não achou ou já ativo."""
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT tipo, id_externo, token_ref, ativo FROM canais WHERE id = ? AND loja_id = ?",
            (canal_id, loja_id)).fetchone()
    finally:
        conexao.close()
    if linha is None or linha["ativo"]:
        return False
    cadastrar_canal(loja_id, linha["tipo"], linha["id_externo"], linha["token_ref"] or "",
                    permitir_mover=False)
    return True


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

"""
Link do vendedor que vem no aviso (C3 do Plano Mestre; tabela da migração 17).

- Uso único e validade curta (VALIDADE). Só o mais novo vale: gerar outro para
  a mesma pessoa e a mesma conversa anula o anterior.
- O token vai só no link. No banco fica só o hash (SHA-256), como nas sessões.
- Quem recebe: dono, gestor ou vendedor, ativo, da loja do link, com a loja
  ligada. Abrir o link cria a sessão de escopo "link" (sessoes.py): só aquela
  conversa, com assumir, responder, devolver e registrar venda.
- Motivos de recusa (contrato): usado, vencido, revogado. Token desconhecido
  ou mal escrito = vencido. Pessoa desativada, de outra loja ou loja
  desligada = revogado.
- Abrir o link anota em acessos (como o login), não no Registro.
- Links errados demais da mesma origem: link_errado_demais (a rota dá 429).
- Endereços: o link aponta para a API (API_PUBLICA_URL); depois de abrir,
  a API leva ao front (PAINEL_URL), sem o token no endereço.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import timedelta
from urllib.parse import quote

from banco import conectar
from app import autenticacao, sessoes
from app.chaves import exigir_loja
from app.relogio import agora_utc, para_banco

VALIDADE = timedelta(hours=12)
MAX_LINK_ERRADO = 10
JANELA_MIN = autenticacao.JANELA_TENTATIVAS_MIN
MIN_TOKEN = 22
MAX_TOKEN = 128
API_URL_PADRAO = "http://127.0.0.1:8001"
PAINEL_URL_PADRAO = "http://localhost:5173"
CAMINHO_NA_API = "/api/v1/v/"
USADO, VENCIDO, REVOGADO = "usado", "vencido", "revogado"
MOTIVOS = (USADO, VENCIDO, REVOGADO)

# Resultados gravados na tabela acessos.
ENTROU = "link_vendedor"
LINK_ERRADO = "link_vendedor_invalido"

_SQL_ACESSO = "INSERT INTO acessos (usuario_id, email, quando, resultado) VALUES (?, ?, ?, ?)"
_SQL_LINK = ("SELECT k.id, k.usuario_id, k.loja_id, k.lead_id, k.expira_em, k.usado_em, "
             "k.revogado_em, u.email, u.papel, u.ativo, u.loja_id AS loja_da_pessoa, "
             "l.ativo AS loja_ativa FROM links_vendedor k "
             "JOIN usuarios u ON u.id = k.usuario_id LEFT JOIN lojas l ON l.id = k.loja_id "
             "WHERE k.token_hash = ?")


class LinkRecusado(ValueError):
    """O link não abre. 'motivo' é usado, vencido ou revogado."""

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


class SemAcesso(ValueError):
    """Esta pessoa não pode receber link desta loja (ou falta a conversa)."""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_ok(token) -> bool:
    return isinstance(token, str) and MIN_TOKEN <= len(token) <= MAX_TOKEN


def _base(variavel: str, padrao: str) -> str:
    return (os.environ.get(variavel) or padrao).strip().rstrip("/") or padrao


def montar_link(token: str) -> str:
    return f"{_base('API_PUBLICA_URL', API_URL_PADRAO)}{CAMINHO_NA_API}{token}"


def url_da_conversa(lead_id: str) -> str:
    return f"{_base('PAINEL_URL', PAINEL_URL_PADRAO)}/conversas/{quote(lead_id, safe='')}"


def url_link_invalido(motivo: str) -> str:
    motivo = motivo if motivo in MOTIVOS else VENCIDO
    return f"{_base('PAINEL_URL', PAINEL_URL_PADRAO)}/link-invalido?motivo={motivo}"


def _pode(papel, ativo, loja_da_pessoa, loja_ativa, loja_id) -> bool:
    return (papel in sessoes.PAPEIS_COM_LOGIN and bool(ativo)
            and loja_da_pessoa == loja_id and bool(loja_ativa))


# ------------------------------------------------------------ gerar (quem avisa chama)

def gerar_link(loja_id, usuario_id, lead_id, agora=None, conexao=None) -> str:
    """Devolve o link para mandar à pessoa. Com 'conexao', NÃO dá commit."""
    loja = exigir_loja(loja_id)
    lead = str(lead_id or "").strip()[:sessoes.MAX_LEAD]
    if not lead:
        raise SemAcesso("Falta a conversa do link.")
    momento = agora or agora_utc()
    texto = para_banco(momento)
    propria = conexao is None
    con = conectar() if propria else conexao
    try:
        u = con.execute("SELECT u.papel, u.ativo, u.loja_id, l.ativo AS loja_ativa FROM usuarios u "
                        "LEFT JOIN lojas l ON l.id = u.loja_id WHERE u.id = ?",
                        (usuario_id,)).fetchone()
        if u is None or not _pode(u["papel"], u["ativo"], u["loja_id"], u["loja_ativa"], loja):
            raise SemAcesso("Esta pessoa não recebe link desta loja.")
        con.execute("UPDATE links_vendedor SET revogado_em = ? WHERE loja_id = ? AND usuario_id = ? "
                    "AND lead_id = ? AND usado_em IS NULL AND revogado_em IS NULL",
                    (texto, loja, usuario_id, lead))
        token = secrets.token_urlsafe(32)
        con.execute("INSERT INTO links_vendedor (token_hash, loja_id, usuario_id, lead_id, criado_em, "
                    "expira_em) VALUES (?, ?, ?, ?, ?, ?)",
                    (_hash(token), loja, usuario_id, lead, texto, para_banco(momento + VALIDADE)))
        if propria:
            con.commit()
    finally:
        if propria:
            con.close()
    return montar_link(token)


# ------------------------------------------------------------ abrir (a rota chama)

def _motivo(linha, agora_txt: str) -> str | None:
    if linha is None:
        return VENCIDO
    if linha["usado_em"]:
        return USADO
    if linha["revogado_em"]:
        return REVOGADO
    if linha["expira_em"] <= agora_txt:
        return VENCIDO
    if not _pode(linha["papel"], linha["ativo"], linha["loja_da_pessoa"], linha["loja_ativa"],
                 linha["loja_id"]):
        return REVOGADO
    return None


def usar_link(token, agora=None) -> dict:
    """Abre o link (uso único). Devolve {"sessao": token da sessão, "lead_id"}.
    Tudo numa transação: marcar como usado, criar a sessão e anotar em acessos."""
    if not _token_ok(token):
        raise LinkRecusado(VENCIDO)
    momento = agora or agora_utc()
    texto = para_banco(momento)
    conexao = conectar()
    try:
        linha = conexao.execute(_SQL_LINK, (_hash(token),)).fetchone()
        motivo = _motivo(linha, texto)
        if motivo:
            raise LinkRecusado(motivo)
        marcou = conexao.execute(
            "UPDATE links_vendedor SET usado_em = ? WHERE id = ? AND usado_em IS NULL "
            "AND revogado_em IS NULL AND expira_em > ?", (texto, linha["id"], texto)).rowcount
        if marcou != 1:
            raise LinkRecusado(USADO)              # outro clique no mesmo instante
        try:
            sessao = sessoes.criar_sessao(linha["usuario_id"], linha["loja_id"], sessoes.PAPEL_LINK,
                                          escopo=sessoes.LINK, lead_id=linha["lead_id"],
                                          agora=momento, conexao=conexao)
        except sessoes.SessaoInvalida:
            raise LinkRecusado(REVOGADO) from None
        conexao.execute(_SQL_ACESSO, (linha["usuario_id"], linha["email"], texto, ENTROU))
        conexao.commit()
    finally:
        conexao.close()
    return {"sessao": sessao, "lead_id": linha["lead_id"]}


# ------------------------------------------------------------ links errados (limite)

def _chave_origem(origem) -> str:
    return "vlink:" + str(origem or "desconhecida")[:200]


def link_errado_demais(origem, agora=None) -> bool:
    momento = agora or agora_utc()
    desde = para_banco(momento - timedelta(minutes=JANELA_MIN))
    conexao = conectar()
    try:
        erros = conexao.execute(
            "SELECT COUNT(*) FROM acessos WHERE email = ? AND resultado = ? AND quando >= ? "
            "AND quando <= ?", (_chave_origem(origem), LINK_ERRADO, desde, para_banco(momento))
        ).fetchone()[0]
    finally:
        conexao.close()
    return erros >= MAX_LINK_ERRADO


def anotar_link_errado(origem, agora=None) -> None:
    conexao = conectar()
    try:
        conexao.execute(_SQL_ACESSO, (None, _chave_origem(origem),
                                      para_banco(agora or agora_utc()), LINK_ERRADO))
        conexao.commit()
    finally:
        conexao.close()

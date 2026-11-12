"""
Sessões do painel do cliente (C2a do Plano Mestre; tabela da migração 15).

- O token vai só no cookie leo_sessao. No banco fica só o hash (SHA-256):
  quem lê o banco não consegue entrar como ninguém.
- O código contra pedido forjado (CSRF) é calculado a partir do token. Não
  precisa de coluna, e quem não tem o cookie não consegue calculá-lo.
- A sessão diz a loja e o papel. A API nunca aceita a loja vinda do pedido.
- Papéis e escopos (decisão D1, contrato v1):
    dono, gestor  -> escopo "completo"    (login)
    vendedor      -> escopo "atendimento" (login; só Atender e Leads)
    vendedor_link -> escopo "link"        (link do aviso, C3; uma conversa só)
  Operador e suporte não ganham sessão aqui: o painel deles é o Streamlit.
- A sessão deixa de valer quando vence (7 dias; 12 h na de link), quando é revogada (sair,
  troca de senha), quando a pessoa é desativada, muda de loja ou de papel,
  ou quando a loja é desligada. ler_sessao devolve None, sem dizer o motivo.
- sessao_sem_acesso: sessão em dia, mas de quem não usa este painel
  (operador, suporte). A API responde 403 nesse caso, e não 401.
- Nada aqui imprime ou grava o token em log.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from banco import conectar
from app.chaves import exigir_loja
from app.relogio import agora_utc, para_banco

DURACAO = timedelta(days=7)
COMPLETO = "completo"
ATENDIMENTO = "atendimento"
LINK = "link"
ESCOPOS = (COMPLETO, ATENDIMENTO, LINK)
# C3c (analista): a sessão do link dura o mesmo que o link, 12 h.
DURACAO_LINK = timedelta(hours=12)


def duracao_do_escopo(escopo) -> timedelta:
    """Quanto a sessão vale: 12 h no escopo link, 7 dias nos outros."""
    return DURACAO_LINK if escopo == LINK else DURACAO


PAPEL_LINK = "vendedor_link"
ESCOPO_DO_PAPEL = {"dono": COMPLETO, "gestor": COMPLETO, "vendedor": ATENDIMENTO, PAPEL_LINK: LINK}
PAPEIS_COM_LOGIN = ("dono", "gestor", "vendedor")
PAPEIS_DA_SESSAO = tuple(ESCOPO_DO_PAPEL)
PAPEIS_SEM_PAINEL = ("operador", "suporte")
MIN_TOKEN = 20
MAX_TOKEN = 128
MAX_LEAD = 80

_SQL_LER = (
    "SELECT s.id, s.usuario_id, s.loja_id, s.papel, s.escopo, s.lead_id, s.criado_em, "
    "s.expira_em, u.nome, u.email, u.loja_id AS loja_da_pessoa, u.papel AS papel_da_pessoa, "
    "u.ativo AS pessoa_ativa, l.ativo AS loja_ativa "
    "FROM sessoes s JOIN usuarios u ON u.id = s.usuario_id JOIN lojas l ON l.id = s.loja_id "
    "WHERE s.token_hash = ? AND s.revogada_em IS NULL AND s.expira_em > ?")


class SessaoInvalida(ValueError):
    """Pedido de sessão que não pode existir (papel, loja, escopo ou pessoa errados)."""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_ok(token) -> bool:
    return isinstance(token, str) and MIN_TOKEN <= len(token) <= MAX_TOKEN


def csrf_da(token: str) -> str:
    """O valor que o front manda no cabeçalho X-CSRF-Token."""
    return hashlib.sha256(("csrf:" + token).encode("utf-8")).hexdigest()


def conferir_csrf(token, valor) -> bool:
    if not _token_ok(token) or not isinstance(valor, str) or not valor:
        return False
    return hmac.compare_digest(csrf_da(token), valor)


def _pessoa_combina(loja_da_pessoa, papel_da_pessoa, ativa, loja_id, papel, escopo) -> bool:
    if not ativa or loja_da_pessoa != loja_id:
        return False
    if ESCOPO_DO_PAPEL.get(papel) != escopo:
        return False
    if escopo == LINK:
        return papel_da_pessoa in PAPEIS_COM_LOGIN      # quem recebeu o aviso (C3)
    return papel_da_pessoa == papel


def criar_sessao(usuario_id: int, loja_id, papel: str, escopo=None, lead_id=None,
                 agora=None, conexao=None) -> str:
    """Cria a sessão e devolve o TOKEN (vai só para o cookie, nunca para log).
    Sem 'escopo', usa o escopo do papel. Com 'conexao', usa a transação de
    quem chamou e NÃO dá commit."""
    loja = exigir_loja(loja_id)
    escopo = escopo or ESCOPO_DO_PAPEL.get(papel)
    if escopo not in ESCOPOS or ESCOPO_DO_PAPEL.get(papel) != escopo:
        raise SessaoInvalida("Papel ou escopo que não entram no painel da loja.")
    lead = None if lead_id is None else (str(lead_id).strip()[:MAX_LEAD] or None)
    if (escopo == LINK) != (lead is not None):
        raise SessaoInvalida("Só a sessão de link tem uma conversa, e ela precisa da conversa.")
    momento = agora or agora_utc()
    propria = conexao is None
    con = conectar() if propria else conexao
    try:
        u = con.execute("SELECT loja_id, papel, ativo FROM usuarios WHERE id = ?",
                        (usuario_id,)).fetchone()
        if u is None or not _pessoa_combina(u["loja_id"], u["papel"], u["ativo"],
                                            loja, papel, escopo):
            raise SessaoInvalida("Esta pessoa não entra nesta loja com este papel.")
        token = secrets.token_urlsafe(32)
        con.execute(
            "INSERT INTO sessoes (token_hash, usuario_id, loja_id, papel, escopo, lead_id, "
            "criado_em, expira_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (_hash(token), usuario_id, loja, papel, escopo, lead,
             para_banco(momento), para_banco(momento + duracao_do_escopo(escopo))))
        if propria:
            con.commit()
    finally:
        if propria:
            con.close()
    return token


def ler_sessao(token, agora=None) -> dict | None:
    """A sessão do token, se ainda vale; senão None (sem dizer o motivo)."""
    if not _token_ok(token):
        return None
    conexao = conectar()
    try:
        linha = conexao.execute(_SQL_LER, (_hash(token), para_banco(agora or agora_utc()))).fetchone()
    finally:
        conexao.close()
    if linha is None or not linha["loja_ativa"]:
        return None
    if not _pessoa_combina(linha["loja_da_pessoa"], linha["papel_da_pessoa"], linha["pessoa_ativa"],
                           linha["loja_id"], linha["papel"], linha["escopo"]):
        return None
    return {"id": linha["id"], "usuario_id": linha["usuario_id"], "loja_id": linha["loja_id"],
            "papel": linha["papel"], "escopo": linha["escopo"], "lead_id": linha["lead_id"],
            "nome": linha["nome"], "email": linha["email"], "expira_em": linha["expira_em"]}


def sessao_sem_acesso(token, agora=None) -> bool:
    """True se o token é de uma sessão em dia, mas de quem não usa este painel
    (operador, suporte ou papel desconhecido). A API responde 403, não 401."""
    if not _token_ok(token):
        return False
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT s.papel, u.papel AS papel_da_pessoa FROM sessoes s "
            "JOIN usuarios u ON u.id = s.usuario_id "
            "WHERE s.token_hash = ? AND s.revogada_em IS NULL AND s.expira_em > ?",
            (_hash(token), para_banco(agora or agora_utc()))).fetchone()
    finally:
        conexao.close()
    if linha is None:
        return False
    return linha["papel"] not in PAPEIS_DA_SESSAO or linha["papel_da_pessoa"] in PAPEIS_SEM_PAINEL


def revogar(token, agora=None) -> bool:
    """Sair: encerra esta sessão. False se não existia ou já estava encerrada."""
    if not _token_ok(token):
        return False
    conexao = conectar()
    try:
        total = conexao.execute(
            "UPDATE sessoes SET revogada_em = ? WHERE token_hash = ? AND revogada_em IS NULL",
            (para_banco(agora or agora_utc()), _hash(token))).rowcount
        conexao.commit()
    finally:
        conexao.close()
    return total > 0


def revogar_todas_da_pessoa(usuario_id: int, exceto_token=None, agora=None, conexao=None) -> int:
    """Encerra as sessões abertas da pessoa (menos a de exceto_token).
    Com 'conexao', NÃO dá commit (quem chamou fecha a transação)."""
    sql = "UPDATE sessoes SET revogada_em = ? WHERE usuario_id = ? AND revogada_em IS NULL"
    valores = [para_banco(agora or agora_utc()), usuario_id]
    if _token_ok(exceto_token):
        sql += " AND token_hash != ?"
        valores.append(_hash(exceto_token))
    propria = conexao is None
    con = conectar() if propria else conexao
    try:
        total = con.execute(sql, valores).rowcount
        if propria:
            con.commit()
    finally:
        if propria:
            con.close()
    return total

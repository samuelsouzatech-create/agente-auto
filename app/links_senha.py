"""
Links de criar e de redefinir senha (C2f do Plano Mestre; tabela da migração 16).

- Sem senha provisória (decisão D5): ninguém, nem o operador, conhece a senha
  de outra pessoa. A pessoa cria a própria senha por um link.
- O token vai só no link. No banco fica só o hash (SHA-256), como nas sessões.
- Uso único e validade curta: VALIDADE_PEDIDO quando a pessoa pede ("esqueci
  a senha"), VALIDADE_OPERADOR quando o operador gera, copia e manda.
- Só vale o link mais novo: gerar outro anula os abertos da mesma pessoa.
- "Esqueci a senha" não diz se o e-mail existe: quem chama responde sempre
  igual. Limite: MAX_PEDIDOS por e-mail na janela (exista ou não o e-mail).
- Link errado demais da mesma origem: MuitasTentativas (MAX_LINK_ERRADO).
- Só ganha link quem entra no painel: dono, gestor ou vendedor, ativo, com
  e-mail e com a loja ligada. O resto recebe a mesma resposta, sem link.
- Criar a senha: na mesma transação grava o hash novo, marca o link como
  usado, encerra TODAS as sessões da pessoa, anota em acessos e grava no
  Registro (só "trocada", nunca a senha). A pessoa entra depois pelo login.
- Senha fraca não gasta o link: a pessoa tenta de novo com o mesmo link.
- Envio: ENVIADOR. Até haver provedor de e-mail, só escreve no terminal.
- O link aponta para o front: PAINEL_URL + /criar-senha#token=... O que vem
  depois do # o navegador nunca manda ao servidor (não cai em log).
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sys
from datetime import timedelta

from banco import conectar
from app import autenticacao
from app.estado_loja import SoOperador
from app.relogio import agora_utc, para_banco

CRIAR = "criar"
REDEFINIR = "redefinir"
TIPOS = (CRIAR, REDEFINIR)
VALIDADE_PEDIDO = timedelta(hours=1)
VALIDADE_OPERADOR = timedelta(hours=24)
PAPEIS_COM_LINK = ("dono", "gestor", "vendedor")
MAX_PEDIDOS = 3
MAX_LINK_ERRADO = 10
JANELA_MIN = autenticacao.JANELA_TENTATIVAS_MIN
MIN_TOKEN = 22
MAX_TOKEN = 128
PAINEL_URL_PADRAO = "http://localhost:5173"
CAMINHO_NO_FRONT = "/criar-senha#token="
MENSAGEM_PEDIDO = "Se este e-mail estiver cadastrado, enviaremos um link para criar uma nova senha."

# Resultados gravados na tabela acessos (a coluna não tem CHECK de propósito).
PEDIU_LINK = "pediu_link"
LINK_ERRADO = "link_invalido"
SENHA_POR_LINK = "senha_por_link"

_COLUNAS = ("u.id, u.loja_id, u.nome, u.papel, u.email, u.senha_hash, u.ativo, "
            "l.ativo AS loja_ativa")
_SQL_POR_EMAIL = (f"SELECT {_COLUNAS} FROM usuarios u LEFT JOIN lojas l ON l.id = u.loja_id "
                  "WHERE u.email = ?")
_SQL_POR_ID = (f"SELECT {_COLUNAS} FROM usuarios u LEFT JOIN lojas l ON l.id = u.loja_id "
               "WHERE u.id = ?")
_SQL_LINK = (f"SELECT k.id AS link_id, k.tipo, {_COLUNAS} FROM links_senha k "
             "JOIN usuarios u ON u.id = k.usuario_id LEFT JOIN lojas l ON l.id = u.loja_id "
             "WHERE k.token_hash = ? AND k.usado_em IS NULL AND k.revogado_em IS NULL "
             "AND k.expira_em > ?")
_SQL_ACESSO = "INSERT INTO acessos (usuario_id, email, quando, resultado) VALUES (?, ?, ?, ?)"


class LinkInvalido(ValueError):
    """Link usado, vencido, anulado, de quem não entra mais, ou que nunca existiu."""


class SemAcesso(ValueError):
    """Esta pessoa não pode receber link (o operador vê a mensagem)."""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_ok(token) -> bool:
    return isinstance(token, str) and MIN_TOKEN <= len(token) <= MAX_TOKEN


def _motivo_sem_link(u) -> str | None:
    if u["papel"] not in PAPEIS_COM_LINK:
        return "Operador e suporte não usam o painel da loja."
    if not u["ativo"]:
        return "Esta pessoa está desativada. Reative antes de gerar o link."
    if not u["email"]:
        return "Esta pessoa ainda não tem e-mail de acesso. Cadastre o e-mail antes."
    if not u["loja_id"] or not u["loja_ativa"]:
        return "A loja desta pessoa está desligada."
    return None


def _pode_ter_link(u) -> bool:
    return u is not None and _motivo_sem_link(u) is None


def montar_link(token: str) -> str:
    base = (os.environ.get("PAINEL_URL") or PAINEL_URL_PADRAO).strip().rstrip("/")
    return f"{base or PAINEL_URL_PADRAO}{CAMINHO_NO_FRONT}{token}"


def _enviar_pelo_terminal(email, link, tipo) -> None:
    acao = "criar" if tipo == CRIAR else "redefinir"
    print(f"[e-mail ainda sem provedor; nada foi enviado] Para: {email} | "
          f"link para {acao} a senha: {link}", file=sys.stderr, flush=True)


# Quem "envia" o link. Troque por um provedor de e-mail quando houver.
ENVIADOR = _enviar_pelo_terminal


def _novo_link(conexao, pessoa, tipo, momento, validade) -> tuple[str, str]:
    """Anula os links abertos da pessoa e grava um novo. NÃO dá commit."""
    agora_txt = para_banco(momento)
    expira = para_banco(momento + validade)
    conexao.execute("UPDATE links_senha SET revogado_em = ? WHERE usuario_id = ? "
                    "AND usado_em IS NULL AND revogado_em IS NULL", (agora_txt, pessoa["id"]))
    token = secrets.token_urlsafe(32)
    conexao.execute("INSERT INTO links_senha (token_hash, usuario_id, loja_id, tipo, criado_em, "
                    "expira_em) VALUES (?, ?, ?, ?, ?, ?)",
                    (_hash(token), pessoa["id"], pessoa["loja_id"], tipo, agora_txt, expira))
    return token, expira


def _contar(conexao, chave, resultado, momento) -> int:
    desde = para_banco(momento - timedelta(minutes=JANELA_MIN))
    return conexao.execute(
        "SELECT COUNT(*) FROM acessos WHERE email = ? AND resultado = ? AND quando >= ? "
        "AND quando <= ?", (chave, resultado, desde, para_banco(momento))).fetchone()[0]


# ------------------------------------------------------------ esqueci a senha (público)

def pedir_link(email, agora=None) -> None:
    """Não diz se o e-mail existe. MuitasTentativas se o mesmo e-mail pediu
    MAX_PEDIDOS vezes na janela (exista ou não)."""
    email_limpo = str(email or "").strip().lower()[:autenticacao.MAX_EMAIL]
    momento = agora or agora_utc()
    envio = None
    conexao = conectar()
    try:
        if _contar(conexao, email_limpo, PEDIU_LINK, momento) >= MAX_PEDIDOS:
            raise autenticacao.MuitasTentativas("Muitas tentativas seguidas. Espere alguns minutos.")
        u = conexao.execute(_SQL_POR_EMAIL, (email_limpo,)).fetchone() if email_limpo else None
        if _pode_ter_link(u):
            token, _ = _novo_link(conexao, u, REDEFINIR, momento, VALIDADE_PEDIDO)
            envio = (u["email"], montar_link(token), REDEFINIR)
        conexao.execute(_SQL_ACESSO, (u["id"] if u is not None else None, email_limpo,
                                      para_banco(momento), PEDIU_LINK))
        conexao.commit()
    finally:
        conexao.close()
    if envio:
        ENVIADOR(*envio)


# ------------------------------------------------------------ links errados (limite)

def _chave_origem(origem) -> str:
    return "link:" + str(origem or "desconhecida")[:200]


def link_errado_demais(origem, agora=None) -> bool:
    conexao = conectar()
    try:
        return _contar(conexao, _chave_origem(origem), LINK_ERRADO,
                       agora or agora_utc()) >= MAX_LINK_ERRADO
    finally:
        conexao.close()


def anotar_link_errado(origem, agora=None) -> None:
    conexao = conectar()
    try:
        conexao.execute(_SQL_ACESSO, (None, _chave_origem(origem),
                                      para_banco(agora or agora_utc()), LINK_ERRADO))
        conexao.commit()
    finally:
        conexao.close()


# ------------------------------------------------------------ criar a senha pelo link

def pessoa_do_link(token, agora=None) -> dict | None:
    """Quem o link atende, se ele ainda vale (só lê). None = inválido, sem motivo.
    A rota usa isto para definir o ator antes de chamar criar_senha (P6)."""
    if not _token_ok(token):
        return None
    conexao = conectar()
    try:
        linha = conexao.execute(_SQL_LINK, (_hash(token), para_banco(agora or agora_utc()))).fetchone()
    finally:
        conexao.close()
    if not _pode_ter_link(linha):
        return None
    return {"usuario_id": linha["id"], "nome": linha["nome"], "loja_id": linha["loja_id"],
            "tipo": linha["tipo"]}


def criar_senha(token, senha_nova, agora=None) -> int:
    """Cria a senha pelo link (uso único). Devolve quantas sessões foram encerradas.
    Ordem: link válido, ator, senha forte. Senha fraca NÃO gasta o link."""
    from app.registro import conferir_ator, registrar   # aqui dentro: evita import circular
    from app.sessoes import revogar_todas_da_pessoa
    if not _token_ok(token):
        raise LinkInvalido("Este link já foi usado ou venceu.")
    momento = agora or agora_utc()
    texto = para_banco(momento)
    conexao = conectar()
    try:
        linha = conexao.execute(_SQL_LINK, (_hash(token), texto)).fetchone()
        if not _pode_ter_link(linha):
            raise LinkInvalido("Este link já foi usado ou venceu.")
        conferir_ator(linha["loja_id"])                  # sem ator, nada acontece
        autenticacao.validar_senha(senha_nova)
        marcou = conexao.execute(
            "UPDATE links_senha SET usado_em = ? WHERE id = ? AND usado_em IS NULL "
            "AND revogado_em IS NULL", (texto, linha["link_id"])).rowcount
        if marcou != 1:
            raise LinkInvalido("Este link já foi usado ou venceu.")
        conexao.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?",
                        (autenticacao._hasher.hash(senha_nova), linha["id"]))
        encerradas = revogar_todas_da_pessoa(linha["id"], agora=momento, conexao=conexao)
        conexao.execute(_SQL_ACESSO, (linha["id"], linha["email"], texto, SENHA_POR_LINK))
        registrar("criar_senha_por_link", linha["loja_id"], None,
                  {"senha": "trocada", "tipo": linha["tipo"], "sessoes_encerradas": encerradas},
                  conexao=conexao, alvo=f"usuario:{linha['id']}", agora=momento)
        conexao.commit()
    finally:
        conexao.close()
    return encerradas


# ------------------------------------------------------------ o operador gera o link

def gerar_link_pelo_operador(usuario_id, agora=None) -> dict:
    """Só o operador. Devolve {"link", "tipo", "expira_em"} para ele copiar.
    O Registro guarda tipo e validade, nunca o token."""
    from app.registro import conferir_ator, registrar   # aqui dentro: evita import circular
    momento = agora or agora_utc()
    conexao = conectar()
    try:
        u = conexao.execute(_SQL_POR_ID, (usuario_id,)).fetchone()
        if u is None:
            raise SemAcesso("Pessoa não encontrada.")
        if conferir_ator(u["loja_id"]).papel != "operador":
            raise SoOperador("Só o operador gera link de senha.")
        motivo = _motivo_sem_link(u)
        if motivo:
            raise SemAcesso(motivo)
        tipo = REDEFINIR if u["senha_hash"] else CRIAR
        token, expira = _novo_link(conexao, u, tipo, momento, VALIDADE_OPERADOR)
        registrar("gerar_link_senha", u["loja_id"], None, {"tipo": tipo, "expira_em": expira},
                  conexao=conexao, alvo=f"usuario:{u['id']}", agora=momento)
        conexao.commit()
    finally:
        conexao.close()
    return {"link": montar_link(token), "tipo": tipo, "expira_em": expira}

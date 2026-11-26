"""
Cofre dos tokens dos canais (SE2, Maratona Segurança; migração 22).

O token de envio de cada canal (WhatsApp, Instagram, Telegram) de cada loja fica no banco CIFRADO
(tabela cofre_credenciais), com AES-256-GCM. A chave mestra fica SÓ no .env (LEO_CHAVE_MESTRA):
nunca no banco, nunca no Git, nunca em log. Sem a chave, o banco (ou um backup dele) não entrega
token nenhum.

- Cada token é cifrado "amarrado" à loja, ao canal e à conta (dado associado do GCM): copiar o
  texto cifrado de uma loja para outra linha NÃO abre (o GCM recusa).
- chave_id: as 8 primeiras letras do resumo (SHA-256) da chave que cifrou. Serve para dizer
  "a chave do .env não é a que cifrou este token" sem tentar abrir. Não revela a chave.
- Ordem do envio (app/credenciais.py): 1) o cofre; 2) se o cofre não tem o token desta conta, o
  token_ref antigo (nome da variável do .env) continua valendo como RESERVA, com um aviso no log.
- O token nunca aparece em log, tela nem API: as funções daqui só devolvem o token para quem vai
  enviar (credenciais.py); as outras dizem só "guardado" ou "não guardado".
Script: scripts/cofre.py (gerar chave, cadastrar e trocar token, trocar a chave mestra).
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets

from app.chaves import exigir_loja
from banco import conectar

VERSAO = "v1"
TIPOS = ("whatsapp", "instagram", "telegram")


class ErroCofre(RuntimeError):
    """Sem chave, chave errada, ou token que não abre. A mensagem nunca tem token nem chave."""


# ------------------------------------------------------------ chave
def nova_chave() -> str:
    """Chave mestra nova (32 bytes aleatórios em base64), para pôr no .env."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def _ler_chave(texto: str | None, nome: str = "LEO_CHAVE_MESTRA") -> bytes:
    texto = (texto or "").strip()
    if not texto:
        raise ErroCofre(f"Falta a {nome} no .env (gere com: python scripts/cofre.py nova-chave).")
    try:
        chave = base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))
    except Exception:
        raise ErroCofre(f"A {nome} do .env não é uma chave válida.") from None
    if len(chave) != 32:
        raise ErroCofre(f"A {nome} do .env não é uma chave válida (precisa de 32 bytes).")
    return chave


def chave_mestra() -> bytes:
    return _ler_chave(os.environ.get("LEO_CHAVE_MESTRA"))


def tem_chave() -> bool:
    try:
        chave_mestra()
        return True
    except ErroCofre:
        return False


def id_da_chave(chave: bytes) -> str:
    return hashlib.sha256(b"leo-cofre:" + chave).hexdigest()[:8]


def _amarra(loja_id: int, tipo: str, conta: str) -> bytes:
    return f"leo:{int(loja_id)}:{tipo}:{conta}".encode()


def cifrar(token: str, loja_id: int, tipo: str, conta: str, chave: bytes | None = None) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    chave = chave or chave_mestra()
    nonce = secrets.token_bytes(12)
    cifrado = AESGCM(chave).encrypt(nonce, token.encode("utf-8"), _amarra(loja_id, tipo, conta))
    return f"{VERSAO}:" + base64.urlsafe_b64encode(nonce + cifrado).decode()


def decifrar(texto: str, loja_id: int, tipo: str, conta: str, chave: bytes | None = None) -> str:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    chave = chave or chave_mestra()
    versao, _, corpo = str(texto or "").partition(":")
    if versao != VERSAO:
        raise ErroCofre("Token guardado num formato desconhecido.")
    try:
        bruto = base64.urlsafe_b64decode(corpo)
        return AESGCM(chave).decrypt(bruto[:12], bruto[12:], _amarra(loja_id, tipo, conta)).decode("utf-8")
    except (InvalidTag, ValueError):
        raise ErroCofre("O token guardado não abre com esta chave (chave errada ou dado alterado).") from None


# ------------------------------------------------------------ guardar e ler
def _validar(tipo: str, conta: str, token: str | None = None) -> tuple[str, str]:
    if tipo not in TIPOS:
        raise ValueError(f"Canal inválido: use {', '.join(TIPOS)}.")
    conta = str(conta or "").strip()
    if not conta:
        raise ValueError("Informe a conta (o número, a conta do Instagram ou o bot).")
    if token is not None and not str(token).strip():
        raise ValueError("Token vazio.")
    return tipo, conta


def guardar_token(loja_id, tipo: str, conta: str, token: str) -> None:
    """Cadastra ou TROCA o token desta conta desta loja (cifrado)."""
    loja_id = exigir_loja(loja_id)
    tipo, conta = _validar(tipo, conta, token)
    chave = chave_mestra()
    cifrado = cifrar(str(token).strip(), loja_id, tipo, conta, chave)
    conexao = conectar()
    try:
        conexao.execute(
            "INSERT INTO cofre_credenciais (loja_id, tipo_canal, conta, token_cifrado, chave_id) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (loja_id, tipo_canal, conta) DO UPDATE SET "
            "token_cifrado = EXCLUDED.token_cifrado, chave_id = EXCLUDED.chave_id, atualizado_em = agora_texto()",
            (loja_id, tipo, conta, cifrado, id_da_chave(chave)))
        conexao.commit()
    finally:
        conexao.close()


def apagar_token(loja_id, tipo: str, conta: str) -> bool:
    loja_id = exigir_loja(loja_id)
    tipo, conta = _validar(tipo, conta)
    conexao = conectar()
    try:
        n = conexao.execute("DELETE FROM cofre_credenciais WHERE loja_id = ? AND tipo_canal = ? AND conta = ?",
                            (loja_id, tipo, conta)).rowcount
        conexao.commit()
    finally:
        conexao.close()
    return bool(n)


def ler_token(loja_id, tipo: str, conta: str) -> str | None:
    """O token desta conta desta loja, ou None se o cofre não tem. ErroCofre se tem e não abre."""
    loja_id = exigir_loja(loja_id)
    tipo, conta = _validar(tipo, conta)
    conexao = conectar(somente_leitura=True)
    try:
        linha = conexao.execute("SELECT token_cifrado FROM cofre_credenciais WHERE loja_id = ? "
                                "AND tipo_canal = ? AND conta = ?", (loja_id, tipo, conta)).fetchone()
    finally:
        conexao.close()
    if not linha:
        return None
    return decifrar(linha["token_cifrado"], loja_id, tipo, conta)


def situacao() -> list[dict]:
    """Para o script e o operador: o que está guardado (NUNCA o token)."""
    atual = id_da_chave(chave_mestra()) if tem_chave() else None
    conexao = conectar(somente_leitura=True)
    try:
        linhas = conexao.execute("SELECT loja_id, tipo_canal, conta, chave_id, atualizado_em FROM cofre_credenciais "
                                 "ORDER BY loja_id, tipo_canal, conta").fetchall()
    finally:
        conexao.close()
    return [{"loja_id": l["loja_id"], "canal": l["tipo_canal"], "conta": l["conta"],
             "atualizado_em": l["atualizado_em"], "abre_com_a_chave_do_env": l["chave_id"] == atual}
            for l in linhas]


def trocar_chave_mestra(chave_atual_texto: str, chave_nova_texto: str) -> int:
    """Recifra TODOS os tokens com a chave nova, numa transação só (tudo ou nada). Devolve quantos.
    Depois disso, troque a LEO_CHAVE_MESTRA do .env pela nova (e reinicie o Léo)."""
    atual = _ler_chave(chave_atual_texto, "chave atual")
    nova = _ler_chave(chave_nova_texto, "chave nova")
    if atual == nova:
        raise ErroCofre("A chave nova é igual à atual.")
    conexao = conectar()
    try:
        linhas = conexao.execute("SELECT id, loja_id, tipo_canal, conta, token_cifrado FROM cofre_credenciais "
                                 "ORDER BY id FOR UPDATE").fetchall()
        for l in linhas:
            token = decifrar(l["token_cifrado"], l["loja_id"], l["tipo_canal"], l["conta"], atual)
            conexao.execute("UPDATE cofre_credenciais SET token_cifrado = ?, chave_id = ?, atualizado_em = agora_texto() "
                            "WHERE id = ?", (cifrar(token, l["loja_id"], l["tipo_canal"], l["conta"], nova),
                                             id_da_chave(nova), l["id"]))
        conexao.commit()
    finally:
        conexao.close()
    return len(linhas)

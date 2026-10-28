"""
Credenciais de ENVIO de cada loja (revisão da Etapa 1).

Antes, todo envio de WhatsApp saía pelo número e token do .env. Com duas
lojas, a resposta da loja 2 sairia pelo número da loja 1. Agora o envio
pergunta "qual é o canal desta loja?" e usa o número e o token dele.

O token fica no .env, nunca no banco: o canal guarda em token_ref só o
NOME da variável (ex.: WHATSAPP_TOKEN_LOJA2).

WhatsApp:
  1. A loja tem canal ATIVO:
       com token_ref -> token = valor dessa variável do .env;
       sem token_ref -> só vale o WHATSAPP_TOKEN do .env se o número do
                        canal for o WHATSAPP_PHONE_NUMBER_ID do .env.
  2. Nenhum WhatsApp cadastrado no sistema (transição) e loja 1 -> .env.
  3. Qualquer outro caso -> SemCredencial (nada sai pelo número errado).
Telegram: mesma ideia, conferindo que o token é mesmo do bot da loja.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from app import config
from app.canais import canal_ativo_da_loja, existe_canal_do_tipo, id_bot_telegram
from app.chaves import LOJA_PADRAO, exigir_loja


class SemCredencial(LookupError):
    """A loja não tem como enviar por este canal. O texto explica o motivo."""


@dataclass(frozen=True)
class CredencialWhatsApp:
    phone_number_id: str
    token: str

    def __repr__(self) -> str:          # o token nunca aparece em log
        return f"CredencialWhatsApp(phone_number_id={self.phone_number_id!r}, token=***)"


def _do_env(nome: str) -> str:
    return (os.getenv(nome) or "").strip()


def credencial_whatsapp(loja_id) -> CredencialWhatsApp:
    loja_id = exigir_loja(loja_id)
    canal = canal_ativo_da_loja(loja_id, "whatsapp")
    if canal:
        numero = canal["id_externo"]
        ref = (canal["token_ref"] or "").strip()
        if ref:
            token = _do_env(ref)
            if not token:
                raise SemCredencial(f"a variável {ref} está vazia ou não existe no .env")
            return CredencialWhatsApp(numero, token)
        if numero == (config.WHATSAPP_PHONE_NUMBER_ID or "").strip() and config.WHATSAPP_TOKEN:
            return CredencialWhatsApp(numero, config.WHATSAPP_TOKEN.strip())
        raise SemCredencial(f"o canal {numero} não tem token_ref "
                            "(informe o nome da variável do .env em Lojas e canais)")
    if loja_id == LOJA_PADRAO and not existe_canal_do_tipo("whatsapp"):
        numero = (config.WHATSAPP_PHONE_NUMBER_ID or "").strip()
        token = (config.WHATSAPP_TOKEN or "").strip()
        if numero and token:
            return CredencialWhatsApp(numero, token)
        raise SemCredencial("WHATSAPP_TOKEN ou WHATSAPP_PHONE_NUMBER_ID vazios no .env (modo local)")
    raise SemCredencial(f"a loja {loja_id} não tem WhatsApp ativo")


def token_telegram(loja_id) -> str:
    """Token do bot de Telegram da loja (usado no envio pelo painel)."""
    loja_id = exigir_loja(loja_id)
    principal = (config.TELEGRAM_TOKEN or "").strip()
    canal = canal_ativo_da_loja(loja_id, "telegram")
    if canal:
        id_bot = canal["id_externo"]
        ref = (canal["token_ref"] or "").strip()
        if ref:
            token = _do_env(ref)
            if not token:
                raise SemCredencial(f"a variável {ref} está vazia ou não existe no .env")
            if id_bot_telegram(token) != id_bot:
                raise SemCredencial(f"o token de {ref} é de outro bot, não do {id_bot}")
            return token
        if principal and id_bot_telegram(principal) == id_bot:
            return principal
        raise SemCredencial(f"o bot {id_bot} desta loja não tem token neste computador "
                            "(informe o token_ref em Lojas e canais)")
    if loja_id == LOJA_PADRAO and not existe_canal_do_tipo("telegram") and principal:
        return principal
    raise SemCredencial(f"a loja {loja_id} não tem bot de Telegram ativo")

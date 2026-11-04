"""
Credenciais de ENVIO de cada loja (revisão da Etapa 1; P1 do Plano Mestre).

O envio pergunta "qual é o canal desta loja?" e usa o número e o token dele.
O token fica no .env, nunca no banco: o canal guarda em token_ref só o
NOME da variável (ex.: WHATSAPP_TOKEN_LOJA2).

WhatsApp:
  1. A loja tem canal ATIVO:
       com token_ref -> token = valor dessa variável do .env;
       sem token_ref -> só vale o WHATSAPP_TOKEN do .env se o número do
                        canal for o WHATSAPP_PHONE_NUMBER_ID do .env.
  2. Qualquer outro caso -> SemCredencial (nada sai pelo número errado).
Telegram: mesma ideia, conferindo que o token é mesmo do bot da loja.

Desde o P1 não existe atalho "loja 1 sem canal usa o .env": toda loja,
inclusive a 1, precisa do canal cadastrado.

S4b: situacao_da_chave(canal) diz se a chave de UM canal foi encontrada,
com as MESMAS regras do envio (as funções internas são as mesmas). Nunca
devolve o token. Usada pelo "Testar conexão" da tela Canais.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from app import config
from app.canais import canal_ativo_da_loja, id_bot_telegram
from app.chaves import exigir_loja

ENCONTRADA = "encontrada"
NAO_ENCONTRADA = "nao_encontrada"
OUTRO_ROBO = "outro_robo"
SEM_CONFERENCIA = "sem_conferencia"


class SemCredencial(LookupError):
    """A loja não tem como enviar por este canal. O texto explica o motivo."""


class ChaveDeOutroRobo(SemCredencial):
    """A chave existe, mas é de outro robô do Telegram."""


@dataclass(frozen=True)
class CredencialWhatsApp:
    phone_number_id: str
    token: str

    def __repr__(self) -> str:          # o token nunca aparece em log
        return f"CredencialWhatsApp(phone_number_id={self.phone_number_id!r}, token=***)"


def _do_env(nome: str) -> str:
    return (os.getenv(nome) or "").strip()


def _token_whatsapp_do_canal(canal: dict) -> str:
    numero = canal["id_externo"]
    ref = (canal.get("token_ref") or "").strip()
    if ref:
        token = _do_env(ref)
        if not token:
            raise SemCredencial(f"a variável {ref} está vazia ou não existe no .env")
        return token
    if numero == (config.WHATSAPP_PHONE_NUMBER_ID or "").strip() and config.WHATSAPP_TOKEN:
        return config.WHATSAPP_TOKEN.strip()
    raise SemCredencial(f"o canal {numero} não tem token_ref "
                        "(informe o nome da variável do .env em Lojas e canais)")


def _token_telegram_do_canal(canal: dict) -> str:
    id_bot = canal["id_externo"]
    ref = (canal.get("token_ref") or "").strip()
    if ref:
        token = _do_env(ref)
        if not token:
            raise SemCredencial(f"a variável {ref} está vazia ou não existe no .env")
        if id_bot_telegram(token) != id_bot:
            raise ChaveDeOutroRobo(f"o token de {ref} é de outro bot, não do {id_bot}")
        return token
    principal = (config.TELEGRAM_TOKEN or "").strip()
    if principal and id_bot_telegram(principal) == id_bot:
        return principal
    raise SemCredencial(f"o bot {id_bot} desta loja não tem token neste computador "
                        "(informe o token_ref em Lojas e canais)")


def credencial_whatsapp(loja_id) -> CredencialWhatsApp:
    loja_id = exigir_loja(loja_id)
    canal = canal_ativo_da_loja(loja_id, "whatsapp")
    if not canal:
        raise SemCredencial(f"a loja {loja_id} não tem WhatsApp ativo")
    return CredencialWhatsApp(canal["id_externo"], _token_whatsapp_do_canal(canal))


def token_telegram(loja_id) -> str:
    """Token do bot de Telegram da loja (usado no envio pelo painel)."""
    loja_id = exigir_loja(loja_id)
    canal = canal_ativo_da_loja(loja_id, "telegram")
    if not canal:
        raise SemCredencial(f"a loja {loja_id} não tem bot de Telegram ativo")
    return _token_telegram_do_canal(canal)


def situacao_da_chave(canal: dict) -> str:
    """ENCONTRADA, NAO_ENCONTRADA, OUTRO_ROBO ou SEM_CONFERENCIA. Nunca o token."""
    tipo = canal.get("tipo")
    try:
        if tipo == "whatsapp":
            _token_whatsapp_do_canal(canal)
        elif tipo == "telegram":
            _token_telegram_do_canal(canal)
        else:
            return SEM_CONFERENCIA
    except ChaveDeOutroRobo:
        return OUTRO_ROBO
    except SemCredencial:
        return NAO_ENCONTRADA
    return ENCONTRADA

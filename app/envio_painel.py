"""O vendedor responde pelo painel, pelo MESMO número/bot da loja (Bloco 7A).

Por que pelo painel: um número ligado à API da Meta não funciona ao mesmo
tempo no aplicativo comum do WhatsApp. Saindo daqui, o cliente continua na
mesma conversa e não percebe troca nenhuma.

Regras:
  - só responde quem ASSUMIU a conversa (assim o assistente fica em silêncio);
  - a mensagem é gravada como direcao='vendedor' (autor = nome), e o
    assistente recebe esse trecho quando a conversa voltar para ele;
  - por enquanto o envio usa o número/bot do .env. Se ele não for o canal
    desta loja, o envio é recusado (nada sai pelo número errado).
"""
import asyncio

from app.canais import id_bot_telegram, resolver_loja
from app.config import TELEGRAM_TOKEN, WHATSAPP_PHONE_NUMBER_ID
from app.handoff import estado_do_handoff, quem_assumiu
from app.mensagens import salvar_mensagem

CANAIS_COM_ENVIO = ("whatsapp", "telegram")
LIMITE_CARACTERES = 4000


class EnvioRecusado(Exception):
    """O motivo vem pronto para mostrar na tela."""


def _canal_e_da_loja(tipo: str, id_externo: str, loja_id: int) -> bool:
    return bool(id_externo) and resolver_loja(tipo, id_externo) == loja_id


async def _despachar(loja_id: int, canal: str, lead_id: str, texto: str) -> bool:
    if canal == "whatsapp":
        if not _canal_e_da_loja("whatsapp", WHATSAPP_PHONE_NUMBER_ID, loja_id):
            raise EnvioRecusado("O número de WhatsApp configurado neste computador não é o desta loja.")
        from app.api.enviar_whatsapp import enviar_texto_whatsapp
        return await enviar_texto_whatsapp(lead_id, texto)
    if canal == "telegram":
        if not _canal_e_da_loja("telegram", id_bot_telegram(TELEGRAM_TOKEN), loja_id):
            raise EnvioRecusado("O bot do Telegram deste computador (TELEGRAM_TOKEN do .env) "
                                "não é o bot desta loja.")
        from telegram import Bot
        async with Bot(TELEGRAM_TOKEN) as bot:
            await bot.send_message(chat_id=lead_id, text=texto)
        return True
    raise EnvioRecusado("Este canal não recebe mensagens do painel.")


def enviar_pelo_painel(loja_id: int, canal: str, lead_id: str, texto: str, vendedor: str) -> None:
    texto = (texto or "").strip()
    if not texto:
        raise EnvioRecusado("Mensagem vazia.")
    if len(texto) > LIMITE_CARACTERES:
        raise EnvioRecusado(f"Mensagem longa demais (máximo {LIMITE_CARACTERES} caracteres).")
    if canal not in CANAIS_COM_ENVIO:
        raise EnvioRecusado("O simulador não recebe mensagens do painel. Teste pelo Telegram.")
    if estado_do_handoff(lead_id, loja_id) != "humano_assumiu":
        raise EnvioRecusado("Assuma a conversa antes de responder. Assim o assistente fica "
                            "em silêncio e vocês não falam ao mesmo tempo.")
    dono = quem_assumiu(lead_id, loja_id)
    if dono and dono != vendedor:
        raise EnvioRecusado(f"Esta conversa está com {dono}.")
    try:
        ok = asyncio.run(_despachar(loja_id, canal, lead_id, texto))
    except EnvioRecusado:
        raise
    except Exception as erro:
        raise EnvioRecusado(f"Não consegui enviar: {erro}") from erro
    if not ok:
        raise EnvioRecusado("O canal não aceitou o envio. Veja o terminal do painel.")
    salvar_mensagem(lead_id, "vendedor", texto, canal=canal, loja_id=loja_id, autor=vendedor)

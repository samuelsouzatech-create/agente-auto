"""O vendedor responde  pelo painel, pelo MESMO número/bot da loja (Bloco 7A; revisão da Etapa 1).

Por que pelo painel: um número ligado à API da Meta não funciona ao mesmo
tempo no aplicativo comum do WhatsApp. Saindo daqui, o cliente continua na
mesma conversa e não percebe troca nenhuma.

Regras:
  - só responde quem ASSUMIU a conversa (assim o assistente fica em silêncio);
  - a mensagem é gravada como direcao='vendedor' (autor = nome);
  - o envio usa as credenciais DESTA loja (app/credenciais.py). Sem
    credencial, o envio é recusado: nada sai pelo número de outra loja.
"""
import asyncio

from app.credenciais import SemCredencial, credencial_whatsapp, token_telegram
from app.handoff import estado_do_handoff, quem_assumiu
from app.mensagens import salvar_mensagem

CANAIS_COM_ENVIO = ("whatsapp", "telegram")
LIMITE_CARACTERES = 4000


class EnvioRecusado(Exception):
    """O motivo vem pronto para mostrar na tela."""


async def _despachar(loja_id: int, canal: str, lead_id: str, texto: str) -> bool:
    if canal == "whatsapp":
        try:
            credencial_whatsapp(loja_id)
        except SemCredencial as erro:
            raise EnvioRecusado(f"O WhatsApp desta loja não está configurado neste computador: {erro}.")
        from app.api.enviar_whatsapp import enviar_texto_whatsapp
        return await enviar_texto_whatsapp(lead_id, texto, loja_id=loja_id)
    if canal == "telegram":
        try:
            token = token_telegram(loja_id)
        except SemCredencial as erro:
            raise EnvioRecusado(f"O bot de Telegram desta loja não está configurado neste computador: {erro}.")
        from telegram import Bot
        async with Bot(token) as bot:
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

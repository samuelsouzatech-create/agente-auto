"""
Envia mensagens de texto de volta para o cliente via WhatsApp Cloud API (Meta).

Usado pelo webhook no Movimento 5: depois que o Léo gera a resposta,
esta função entrega essa resposta no WhatsApp do cliente.
"""
import httpx
import asyncio

from app.humanizador import dividir_em_bolhas
from app.config import (
    WHATSAPP_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_API_VERSION,
)


async def enviar_texto_whatsapp(numero_cliente: str, texto: str) -> bool:
    """Manda uma mensagem de texto para o cliente pelo WhatsApp.

    Retorna True se a Meta aceitou o envio, False se deu erro.
    Nunca levanta exceção: o webhook precisa continuar vivo mesmo
    se o envio falhar (rede, token expirado, etc.).
    """
    # Se faltar token ou phone number ID, não tenta enviar (modo "ainda sem Meta").
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        print("[WhatsApp] AVISO: WHATSAPP_TOKEN ou PHONE_NUMBER_ID vazios. "
              "Envio pulado (ainda em modo local).")
        return False

    url = (
        f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"
        f"/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    cabecalhos = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    corpo = {
        "messaging_product": "whatsapp",
        "to": numero_cliente,
        "type": "text",
        "text": {"body": texto},
    }

    try:
        async with httpx.AsyncClient(timeout=30) as cliente:
            resposta = await cliente.post(url, headers=cabecalhos, json=corpo)

        if resposta.status_code == 200:
            print(f"[WhatsApp] Mensagem enviada para {numero_cliente}.")
            return True
        else:
            # Mostra o erro da Meta pra facilitar o diagnóstico (token, janela 24h, etc.)
            print(f"[WhatsApp] ERRO ao enviar ({resposta.status_code}): "
                  f"{resposta.text}")
            return False
    except Exception as erro:
        print(f"[WhatsApp] ERRO de conexão ao enviar: {erro}")
        return False

# Pausa entre bolhas, em segundos (PDF: 2 a 6 s). Começamos conservador.
PAUSA_ENTRE_BOLHAS = 2


async def enviar_resposta_humanizada(numero_cliente: str, texto: str,
                                     atraso: float = 0) -> None:
    """Divide a resposta em bolhas e envia uma a uma, com pausa entre elas.

    Antes da primeira bolha, aplica o atraso adaptativo (rápido se o cliente
    está ativo, mais lento se sumiu e voltou). Imita um atendente humano.
    O indicador de 'digitando' real (chamada à Meta) será plugado aqui
    quando a conta Meta estiver ativa.
    """
    bolhas = dividir_em_bolhas(texto)

    if not bolhas:
        return

    # Atraso adaptativo antes de começar a responder.
    # (Futuro: manter o 'digitando' da Meta aceso durante esta espera.)
    if atraso > 0:
        await asyncio.sleep(atraso)

    for i, bolha in enumerate(bolhas):
        # (Futuro: acionar o indicador 'digitando' na Meta antes de cada bolha.)
        await enviar_texto_whatsapp(numero_cliente, bolha)
        # Pausa entre as bolhas, menos depois da última.
        if i < len(bolhas) - 1:
            await asyncio.sleep(PAUSA_ENTRE_BOLHAS)


async def enviar_foto_whatsapp(numero_cliente: str, url_foto: str) -> bool:
    """Envia UMA imagem para o cliente pelo WhatsApp, a partir de uma URL pública.
    A Meta baixa a imagem da URL e entrega como foto (o cliente não vê o link).
    Retorna True se a Meta aceitou, False se deu erro. Nunca levanta exceção.
    """
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        print("[WhatsApp] AVISO: token/phone id vazios. Envio de foto pulado "
              "(ainda em modo local).")
        return False

    url = (
        f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"
        f"/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    cabecalhos = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    corpo = {
        "messaging_product": "whatsapp",
        "to": numero_cliente,
        "type": "image",
        "image": {"link": url_foto},
    }

    try:
        async with httpx.AsyncClient(timeout=30) as cliente:
            resposta = await cliente.post(url, headers=cabecalhos, json=corpo)

        if resposta.status_code == 200:
            print(f"[WhatsApp] Foto enviada para {numero_cliente}.")
            return True
        else:
            print(f"[WhatsApp] ERRO ao enviar foto ({resposta.status_code}): "
                  f"{resposta.text}")
            return False
    except Exception as erro:
        print(f"[WhatsApp] ERRO de conexão ao enviar foto: {erro}")
        return False

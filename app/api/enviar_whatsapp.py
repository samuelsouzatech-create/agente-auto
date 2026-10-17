"""
Envia mensagens de texto de volta para o cliente via WhatsApp Cloud API (Meta).

Usado pelo webhook no Movimento 5: depois que o Léo gera a resposta,
esta função entrega essa resposta no WhatsApp do cliente.
"""
import httpx

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

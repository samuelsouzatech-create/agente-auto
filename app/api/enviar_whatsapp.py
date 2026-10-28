"""
Envia mensagens para o cliente pela WhatsApp Cloud API (Meta).

Revisão da Etapa 1: todo envio diz de qual LOJA é (loja_id obrigatório) e
sai pelo número e token DESSA loja (app/credenciais.py). Sem credencial, o
envio é pulado com aviso no terminal: nada sai pelo número errado.
Falha de rede ou da Meta nunca derruba o atendimento (devolve False).
"""
import asyncio

import httpx

from app.config import WHATSAPP_API_VERSION
from app.credenciais import SemCredencial, credencial_whatsapp
from app.humanizador import dividir_em_bolhas

# Pausa entre bolhas, em segundos (PDF: 2 a 6 s).
PAUSA_ENTRE_BOLHAS = 2


async def _postar(loja_id, corpo: dict, descricao: str, para: str) -> bool:
    try:
        cred = credencial_whatsapp(loja_id)        # sem loja: erro (bug no chamador)
    except SemCredencial as erro:
        print(f"[WhatsApp][loja {loja_id}] {descricao} não enviado: {erro}.")
        return False
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{cred.phone_number_id}/messages"
    cabecalhos = {"Authorization": f"Bearer {cred.token}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=30) as cliente:
            resposta = await cliente.post(url, headers=cabecalhos, json=corpo)
    except Exception as erro:
        print(f"[WhatsApp][loja {loja_id}] ERRO de conexão ({descricao}): {type(erro).__name__}")
        return False
    if resposta.status_code == 200:
        print(f"[WhatsApp][loja {loja_id}] {descricao} enviado para {para}.")
        return True
    print(f"[WhatsApp][loja {loja_id}] ERRO ({descricao}, {resposta.status_code}): {resposta.text}")
    return False


async def enviar_texto_whatsapp(numero_cliente: str, texto: str, *, loja_id: int) -> bool:
    corpo = {"messaging_product": "whatsapp", "to": numero_cliente,
             "type": "text", "text": {"body": texto}}
    return await _postar(loja_id, corpo, "Mensagem", numero_cliente)


async def enviar_foto_whatsapp(numero_cliente: str, url_foto: str, *, loja_id: int) -> bool:
    """Envia UMA imagem a partir de uma URL pública (o cliente não vê o link)."""
    corpo = {"messaging_product": "whatsapp", "to": numero_cliente,
             "type": "image", "image": {"link": url_foto}}
    return await _postar(loja_id, corpo, "Foto", numero_cliente)


async def marcar_lida_whatsapp(id_mensagem: str, *, loja_id: int, digitando: bool = False) -> bool:
    """Dois 'checks azuis' + (opcional) 'digitando...', numa chamada só."""
    if not id_mensagem:
        return False
    corpo = {"messaging_product": "whatsapp", "status": "read", "message_id": id_mensagem}
    if digitando:
        corpo["typing_indicator"] = {"type": "text"}
    return await _postar(loja_id, corpo, "Marcação de lida", id_mensagem)


async def enviar_resposta_humanizada(numero_cliente: str, texto: str,
                                     atraso: float = 0, *, loja_id: int) -> None:
    """Divide a resposta em bolhas e envia uma a uma, com pausa entre elas."""
    bolhas = dividir_em_bolhas(texto)
    if not bolhas:
        return
    if atraso > 0:
        await asyncio.sleep(atraso)
    for i, bolha in enumerate(bolhas):
        await enviar_texto_whatsapp(numero_cliente, bolha, loja_id=loja_id)
        if i < len(bolhas) - 1:
            await asyncio.sleep(PAUSA_ENTRE_BOLHAS)

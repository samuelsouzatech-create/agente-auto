"""
Envia mensagens para o cliente pela WhatsApp Cloud API (Meta).

Revisão da Etapa 1: todo envio diz de qual LOJA é (loja_id obrigatório) e
sai pelo número e token DESSA loja (app/credenciais.py). Sem credencial, o
envio é pulado com aviso no terminal: nada sai pelo número errado.
Falha de rede ou da Meta nunca derruba o atendimento.

Etapa 2, Bloco 1: envio de MODELO (template, parâmetros nomeados) e resultado
detalhado (ResultadoEnvio), para o job saber por que a Meta recusou.
"""
import asyncio

import httpx

from app.config import WHATSAPP_API_VERSION
from app.credenciais import SemCredencial, credencial_whatsapp
from app.humanizador import dividir_em_bolhas
from app.resultado_envio import ResultadoEnvio
from app.templates import ValoresFaltando, parametros_meta

# Pausa entre bolhas, em segundos (PDF: 2 a 6 s).
PAUSA_ENTRE_BOLHAS = 2


def _id_da_mensagem(resposta) -> str:
    try:
        return str(resposta.json()["messages"][0]["id"])
    except Exception:
        return ""


def _codigo_de_erro(resposta):
    try:
        return int(resposta.json()["error"]["code"])
    except Exception:
        return None


async def _postar_detalhado(loja_id, corpo: dict, descricao: str, para: str) -> ResultadoEnvio:
    try:
        cred = credencial_whatsapp(loja_id)        # sem loja: erro (bug no chamador)
    except SemCredencial as erro:
        print(f"[WhatsApp][loja {loja_id}] {descricao} não enviado: {erro}.")
        return ResultadoEnvio(ok=False, detalhe=f"sem credencial: {erro}")
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{cred.phone_number_id}/messages"
    cabecalhos = {"Authorization": f"Bearer {cred.token}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=30) as cliente:
            resposta = await cliente.post(url, headers=cabecalhos, json=corpo)
    except Exception as erro:
        print(f"[WhatsApp][loja {loja_id}] ERRO de conexão ({descricao}): {type(erro).__name__}")
        return ResultadoEnvio(ok=False, detalhe=f"conexão: {type(erro).__name__}")
    if resposta.status_code == 200:
        print(f"[WhatsApp][loja {loja_id}] {descricao} enviado para {para}.")
        return ResultadoEnvio(ok=True, id_externo=_id_da_mensagem(resposta))
    print(f"[WhatsApp][loja {loja_id}] ERRO ({descricao}, {resposta.status_code}): {resposta.text}")
    return ResultadoEnvio(ok=False, codigo_erro=_codigo_de_erro(resposta),
                          detalhe=str(resposta.text)[:500])


async def _postar(loja_id, corpo: dict, descricao: str, para: str) -> bool:
    return (await _postar_detalhado(loja_id, corpo, descricao, para)).ok


def _corpo_texto(numero_cliente: str, texto: str) -> dict:
    return {"messaging_product": "whatsapp", "to": numero_cliente,
            "type": "text", "text": {"body": texto}}


async def enviar_texto_whatsapp(numero_cliente: str, texto: str, *, loja_id: int) -> bool:
    return await _postar(loja_id, _corpo_texto(numero_cliente, texto), "Mensagem", numero_cliente)


async def enviar_texto_whatsapp_detalhado(numero_cliente: str, texto: str, *,
                                          loja_id: int) -> ResultadoEnvio:
    """Igual ao enviar_texto_whatsapp, mas diz o motivo da recusa (ex.: janela vencida)."""
    return await _postar_detalhado(loja_id, _corpo_texto(numero_cliente, texto),
                                   "Mensagem", numero_cliente)


async def enviar_foto_whatsapp(numero_cliente: str, url_foto: str, *, loja_id: int) -> bool:
    """Envia UMA imagem a partir de uma URL pública (o cliente não vê o link)."""
    corpo = {"messaging_product": "whatsapp", "to": numero_cliente,
             "type": "image", "image": {"link": url_foto}}
    return await _postar(loja_id, corpo, "Foto", numero_cliente)


async def enviar_template_whatsapp(numero_cliente: str, modelo, valores: dict, *,
                                   loja_id: int) -> ResultadoEnvio:
    """Envia um MODELO aprovado (parâmetros nomeados). Faltou variável: nem chama a Meta."""
    try:
        parametros = parametros_meta(modelo, valores)
    except ValoresFaltando as erro:
        print(f"[WhatsApp][loja {loja_id}] Modelo {modelo.nome} não enviado: {erro}")
        return ResultadoEnvio(ok=False, detalhe=str(erro))
    template = {"name": modelo.nome, "language": {"code": modelo.idioma}}
    if parametros:
        template["components"] = [{"type": "body", "parameters": parametros}]
    corpo = {"messaging_product": "whatsapp", "recipient_type": "individual",
             "to": numero_cliente, "type": "template", "template": template}
    return await _postar_detalhado(loja_id, corpo, f"Modelo {modelo.nome}", numero_cliente)


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

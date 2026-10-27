"""
Servidor web (FastAPI) do webhook do WhatsApp - só a "porta".

POST /webhook: valida assinatura -> lê TODAS as mensagens do pacote ->
descobre a loja -> deduplica -> agenda o processamento e responde 200.
O atendimento em si é o executar_turno() (app/core/turno.py).
"""
import hashlib
import hmac
import json

from fastapi import FastAPI, Request, Response, Query, BackgroundTasks

from app.config import WHATSAPP_VERIFY_TOKEN, WHATSAPP_APP_SECRET
from app.core.agent import agente_grafo
from app.core.turno import (
    executar_turno, aguardar_vez, turno_midia_nao_suportada, turno_audio_falhou,
)
from app.api.enviar_whatsapp import enviar_resposta_humanizada, enviar_foto_whatsapp
from app.api.receber_audio import transcrever_audio, pegar_uso_da_transcricao
from app.custos import registrar_uso
from app.channels.whatsapp import CanalWhatsApp
from app.redis_lock import liberar_lock
from app.redis_atraso import calcular_atraso
from app.dedup import ja_processada
from app.canais import resolver_loja
from app.chaves import LOJA_PADRAO

CANAL = "whatsapp"
app = FastAPI(title="Agente Léo - Webhook WhatsApp")
canal_whatsapp = CanalWhatsApp()

# Última mensagem recebida de cada cliente (para marcar como lida antes de responder).
_ultima_recebida: dict[tuple[int, str], str] = {}
_LIMITE_ULTIMAS = 5000


def _lembrar_ultima(loja_id: int, lead_id: str, id_mensagem: str) -> None:
    if len(_ultima_recebida) > _LIMITE_ULTIMAS:
        _ultima_recebida.clear()
    _ultima_recebida[(loja_id, lead_id)] = id_mensagem


async def sinalizar_leitura(loja_id: int, lead_id: str) -> None:
    """Checks azuis + 'digitando...' na última mensagem do cliente."""
    id_mensagem = _ultima_recebida.pop((loja_id, lead_id), None)
    if id_mensagem:
        await canal_whatsapp.marcar_lida(id_mensagem, digitando=True)


@app.get("/")
def raiz():
    return {"status": "ok", "mensagem": "Servidor do Léo está no ar 🚗"}


@app.get("/webhook")
def verificar_webhook(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == WHATSAPP_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(content="Token de verificação inválido", status_code=403)


def assinatura_valida(corpo: bytes, cabecalho: str, segredo: str) -> bool:
    """HMAC-SHA256 do corpo cru com o App Secret. Falha FECHADA sem segredo."""
    if not segredo:
        return False
    if not cabecalho or not cabecalho.startswith("sha256="):
        return False
    enviado = cabecalho.split("=", 1)[1]
    esperado = hmac.new(segredo.encode("utf-8"), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(enviado, esperado)


# --- Compatibilidade com código antigo (lê só a 1ª mensagem) ---
def extrair_mensagem(dados: dict):
    entradas = canal_whatsapp.ler_webhook(dados)
    if not entradas:
        return None, None, None, None
    e = entradas[0]
    return e.id_externo, e.lead_id, (e.texto or None), (e.id_midia or None)


def extrair_id_canal(dados: dict):
    entradas = canal_whatsapp.ler_webhook(dados)
    return entradas[0].id_canal if entradas else None


async def processar_mensagem(numero: str, texto: str, id_audio: str = None,
                             loja_id: int = LOJA_PADRAO):
    """Segundo plano: (áudio) -> debounce + lock -> executar_turno -> envio."""
    if id_audio:
        print(f"[WhatsApp][loja {loja_id}] Cliente {numero} mandou um áudio. Transcrevendo...")
        texto = await transcrever_audio(id_audio)
        uso_audio = pegar_uso_da_transcricao(id_audio)
        if uso_audio is not None and not uso_audio.vazio:
            registrar_uso(loja_id, numero, CANAL, uso_audio,
                          tipo="transcricao", ferramentas=["transcricao_audio"])
        if not texto:
            aviso = turno_audio_falhou(loja_id, CANAL, numero)
            if aviso.texto:
                await enviar_resposta_humanizada(numero, aviso.texto)
            return
        print(f"[WhatsApp][loja {loja_id}] Áudio transcrito: {texto}")

    texto_juntado, token = await aguardar_vez(loja_id, numero, texto)
    if texto_juntado is None:
        return

    try:
        atraso = await calcular_atraso(numero, loja_id=loja_id)
        resultado = await executar_turno(loja_id, CANAL, numero, texto_juntado, grafo=agente_grafo)
        if resultado.silenciado or not resultado.texto:
            return
        await sinalizar_leitura(loja_id, numero)
        await enviar_resposta_humanizada(numero, resultado.texto, atraso)
        for url in resultado.midias:
            await enviar_foto_whatsapp(numero, url)
    finally:
        await liberar_lock(numero, token, loja_id=loja_id)


async def responder_midia_nao_suportada(numero: str, tipo_original: str,
                                        loja_id: int = LOJA_PADRAO):
    resultado = turno_midia_nao_suportada(loja_id, CANAL, numero, tipo_original)
    if resultado.texto:
        await sinalizar_leitura(loja_id, numero)
        await enviar_resposta_humanizada(numero, resultado.texto)


@app.post("/webhook")
async def receber_mensagem(request: Request, tarefas: BackgroundTasks):
    corpo = await request.body()

    if not assinatura_valida(corpo, request.headers.get("X-Hub-Signature-256"), WHATSAPP_APP_SECRET):
        print("[WhatsApp] Assinatura inválida no POST. Rejeitado (403).")
        return Response(status_code=403)

    try:
        dados = json.loads(corpo)
    except Exception:
        return Response(status_code=200)

    for entrada in canal_whatsapp.ler_webhook(dados):
        loja_id = resolver_loja(CANAL, entrada.id_canal)
        if loja_id is None:
            print(f"[WhatsApp] phone_number_id {entrada.id_canal} não cadastrado em canais. Ignorando.")
            continue
        if await ja_processada(CANAL, entrada.id_externo):
            print(f"[WhatsApp] Mensagem {entrada.id_externo} já processada. Ignorando duplicata.")
            continue

        _lembrar_ultima(loja_id, entrada.lead_id, entrada.id_externo)
        if entrada.tipo == "texto":
            tarefas.add_task(processar_mensagem, entrada.lead_id, entrada.texto, None, loja_id)
        elif entrada.tipo == "audio":
            tarefas.add_task(processar_mensagem, entrada.lead_id, None, entrada.id_midia, loja_id)
        else:
            tarefas.add_task(responder_midia_nao_suportada, entrada.lead_id,
                             entrada.tipo_original, loja_id)

    return Response(status_code=200)

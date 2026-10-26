"""
Servidor web (FastAPI) do webhook do WhatsApp.

Rotas:
- GET  "/"         -> saúde
- GET  "/webhook"  -> verificação (aperto de mão da Meta)
- POST "/webhook"  -> valida assinatura, descobre a LOJA pelo phone_number_id,
                      deduplica, responde 200 e processa em segundo plano.
"""
import asyncio
import hashlib
import hmac
import json

from fastapi import FastAPI, Request, Response, Query, BackgroundTasks
from langchain_core.messages import HumanMessage

from app.config import WHATSAPP_VERIFY_TOKEN, WHATSAPP_APP_SECRET
from app.core.agent import agente_grafo
from app.utils import extrair_texto, mensagens_do_turno
from app.formatacao import limpar_markdown
from app.api.enviar_whatsapp import enviar_resposta_humanizada, enviar_foto_whatsapp
from app.redis_debounce import acumular_e_esperar
from app.redis_lock import adquirir_lock_esperando, liberar_lock
from app.redis_atraso import calcular_atraso
from app.api.receber_audio import transcrever_audio
from app.guarda_politica import resposta_tem_preco_inventado, MENSAGEM_SEGURA
from app.mensagens import salvar_mensagem
from app.handoff import estado_do_handoff
from app.dedup import ja_processada
from app.canais import resolver_loja
from app.chaves import thread_id, LOJA_PADRAO
from tools import acionar_handoff

CANAL = "whatsapp"
app = FastAPI(title="Agente Léo - Webhook WhatsApp")


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


def extrair_mensagem(dados: dict):
    """Devolve (id_mensagem, numero, texto, id_audio). Fora texto/áudio: Nones."""
    try:
        valor = dados["entry"][0]["changes"][0]["value"]
        mensagens = valor.get("messages")
        if not mensagens:
            return None, None, None, None
        msg = mensagens[0]
        id_mensagem = msg["id"]
        numero = msg["from"]
        tipo = msg.get("type")
        if tipo == "text":
            return id_mensagem, numero, msg["text"]["body"], None
        if tipo == "audio":
            return id_mensagem, numero, None, msg["audio"]["id"]
        return id_mensagem, numero, None, None
    except (KeyError, IndexError, TypeError):
        return None, None, None, None


def extrair_id_canal(dados: dict):
    """phone_number_id do número da LOJA que recebeu a mensagem (identifica a loja)."""
    try:
        return dados["entry"][0]["changes"][0]["value"].get("metadata", {}).get("phone_number_id")
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


def extrair_fotos(resultado) -> list:
    """URLs de fotos dos artifacts, só do turno atual."""
    urls = []
    for m in mensagens_do_turno(resultado):
        artifact = getattr(m, "artifact", None)
        if isinstance(artifact, dict) and artifact.get("tipo") == "fotos":
            urls.extend(artifact.get("urls", []))
    return urls


async def processar_mensagem(numero: str, texto: str, id_audio: str = None,
                             loja_id: int = LOJA_PADRAO):
    """Segundo plano: (áudio) -> debounce -> lock -> Léo -> guarda -> envio.
    Tudo separado por loja: chaves do Redis, memória, histórico e handoff."""
    rotulo = f"[WhatsApp][loja {loja_id}]"

    if id_audio:
        print(f"{rotulo} Cliente {numero} mandou um áudio. Transcrevendo...")
        texto = await transcrever_audio(id_audio)
        if not texto:
            print(f"{rotulo} Não foi possível transcrever o áudio de {numero}.")
            return
        print(f"{rotulo} Áudio transcrito: {texto}")

    texto_juntado = await acumular_e_esperar(numero, texto, loja_id=loja_id)
    if texto_juntado is None:
        return
    atraso = await calcular_atraso(numero, loja_id=loja_id)

    token_lock = await adquirir_lock_esperando(numero, loja_id=loja_id)
    if token_lock is None:
        print(f"{rotulo} Lead {numero}: lock ocupado tempo demais. Desistindo.")
        return

    try:
        print(f"\n{rotulo} Cliente {numero} disse: {texto_juntado}")
        salvar_mensagem(numero, "cliente", texto_juntado, canal=CANAL, loja_id=loja_id)

        if estado_do_handoff(numero, loja_id) == "humano_assumiu":
            print(f"{rotulo} Lead {numero} está com um vendedor humano. Léo em silêncio.")
            return

        resultado = await asyncio.to_thread(
            agente_grafo.invoke,
            {
                "messages": [HumanMessage(content=texto_juntado)],
                "lead_id": numero,
                "loja_id": loja_id,
                "canal": CANAL,
            },
            {"configurable": {"thread_id": thread_id(loja_id, CANAL, numero)}},
        )
        resposta = limpar_markdown(extrair_texto(resultado["messages"][-1].content))
        fotos = extrair_fotos(resultado)

        if resposta_tem_preco_inventado(resposta, resultado["messages"]):
            print(f"{rotulo} GUARDA: preço inventado detectado. Acionando handoff.")
            print(f"{rotulo} Resposta barrada: {resposta}")
            acionar_handoff.func(
                motivo="Guarda de política: valor em R$ sem origem em tool.",
                resumo=f"Resposta barrada do Léo: {resposta}",
                lead_id=numero,
                loja_id=loja_id,
            )
            resposta = MENSAGEM_SEGURA
            fotos = []

        print(f"{rotulo} Léo responde: {resposta}")
        if fotos:
            print(f"{rotulo} Enviando {len(fotos)} foto(s).")
        print()

        salvar_mensagem(numero, "leo", resposta, canal=CANAL, loja_id=loja_id)
        await enviar_resposta_humanizada(numero, resposta, atraso)
        for url in fotos:
            await enviar_foto_whatsapp(numero, url)
    finally:
        await liberar_lock(numero, token_lock, loja_id=loja_id)


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

    id_mensagem, numero, texto, id_audio = extrair_mensagem(dados)
    if not texto and not id_audio:
        return Response(status_code=200)

    # Qual loja recebeu? Pelo phone_number_id do número dela.
    id_canal = extrair_id_canal(dados)
    loja_id = resolver_loja(CANAL, id_canal)
    if loja_id is None:
        print(f"[WhatsApp] phone_number_id {id_canal} não cadastrado em canais. Ignorando.")
        return Response(status_code=200)

    if await ja_processada(CANAL, id_mensagem):
        print(f"[WhatsApp] Mensagem {id_mensagem} já processada. Ignorando duplicata.")
        return Response(status_code=200)

    tarefas.add_task(processar_mensagem, numero, texto, id_audio, loja_id)
    return Response(status_code=200)

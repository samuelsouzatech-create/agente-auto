"""
Servidor web (FastAPI) que hospeda o webhook do WhatsApp na Fase 2.

Rotas:
- GET  "/"         -> saúde ("tô vivo")
- GET  "/webhook"  -> verificação do webhook (aperto de mão da Meta)
- POST "/webhook"  -> recebe a mensagem, responde 200 rápido e processa
                      em segundo plano (debounce + lock + Léo + envio)
"""
import asyncio

from fastapi import FastAPI, Request, Response, Query, BackgroundTasks
from langchain_core.messages import HumanMessage

from app.config import WHATSAPP_VERIFY_TOKEN
from app.core.agent import agente_grafo
from app.utils import extrair_texto
from app.api.enviar_whatsapp import enviar_resposta_humanizada, enviar_foto_whatsapp
from app.redis_debounce import acumular_e_esperar
from app.redis_lock import adquirir_lock, liberar_lock
from app.redis_atraso import calcular_atraso
from app.api.receber_audio import transcrever_audio

app = FastAPI(title="Agente Léo - Webhook WhatsApp")

# --- Deduplicação (Bloco 4) ---
# A Meta reenvia a mesma mensagem às vezes. Guardamos os ids já processados
# para não responder (nem gastar Gemini) duas vezes pela mesma mensagem.
_ids_processados: set[str] = set()
_LIMITE_IDS = 1000  # evita a lista crescer para sempre na memória


def ja_processada(id_mensagem: str) -> bool:
    """Devolve True se esta mensagem já foi vista antes (duplicata).
    Se for nova, registra o id e devolve False."""
    if id_mensagem in _ids_processados:
        return True
    _ids_processados.add(id_mensagem)
    if len(_ids_processados) > _LIMITE_IDS:
        for antigo in list(_ids_processados)[: _LIMITE_IDS // 2]:
            _ids_processados.discard(antigo)
    return False


@app.get("/")
def raiz():
    """Rota de saúde: se isto responder, o servidor está no ar."""
    return {"status": "ok", "mensagem": "Servidor do Léo está no ar 🚗"}


@app.get("/webhook")
def verificar_webhook(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
):
    """Aperto de mão da Meta (ver Movimento 3)."""
    if hub_mode == "subscribe" and hub_verify_token == WHATSAPP_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(content="Token de verificação inválido", status_code=403)


def extrair_mensagem(dados: dict):
    """Cava o JSON da Meta e devolve (id_mensagem, numero, texto, id_audio).

    - Mensagem de TEXTO: texto preenchido, id_audio = None.
    - Mensagem de ÁUDIO: texto = None, id_audio preenchido (o id do arquivo
      de mídia na Meta; o áudio em si é baixado depois, com o token).
    - Qualquer outra coisa (status, etc.): tudo None.
    """
    try:
        valor = dados["entry"][0]["changes"][0]["value"]
        mensagens = valor.get("messages")
        if not mensagens:
            return None, None, None, None  # não é mensagem (ex.: status)
        msg = mensagens[0]
        id_mensagem = msg["id"]           # id único (wamid...) para deduplicar
        numero = msg["from"]              # número do cliente (vira o lead_id)
        tipo = msg.get("type")            # "text", "audio", "image"...

        if tipo == "text":
            texto = msg["text"]["body"]
            return id_mensagem, numero, texto, None

        if tipo == "audio":
            id_audio = msg["audio"]["id"]  # id do arquivo de áudio na Meta
            return id_mensagem, numero, None, id_audio

        # Outros tipos (imagem, figurinha, etc.): ainda não tratados.
        return id_mensagem, numero, None, None
    except (KeyError, IndexError, TypeError):
        return None, None, None, None

def extrair_fotos(resultado) -> list:
    """Varre as mensagens do resultado do grafo e junta todas as URLs de fotos
    que vieram em artifacts de ToolMessages (da tool enviar_fotos)."""
    urls = []
    for m in resultado["messages"]:
        artifact = getattr(m, "artifact", None)
        if isinstance(artifact, dict) and artifact.get("tipo") == "fotos":
            urls.extend(artifact.get("urls", []))
    return urls

async def processar_mensagem(numero: str, texto: str, id_audio: str = None):
    """Trabalho pesado, rodado em segundo plano (depois do 200 à Meta).

    0) Se veio áudio, transcreve primeiro (vira texto).
    1) Debounce: espera o cliente terminar a rajada de mensagens.
    2) Lock: garante uma execução por vez por lead.
    3) Chama o Léo e envia a resposta.
    """
    # 0) Áudio: transcreve antes de qualquer coisa (seção 4.3 do PDF).
    if id_audio:
        print(f"[WhatsApp] Cliente {numero} mandou um áudio. Transcrevendo...")
        texto = await transcrever_audio(id_audio)
        if not texto:
            # Sem token (modo local) ou falha na transcrição: não trava o fluxo.
            print(f"[WhatsApp] Não foi possível transcrever o áudio de {numero}. "
                  f"Nada a processar por enquanto.")
            return
        print(f"[WhatsApp] Áudio transcrito: {texto}")

    # 1) Debounce: acumula e espera o silêncio. Só a última da rajada segue.
    texto_juntado = await acumular_e_esperar(numero, texto)
    if texto_juntado is None:
        return  # outra mensagem mais nova chegou; ela cuidará da rajada
    # Calcula o atraso adaptativo (rápido se o cliente está ativo, mais lento
    # se sumiu e voltou). Feito aqui, depois do debounce, roda uma vez por rajada.
    atraso = await calcular_atraso(numero)


    # 2) Lock: se já há execução para este lead, desiste (evita duplicar).
    if not await adquirir_lock(numero):
        print(f"[WhatsApp] Lead {numero} já em processamento. Ignorando.")
        return

    try:
        print(f"\n[WhatsApp] Cliente {numero} disse: {texto_juntado}")

        # 3) Cérebro do Léo, usando o número como lead_id.
        # - thread_id dá memória por conversa (igual ao Telegram).
        # - to_thread roda o invoke (síncrono) fora do loop async, pra não
        #   travar o servidor enquanto o Gemini responde.
        resultado = await asyncio.to_thread(
            agente_grafo.invoke,
            {
                "messages": [HumanMessage(content=texto_juntado)],
                "lead_id": numero,
            },
            {"configurable": {"thread_id": numero}},
        )
        resposta = extrair_texto(resultado["messages"][-1].content)
        fotos = extrair_fotos(resultado)

        print(f"[WhatsApp] Léo responde: {resposta}")
        if fotos:
            print(f"[WhatsApp] Enviando {len(fotos)} foto(s).")
        print()

        # Envia a resposta humanizada (em bolhas, com pausa) pro WhatsApp,
        # aplicando o atraso adaptativo antes da primeira bolha.
        await enviar_resposta_humanizada(numero, resposta, atraso)

        # Depois do texto, envia as fotos (se houver) como imagens.
        for url in fotos:
            await enviar_foto_whatsapp(numero, url)
    finally:
        # Libera o lock mesmo se der erro no meio (o finally sempre roda).
        await liberar_lock(numero)


@app.post("/webhook")
async def receber_mensagem(request: Request, tarefas: BackgroundTasks):
    """Recebe o POST da Meta, deduplica e AGENDA o processamento em segundo
    plano, devolvendo 200 imediatamente (a Meta exige 200 rápido)."""
    try:
        dados = await request.json()
    except Exception:
        return Response(status_code=200)

    id_mensagem, numero, texto, id_audio = extrair_mensagem(dados)

    # Se não for texto NEM áudio (ex.: imagem, status), responde 200 e ignora.
    if not texto and not id_audio:
        return Response(status_code=200)

    # Deduplicação: se a Meta reenviou a mesma mensagem, ignora.
    if ja_processada(id_mensagem):
        print(f"[WhatsApp] Mensagem {id_mensagem} já processada. Ignorando duplicata.")
        return Response(status_code=200)

    # Agenda o trabalho pesado em segundo plano e responde 200 na hora.
    tarefas.add_task(processar_mensagem, numero, texto, id_audio)
    return Response(status_code=200)

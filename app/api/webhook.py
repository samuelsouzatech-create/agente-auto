"""
Servidor web (FastAPI) que hospeda o webhook do WhatsApp na Fase 2.

Rotas:
- GET  "/"         -> saúde ("tô vivo")
- GET  "/webhook"  -> verificação do webhook (aperto de mão da Meta)
- POST "/webhook"  -> recebe a mensagem, responde 200 rápido e processa
                      em segundo plano (debounce + lock + Léo + envio)
"""
from fastapi import FastAPI, Request, Response, Query, BackgroundTasks
from langchain_core.messages import HumanMessage

from app.config import WHATSAPP_VERIFY_TOKEN
from app.core.agent import agente_grafo
from app.utils import extrair_texto
from app.api.enviar_whatsapp import enviar_resposta_humanizada
from app.redis_debounce import acumular_e_esperar
from app.redis_lock import adquirir_lock, liberar_lock

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
    """Cava o JSON da Meta e devolve (id_mensagem, numero_cliente, texto)
    ou (None, None, None)."""
    try:
        valor = dados["entry"][0]["changes"][0]["value"]
        mensagens = valor.get("messages")
        if not mensagens:
            return None, None, None  # não é mensagem (ex.: notificação de status)
        msg = mensagens[0]
        id_mensagem = msg["id"]           # id único (wamid...) para deduplicar
        numero = msg["from"]              # número do cliente (vira o lead_id)
        texto = msg["text"]["body"]       # o que o cliente escreveu
        return id_mensagem, numero, texto
    except (KeyError, IndexError, TypeError):
        return None, None, None


async def processar_mensagem(numero: str, texto: str):
    """Trabalho pesado, rodado em segundo plano (depois do 200 à Meta).

    1) Debounce: espera o cliente terminar a rajada de mensagens.
    2) Lock: garante uma execução por vez por lead.
    3) Chama o Léo e envia a resposta.
    """
    # 1) Debounce: acumula e espera o silêncio. Só a última da rajada segue.
    texto_juntado = await acumular_e_esperar(numero, texto)
    if texto_juntado is None:
        return  # outra mensagem mais nova chegou; ela cuidará da rajada

    # 2) Lock: se já há execução para este lead, desiste (evita duplicar).
    if not await adquirir_lock(numero):
        print(f"[WhatsApp] Lead {numero} já em processamento. Ignorando.")
        return

    try:
        print(f"\n[WhatsApp] Cliente {numero} disse: {texto_juntado}")

        # 3) Cérebro do Léo, usando o número como lead_id
        resultado = agente_grafo.invoke({
            "messages": [HumanMessage(content=texto_juntado)],
            "lead_id": numero,
        })
        resposta = extrair_texto(resultado["messages"][-1].content)

        print(f"[WhatsApp] Léo responde: {resposta}\n")

        # Envia a resposta humanizada (em bolhas, com pausa) pro WhatsApp.
        await enviar_resposta_humanizada(numero, resposta)
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

    id_mensagem, numero, texto = extrair_mensagem(dados)

    # Se não for uma mensagem de texto, responde 200 e ignora.
    if not texto:
        return Response(status_code=200)

    # Deduplicação: se a Meta reenviou a mesma mensagem, ignora.
    if ja_processada(id_mensagem):
        print(f"[WhatsApp] Mensagem {id_mensagem} já processada. Ignorando duplicata.")
        return Response(status_code=200)

    # Agenda o trabalho pesado em segundo plano e responde 200 na hora.
    tarefas.add_task(processar_mensagem, numero, texto)
    return Response(status_code=200)

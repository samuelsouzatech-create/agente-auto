"""
Servidor web (FastAPI) que hospeda o webhook do WhatsApp na Fase 2.

Rotas:
- GET  "/"         -> saúde ("tô vivo")
- GET  "/webhook"  -> verificação do webhook (aperto de mão da Meta)
- POST "/webhook"  -> recebe a mensagem do cliente e chama o cérebro do Léo
"""
from fastapi import FastAPI, Request, Response, Query
from langchain_core.messages import HumanMessage

from app.config import WHATSAPP_VERIFY_TOKEN
from app.core.agent import agente_grafo
from app.utils import extrair_texto
from app.api.enviar_whatsapp import enviar_texto_whatsapp

app = FastAPI(title="Agente Léo - Webhook WhatsApp")


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
    """Cava o JSON da Meta e devolve (numero_cliente, texto) ou (None, None).

    O pacote da Meta tem várias camadas:
    entry -> changes -> value -> messages -> [0] -> text -> body
    Nem todo POST é uma mensagem de texto (pode ser status de entrega, etc.),
    por isso usamos try/except e devolvemos None quando não há texto."""
    try:
        valor = dados["entry"][0]["changes"][0]["value"]
        mensagens = valor.get("messages")
        if not mensagens:
            return None, None  # não é mensagem (ex.: notificação de status)
        msg = mensagens[0]
        numero = msg["from"]              # número do cliente (vira o lead_id)
        texto = msg["text"]["body"]       # o que o cliente escreveu
        return numero, texto
    except (KeyError, IndexError, TypeError):
        return None, None


@app.post("/webhook")
async def receber_mensagem(request: Request):
    """Recebe o POST da Meta, extrai a mensagem, chama o cérebro do Léo
    e (por enquanto) imprime a resposta no terminal. O envio de volta
    pro WhatsApp entra no Movimento 5."""
    try:
        dados = await request.json()
    except Exception:
        # Corpo vazio ou não-JSON: confirma recebimento e ignora.
        return Response(status_code=200)

    numero, texto = extrair_mensagem(dados)

    # Se não for uma mensagem de texto, responde 200 e ignora
    # (a Meta exige 200 rápido, senão fica reenviando).
    if not texto:
        return Response(status_code=200)

    print(f"\n[WhatsApp] Cliente {numero} disse: {texto}")

    # Joga no cérebro de sempre, usando o número como lead_id
    resultado = agente_grafo.invoke({
        "messages": [HumanMessage(content=texto)],
        "lead_id": numero,
    })
    resposta = extrair_texto(resultado["messages"][-1].content)

    print(f"[WhatsApp] Léo responde: {resposta}\n")

    # Movimento 5: envia a resposta de volta pro WhatsApp do cliente.
    await enviar_texto_whatsapp(numero, resposta)

    return Response(status_code=200)


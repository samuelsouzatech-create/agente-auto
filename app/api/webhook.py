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

# --- Deduplicação (Bloco 4) ---
# A Meta reenvia a mesma mensagem às vezes. Guardamos os ids já processados
# para não responder (nem gastar Gemini) duas vezes pela mesma mensagem.
# Versão em memória: simples e boa para testes/piloto. No Bloco 5 (Redis)
# essa mesma lógica passa a morar no Redis, para sobreviver a reinícios.
_ids_processados: set[str] = set()
_LIMITE_IDS = 1000  # evita a lista crescer para sempre na memória


def ja_processada(id_mensagem: str) -> bool:
    """Devolve True se esta mensagem já foi vista antes (duplicata).
    Se for nova, registra o id e devolve False."""
    if id_mensagem in _ids_processados:
        return True
    _ids_processados.add(id_mensagem)
    # Poda simples: se passou do limite, esvazia metade para não vazar memória.
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
    ou (None, None, None).

    O pacote da Meta tem várias camadas:
    entry -> changes -> value -> messages -> [0] -> text -> body
    Nem todo POST é uma mensagem de texto (pode ser status de entrega, etc.),
    por isso usamos try/except e devolvemos None quando não há texto."""
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



@app.post("/webhook")
async def receber_mensagem(request: Request):
    """Recebe o POST da Meta, extrai a mensagem, deduplica, chama o cérebro
    do Léo e envia a resposta de volta pro WhatsApp."""
    try:
        dados = await request.json()
    except Exception:
        # Corpo vazio ou não-JSON: confirma recebimento e ignora.
        return Response(status_code=200)

    id_mensagem, numero, texto = extrair_mensagem(dados)

    # Se não for uma mensagem de texto, responde 200 e ignora
    # (a Meta exige 200 rápido, senão fica reenviando).
    if not texto:
        return Response(status_code=200)

    # Deduplicação: se a Meta reenviou a mesma mensagem, ignora.
    if ja_processada(id_mensagem):
        print(f"[WhatsApp] Mensagem {id_mensagem} já processada. Ignorando duplicata.")
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


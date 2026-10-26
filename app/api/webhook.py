"""
Servidor web (FastAPI) que hospeda o webhook do WhatsApp na Fase 2.

Rotas:
- GET  "/"         -> saúde ("tô vivo")
- GET  "/webhook"  -> verificação do webhook (aperto de mão da Meta)
- POST "/webhook"  -> recebe a mensagem, responde 200 rápido e processa
                      em segundo plano (debounce + lock + Léo + envio)
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
from tools import acionar_handoff

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

def assinatura_valida(corpo: bytes, cabecalho: str, segredo: str) -> bool:
    """Confere se o POST veio mesmo da Meta, comparando a assinatura enviada
    no header 'X-Hub-Signature-256' com um HMAC-SHA256 que calculamos sobre o
    corpo CRU da requisição, usando o App Secret como chave.

    Falha FECHADA: sem App Secret configurado, rejeita tudo. Com chave vazia
    qualquer pessoa consegue calcular uma assinatura que "bate".
    """
    if not segredo:
        return False

    if not cabecalho or not cabecalho.startswith("sha256="):
        return False

    enviado = cabecalho.split("=", 1)[1]
    esperado = hmac.new(segredo.encode("utf-8"), corpo, hashlib.sha256).hexdigest()

    # compare_digest evita comparação vulnerável a timing.
    return hmac.compare_digest(enviado, esperado)

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
    """Junta as URLs de fotos dos artifacts de ToolMessages, mas SÓ do turno
    atual (não reenvia fotos pedidas em turnos anteriores, que o MemorySaver
    ainda guarda na lista de mensagens)."""
    urls = []
    for m in mensagens_do_turno(resultado):
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


    # 2) Lock: espera a vez em vez de desistir, para não perder a 2ª mensagem
    #    do mesmo cliente que chegou enquanto a 1ª ainda respondia.
    token_lock = await adquirir_lock_esperando(numero)
    if token_lock is None:
        print(f"[WhatsApp] Lead {numero}: lock ocupado tempo demais. Desistindo.")
        return

    try:
        print(f"\n[WhatsApp] Cliente {numero} disse: {texto_juntado}")

        # Grava a mensagem do cliente no histórico (para o painel ler depois).
        salvar_mensagem(numero, "cliente", texto_juntado, canal="whatsapp")

        # --- Silêncio do Léo (Fase 3): se um vendedor humano assumiu este
        # lead, o Léo NÃO responde. A mensagem do cliente já foi salva acima
        # (o vendedor a vê no painel); aqui apenas encerramos sem chamar o Léo.
        if estado_do_handoff(numero) == "humano_assumiu":
            print(f"[WhatsApp] Lead {numero} está com um vendedor humano. Léo em silêncio.")
            return

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
        resposta = limpar_markdown(extrair_texto(resultado["messages"][-1].content))
        fotos = extrair_fotos(resultado)

        # --- Guarda de política (PDF 4.5): preço só pode vir de tool. ---
        # Se o Léo citou um valor em R$ que nenhuma tool deste turno devolveu,
        # é preço inventado: barra a resposta, não manda fotos e aciona handoff.
        if resposta_tem_preco_inventado(resposta, resultado["messages"]):
            print(f"[WhatsApp] GUARDA: preço inventado detectado. Acionando handoff.")
            print(f"[WhatsApp] Resposta barrada: {resposta}")
            acionar_handoff.func(
                motivo="Guarda de política: valor em R$ sem origem em tool.",
                resumo=f"Resposta barrada do Léo: {resposta}",
                lead_id=numero,
            )
            resposta = MENSAGEM_SEGURA
            fotos = []

        print(f"[WhatsApp] Léo responde: {resposta}")
        if fotos:
            print(f"[WhatsApp] Enviando {len(fotos)} foto(s).")
        print()

        # Grava a resposta do Léo no histórico (texto final, após a guarda).
        salvar_mensagem(numero, "leo", resposta, canal="whatsapp")

        # Envia a resposta humanizada (em bolhas, com pausa) pro WhatsApp,
        # aplicando o atraso adaptativo antes da primeira bolha.
        await enviar_resposta_humanizada(numero, resposta, atraso)

        # Depois do texto, envia as fotos (se houver) como imagens.
        for url in fotos:
            await enviar_foto_whatsapp(numero, url)
    finally:
        # Libera o lock mesmo se der erro no meio (o finally sempre roda).
        # Passa o token para só apagar o lock se ele ainda for o nosso.
        await liberar_lock(numero, token_lock)

@app.post("/webhook")
async def receber_mensagem(request: Request, tarefas: BackgroundTasks):
    """Recebe o POST da Meta, valida a assinatura, deduplica e AGENDA o
    processamento em segundo plano, devolvendo 200 imediatamente (a Meta
    exige 200 rápido)."""
    # Lê o corpo CRU primeiro: a assinatura é calculada sobre estes bytes
    # exatos (request.json() reinterpretaria e não serviria para o HMAC).
    corpo = await request.body()

    # Valida que o POST veio mesmo da Meta.
    if not assinatura_valida(corpo, request.headers.get("X-Hub-Signature-256"), WHATSAPP_APP_SECRET):
        print("[WhatsApp] Assinatura inválida no POST. Rejeitado (403).")
        return Response(status_code=403)

    try:
        dados = json.loads(corpo)
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

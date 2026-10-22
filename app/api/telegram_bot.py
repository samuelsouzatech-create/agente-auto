"""
Casca do Telegram para o Agente Léo (modo de testes, via polling).

Reaproveita o MESMO cérebro do WhatsApp (agente_grafo) e os mesmos
mecanismos: debounce, lock por lead e humanizador (resposta em bolhas).
A única diferença em relação ao WhatsApp é a "porta": aqui a mensagem
entra e sai pelo Telegram, não pela Meta.
"""
import asyncio

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from langchain_core.messages import HumanMessage

from app.config import TELEGRAM_TOKEN
from app.core.agent import agente_grafo
from app.utils import extrair_texto
from app.humanizador import dividir_em_bolhas
from app.redis_debounce import acumular_e_esperar
from app.redis_lock import adquirir_lock, liberar_lock
from app.redis_atraso import calcular_atraso
from app.api.receber_audio import transcrever_bytes
from app.guarda_politica import resposta_tem_preco_inventado, MENSAGEM_SEGURA
from tools import acionar_handoff

# --- Deduplicação (igual à do WhatsApp) ---
# O Telegram normalmente não reenvia, mas mantemos o padrão por segurança.
_ids_processados: set[str] = set()
_LIMITE_IDS = 1000


def ja_processada(id_mensagem: str) -> bool:
    if id_mensagem in _ids_processados:
        return True
    _ids_processados.add(id_mensagem)
    if len(_ids_processados) > _LIMITE_IDS:
        for antigo in list(_ids_processados)[: _LIMITE_IDS // 2]:
            _ids_processados.discard(antigo)
    return False


# Pausa entre bolhas, em segundos (mesma lógica do WhatsApp).
PAUSA_ENTRE_BOLHAS = 2


async def esperar_digitando(update: Update, segundos: float) -> None:
    """Espera o tempo pedido mantendo o 'digitando...' aceso o tempo todo.
    O indicador do Telegram dura ~5s, então reacionamos a cada 4s."""
    restante = segundos
    while restante > 0:
        await update.message.chat.send_action("typing")
        passo = min(4, restante)
        await asyncio.sleep(passo)
        restante -= passo


async def enviar_resposta_humanizada_telegram(update: Update, texto: str,
                                              atraso: float = 0) -> None:
    """Divide a resposta em bolhas e envia uma a uma pelo Telegram.
    Antes da primeira bolha, aplica o atraso adaptativo com 'digitando...'
    aceso; entre as bolhas, mantém a pausa normal."""
    bolhas = dividir_em_bolhas(texto)
    if not bolhas:
        return

    # Atraso adaptativo (rápido se o cliente está ativo, mais lento se sumiu),
    # com "digitando..." aceso durante toda a espera.
    if atraso > 0:
        await esperar_digitando(update, atraso)

    for i, bolha in enumerate(bolhas):
        # Mostra "digitando..." no Telegram (recurso nativo, igual conversa real).
        await update.message.chat.send_action("typing")
        await asyncio.sleep(1)  # um respiro pra parecer que está digitando
        await update.message.reply_text(bolha)
        if i < len(bolhas) - 1:
            await asyncio.sleep(PAUSA_ENTRE_BOLHAS)

def extrair_fotos(resultado) -> list:
    """Varre as mensagens do resultado do grafo e junta todas as URLs de fotos
    que vieram em artifacts de ToolMessages (da tool enviar_fotos)."""
    urls = []
    for m in resultado["messages"]:
        artifact = getattr(m, "artifact", None)
        if isinstance(artifact, dict) and artifact.get("tipo") == "fotos":
            urls.extend(artifact.get("urls", []))
    return urls

async def processar_texto(chat_id: str, texto: str):
    """Trabalho pesado: debounce -> lock -> Léo. Devolve uma dupla
    (resposta_texto, lista_de_fotos). Devolve (None, []) se a rajada foi
    assumida por outra mensagem / lock ocupado."""
    # 1) Debounce: acumula e espera o silêncio.
    texto_juntado = await acumular_e_esperar(chat_id, texto)
    if texto_juntado is None:
        return None, []

    # 2) Lock: uma execução por vez por lead.
    if not await adquirir_lock(chat_id):
        print(f"[Telegram] Lead {chat_id} já em processamento. Ignorando.")
        return None, []

    try:
        print(f"\n[Telegram] Cliente {chat_id} disse: {texto_juntado}")
        resultado = await asyncio.to_thread(
            agente_grafo.invoke,
            {
                "messages": [HumanMessage(content=texto_juntado)],
                "lead_id": chat_id,
            },
            {"configurable": {"thread_id": chat_id}},
        )
        resposta = extrair_texto(resultado["messages"][-1].content)
        fotos = extrair_fotos(resultado)

        # --- Guarda de política (PDF 4.5): preço só pode vir de tool. ---
        if resposta_tem_preco_inventado(resposta, resultado["messages"]):
            print(f"[Telegram] GUARDA: preço inventado detectado. Acionando handoff.")
            print(f"[Telegram] Resposta barrada: {resposta}")
            acionar_handoff.func(
                motivo="Guarda de política: valor em R$ sem origem em tool.",
                resumo=f"Resposta barrada do Léo: {resposta}",
                lead_id=chat_id,
            )
            resposta = MENSAGEM_SEGURA
            fotos = []

        print(f"[Telegram] Léo responde: {resposta}")
        if fotos:
            print(f"[Telegram] Enviando {len(fotos)} foto(s).")
        print()
        return resposta, fotos
    finally:
        await liberar_lock(chat_id)


async def ao_receber_texto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Chamada quando chega uma mensagem de TEXTO no bot."""
    chat_id = str(update.effective_chat.id)   # faz o papel do número/lead
    id_mensagem = f"{chat_id}:{update.message.message_id}"
    texto = update.message.text

    if ja_processada(id_mensagem):
        return

    # Calcula o atraso adaptativo com base em quanto tempo o cliente sumiu.
    atraso = await calcular_atraso(chat_id)

    resposta, fotos = await processar_texto(chat_id, texto)
    if resposta:
        await enviar_resposta_humanizada_telegram(update, resposta, atraso)
    for url in fotos:
        try:
            await update.message.reply_photo(url)
        except Exception as e:
            print(f"[Telegram] Erro ao enviar foto {url}: {e}")


async def ao_receber_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Chamada quando chega um ÁUDIO/voz no bot."""
    chat_id = str(update.effective_chat.id)
    id_mensagem = f"{chat_id}:{update.message.message_id}"

    if ja_processada(id_mensagem):
        return

    print(f"[Telegram] Cliente {chat_id} mandou um áudio. Transcrevendo...")

    # Telegram: pega o arquivo pelo file_id e baixa os bytes.
    objeto_audio = update.message.voice or update.message.audio
    if objeto_audio is None:
        return

    try:
        arquivo = await context.bot.get_file(objeto_audio.file_id)
        bytes_audio = bytes(await arquivo.download_as_bytearray())
    except Exception as e:
        print(f"[Telegram] Erro ao baixar áudio: {e}")
        return

    # A transcrição (Gemini) é síncrona, então roda numa thread pra não travar.
    mime = getattr(objeto_audio, "mime_type", None) or "audio/ogg"
    texto = await asyncio.to_thread(transcrever_bytes, bytes_audio, mime)

    if not texto:
        print(f"[Telegram] Não consegui transcrever o áudio de {chat_id}.")
        await update.message.reply_text(
            "Não consegui entender o áudio, pode mandar de novo ou escrever?"
        )
        return

    print(f"[Telegram] Áudio transcrito: {texto}")

    # Atraso adaptativo também para áudio.
    atraso = await calcular_atraso(chat_id)

    # Daqui pra frente é IGUAL ao texto: cai no mesmo cérebro do Léo.
    resposta, fotos = await processar_texto(chat_id, texto)
    if resposta:
        await enviar_resposta_humanizada_telegram(update, resposta, atraso)
    for url in fotos:
        try:
            await update.message.reply_photo(url)
        except Exception as e:
            print(f"[Telegram] Erro ao enviar foto {url}: {e}")



def main() -> None:
    """Liga o bot e fica ouvindo mensagens (polling)."""
    if not TELEGRAM_TOKEN:
        print("[Telegram] ERRO: TELEGRAM_TOKEN vazio. Confira o .env.")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).concurrent_updates(True).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ao_receber_texto))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, ao_receber_audio))

    print("[Telegram] Bot no ar! Mande uma mensagem pra ele no celular.")
    print("[Telegram] (Ctrl+C aqui no terminal para parar.)")
    app.run_polling()


if __name__ == "__main__":
    main()

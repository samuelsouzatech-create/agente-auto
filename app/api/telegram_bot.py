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
from app.api.receber_audio import transcrever_bytes

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


async def enviar_resposta_humanizada_telegram(update: Update, texto: str) -> None:
    """Divide a resposta em bolhas e envia uma a uma pelo Telegram,
    com o indicador de 'digitando...' antes de cada bolha e pausa entre elas."""
    bolhas = dividir_em_bolhas(texto)
    if not bolhas:
        return

    for i, bolha in enumerate(bolhas):
        # Mostra "digitando..." no Telegram (recurso nativo, igual conversa real).
        await update.message.chat.send_action("typing")
        await asyncio.sleep(1)  # um respiro pra parecer que está digitando
        await update.message.reply_text(bolha)
        if i < len(bolhas) - 1:
            await asyncio.sleep(PAUSA_ENTRE_BOLHAS)


async def processar_texto(chat_id: str, texto: str) -> str | None:
    """Trabalho pesado: debounce -> lock -> Léo. Devolve a resposta em texto
    (ou None se a rajada foi assumida por outra mensagem / lock ocupado)."""
    # 1) Debounce: acumula e espera o silêncio.
    texto_juntado = await acumular_e_esperar(chat_id, texto)
    if texto_juntado is None:
        return None

    # 2) Lock: uma execução por vez por lead.
    if not await adquirir_lock(chat_id):
        print(f"[Telegram] Lead {chat_id} já em processamento. Ignorando.")
        return None

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
        print(f"[Telegram] Léo responde: {resposta}\n")
        return resposta
    finally:
        await liberar_lock(chat_id)


async def ao_receber_texto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Chamada quando chega uma mensagem de TEXTO no bot."""
    chat_id = str(update.effective_chat.id)   # faz o papel do número/lead
    id_mensagem = f"{chat_id}:{update.message.message_id}"
    texto = update.message.text

    if ja_processada(id_mensagem):
        return

    resposta = await processar_texto(chat_id, texto)
    if resposta:
        await enviar_resposta_humanizada_telegram(update, resposta)


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

    # Daqui pra frente é IGUAL ao texto: cai no mesmo cérebro do Léo.
    resposta = await processar_texto(chat_id, texto)
    if resposta:
        await enviar_resposta_humanizada_telegram(update, resposta)


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

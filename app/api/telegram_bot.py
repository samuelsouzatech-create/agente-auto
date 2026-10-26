"""
Casca do Telegram (modo de testes, via polling).

Cada bot pertence a UMA loja: o id do bot (parte do token antes do ":")
é procurado na tabela canais. Sem nenhum bot cadastrado, atende a loja 1.
"""
import asyncio

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from langchain_core.messages import HumanMessage

from app.config import TELEGRAM_TOKEN
from app.core.agent import agente_grafo
from app.utils import extrair_texto, mensagens_do_turno
from app.formatacao import limpar_markdown
from app.humanizador import dividir_em_bolhas
from app.redis_debounce import acumular_e_esperar
from app.redis_lock import adquirir_lock_esperando, liberar_lock
from app.redis_atraso import calcular_atraso
from app.api.receber_audio import transcrever_bytes
from app.guarda_politica import resposta_tem_preco_inventado, MENSAGEM_SEGURA
from app.mensagens import salvar_mensagem
from app.handoff import estado_do_handoff
from app.dedup import ja_processada
from app.canais import resolver_loja, id_bot_telegram
from app.chaves import thread_id, LOJA_PADRAO
from tools import acionar_handoff

CANAL = "telegram"
BOT_ID = id_bot_telegram(TELEGRAM_TOKEN)
LOJA_DO_BOT = LOJA_PADRAO        # definido de verdade no main()
PAUSA_ENTRE_BOLHAS = 2


async def esperar_digitando(update: Update, segundos: float) -> None:
    """Mantém o 'digitando...' aceso durante a espera (dura ~5s; reaciona a cada 4s)."""
    restante = segundos
    while restante > 0:
        await update.message.chat.send_action("typing")
        passo = min(4, restante)
        await asyncio.sleep(passo)
        restante -= passo


async def enviar_resposta_humanizada_telegram(update: Update, texto: str, atraso: float = 0) -> None:
    bolhas = dividir_em_bolhas(texto)
    if not bolhas:
        return
    if atraso > 0:
        await esperar_digitando(update, atraso)
    for i, bolha in enumerate(bolhas):
        await update.message.chat.send_action("typing")
        await asyncio.sleep(1)
        await update.message.reply_text(bolha)
        if i < len(bolhas) - 1:
            await asyncio.sleep(PAUSA_ENTRE_BOLHAS)


def extrair_fotos(resultado) -> list:
    urls = []
    for m in mensagens_do_turno(resultado):
        artifact = getattr(m, "artifact", None)
        if isinstance(artifact, dict) and artifact.get("tipo") == "fotos":
            urls.extend(artifact.get("urls", []))
    return urls


async def processar_texto(chat_id: str, texto: str, loja_id: int = LOJA_PADRAO):
    """debounce -> lock -> Léo. Devolve (resposta, fotos) ou (None, [])."""
    rotulo = f"[Telegram][loja {loja_id}]"

    texto_juntado = await acumular_e_esperar(chat_id, texto, loja_id=loja_id)
    if texto_juntado is None:
        return None, []

    token_lock = await adquirir_lock_esperando(chat_id, loja_id=loja_id)
    if token_lock is None:
        print(f"{rotulo} Lead {chat_id}: lock ocupado tempo demais. Desistindo.")
        return None, []

    try:
        print(f"\n{rotulo} Cliente {chat_id} disse: {texto_juntado}")
        salvar_mensagem(chat_id, "cliente", texto_juntado, canal=CANAL, loja_id=loja_id)

        if estado_do_handoff(chat_id, loja_id) == "humano_assumiu":
            print(f"{rotulo} Lead {chat_id} está com um vendedor humano. Léo em silêncio.")
            return None, []

        resultado = await asyncio.to_thread(
            agente_grafo.invoke,
            {
                "messages": [HumanMessage(content=texto_juntado)],
                "lead_id": chat_id,
                "loja_id": loja_id,
                "canal": CANAL,
            },
            {"configurable": {"thread_id": thread_id(loja_id, CANAL, chat_id)}},
        )
        resposta = limpar_markdown(extrair_texto(resultado["messages"][-1].content))
        fotos = extrair_fotos(resultado)

        if resposta_tem_preco_inventado(resposta, resultado["messages"]):
            print(f"{rotulo} GUARDA: preço inventado detectado. Acionando handoff.")
            print(f"{rotulo} Resposta barrada: {resposta}")
            acionar_handoff.func(
                motivo="Guarda de política: valor em R$ sem origem em tool.",
                resumo=f"Resposta barrada do Léo: {resposta}",
                lead_id=chat_id,
                loja_id=loja_id,
            )
            resposta = MENSAGEM_SEGURA
            fotos = []

        print(f"{rotulo} Léo responde: {resposta}")
        if fotos:
            print(f"{rotulo} Enviando {len(fotos)} foto(s).")
        print()

        salvar_mensagem(chat_id, "leo", resposta, canal=CANAL, loja_id=loja_id)
        return resposta, fotos
    finally:
        await liberar_lock(chat_id, token_lock, loja_id=loja_id)


async def _responder(update: Update, chat_id: str, texto: str) -> None:
    atraso = await calcular_atraso(chat_id, loja_id=LOJA_DO_BOT)
    resposta, fotos = await processar_texto(chat_id, texto, loja_id=LOJA_DO_BOT)
    if resposta:
        await enviar_resposta_humanizada_telegram(update, resposta, atraso)
    for url in fotos:
        try:
            await update.message.reply_photo(url)
        except Exception as e:
            print(f"[Telegram] Erro ao enviar foto {url}: {e}")


def _id_mensagem(update: Update) -> str:
    # message_id do Telegram só é único dentro do chat; por isso bot + chat + id.
    return f"{BOT_ID}:{update.effective_chat.id}:{update.message.message_id}"


async def ao_receber_texto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await ja_processada(CANAL, _id_mensagem(update)):
        return
    await _responder(update, str(update.effective_chat.id), update.message.text)


async def ao_receber_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if await ja_processada(CANAL, _id_mensagem(update)):
        return

    print(f"[Telegram] Cliente {chat_id} mandou um áudio. Transcrevendo...")
    objeto_audio = update.message.voice or update.message.audio
    if objeto_audio is None:
        return
    try:
        arquivo = await context.bot.get_file(objeto_audio.file_id)
        bytes_audio = bytes(await arquivo.download_as_bytearray())
    except Exception as e:
        print(f"[Telegram] Erro ao baixar áudio: {e}")
        return

    mime = getattr(objeto_audio, "mime_type", None) or "audio/ogg"
    texto = await asyncio.to_thread(transcrever_bytes, bytes_audio, mime)
    if not texto:
        print(f"[Telegram] Não consegui transcrever o áudio de {chat_id}.")
        await update.message.reply_text("Não consegui entender o áudio, pode mandar de novo ou escrever?")
        return

    print(f"[Telegram] Áudio transcrito: {texto}")
    await _responder(update, chat_id, texto)


def main() -> None:
    global LOJA_DO_BOT
    if not TELEGRAM_TOKEN:
        print("[Telegram] ERRO: TELEGRAM_TOKEN vazio. Confira o .env.")
        return

    loja = resolver_loja(CANAL, BOT_ID)
    if loja is None:
        print(f"[Telegram] ERRO: o bot {BOT_ID} não está cadastrado em canais. Rode:")
        print(f"  python scripts/cadastrar_canal.py telegram auto <loja_id>")
        return
    LOJA_DO_BOT = loja

    app = Application.builder().token(TELEGRAM_TOKEN).concurrent_updates(True).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ao_receber_texto))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, ao_receber_audio))

    print(f"[Telegram] Bot {BOT_ID} no ar, atendendo a loja {LOJA_DO_BOT}.")
    print("[Telegram] (Ctrl+C aqui no terminal para parar.)")
    app.run_polling()


if __name__ == "__main__":
    main()

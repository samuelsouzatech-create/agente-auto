"""
Casca do Telegram (modo de testes, via polling) - só a "porta".

Cada bot pertence a UMA loja (tabela canais). O atendimento em si é o
executar_turno() (app/core/turno.py), o mesmo do WhatsApp.
"""
import asyncio

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from app.config import TELEGRAM_TOKEN
from app.core.agent import agente_grafo
from app.core.turno import (
    ResultadoTurno, executar_turno, aguardar_vez, turno_midia_nao_suportada, turno_audio_falhou,
)
from app.channels.base import enviar_humanizado, enviar_resultado
from app.channels.telegram import CanalTelegram
from app.api.receber_audio import transcrever_bytes
from app.redis_lock import liberar_lock
from app.redis_atraso import calcular_atraso
from app.dedup import ja_processada
from app.canais import resolver_loja, id_bot_telegram
from app.chaves import LOJA_PADRAO

CANAL = "telegram"
BOT_ID = id_bot_telegram(TELEGRAM_TOKEN)
LOJA_DO_BOT = LOJA_PADRAO        # definido de verdade no main()


async def processar_texto(chat_id: str, texto: str, loja_id: int = LOJA_PADRAO):
    """debounce + lock -> executar_turno. Devolve (resposta, fotos) ou (None, [])."""
    texto_juntado, token = await aguardar_vez(loja_id, chat_id, texto)
    if texto_juntado is None:
        return None, []
    try:
        resultado = await executar_turno(loja_id, CANAL, chat_id, texto_juntado, grafo=agente_grafo)
    finally:
        await liberar_lock(chat_id, token, loja_id=loja_id)
    if resultado.silenciado:
        return None, []
    return resultado.texto, resultado.midias


async def _responder(canal: CanalTelegram, chat_id: str, texto: str) -> None:
    atraso = await calcular_atraso(chat_id, loja_id=LOJA_DO_BOT)
    resposta, fotos = await processar_texto(chat_id, texto, loja_id=LOJA_DO_BOT)
    if resposta or fotos:
        await enviar_resultado(canal, chat_id, ResultadoTurno(texto=resposta, midias=fotos), atraso)


async def _responder_audio(canal: CanalTelegram, entrada) -> None:
    chat_id = entrada.lead_id
    print(f"[Telegram] Cliente {chat_id} mandou um áudio. Transcrevendo...")
    bytes_audio = await canal.baixar_midia(entrada)
    texto = None
    if bytes_audio:
        texto = await asyncio.to_thread(transcrever_bytes, bytes_audio, entrada.mime or "audio/ogg")
    if not texto:
        aviso = turno_audio_falhou(LOJA_DO_BOT, CANAL, chat_id)
        if aviso.texto:
            await canal.enviar_texto(chat_id, aviso.texto)
        return
    print(f"[Telegram] Áudio transcrito: {texto}")
    await _responder(canal, chat_id, texto)


async def ao_receber(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    canal = CanalTelegram(context.bot, BOT_ID)
    for entrada in canal.ler_webhook(update):
        if await ja_processada(CANAL, entrada.id_externo):
            continue
        if entrada.tipo == "texto":
            await _responder(canal, entrada.lead_id, entrada.texto)
        elif entrada.tipo == "audio":
            await _responder_audio(canal, entrada)
        else:
            aviso = turno_midia_nao_suportada(LOJA_DO_BOT, CANAL, entrada.lead_id, entrada.tipo_original)
            if aviso.texto:
                await enviar_humanizado(canal, entrada.lead_id, aviso.texto)


def main() -> None:
    global LOJA_DO_BOT
    if not TELEGRAM_TOKEN:
        print("[Telegram] ERRO: TELEGRAM_TOKEN vazio. Confira o .env.")
        return

    loja = resolver_loja(CANAL, BOT_ID)
    if loja is None:
        print(f"[Telegram] ERRO: o bot {BOT_ID} não está cadastrado em canais. Rode:")
        print("  python scripts/cadastrar_canal.py telegram auto <loja_id>")
        return
    LOJA_DO_BOT = loja

    app = Application.builder().token(TELEGRAM_TOKEN).concurrent_updates(True).build()
    app.add_handler(MessageHandler(filters.UpdateType.MESSAGE & ~filters.COMMAND, ao_receber))

    print(f"[Telegram] Bot {BOT_ID} no ar, atendendo a loja {LOJA_DO_BOT}.")
    print("[Telegram] (Ctrl+C aqui no terminal para parar.)")
    app.run_polling()


if __name__ == "__main__":
    main()

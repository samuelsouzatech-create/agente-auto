"""
Casca do Telegram (modo de testes, via polling) - só a "porta".

Cada bot pertence a UMA loja (tabela canais). O atendimento em si é o
executar_turno() (app/core/turno.py), o mesmo do WhatsApp.

Rodar (o argumento é o NOME da variável do .env, nunca o token):
    python -m app.api.telegram_bot                       bot do TELEGRAM_TOKEN
    python -m app.api.telegram_bot TELEGRAM_TOKEN_LOJA2  bot de outra loja

P7c: áudio de quem não é número de teste, numa loja em teste, nem é
baixado nem transcrito. A porta grava o evento no Registro.
"""
import asyncio
import os
import sys

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from app import config as _config  # noqa: F401  (carrega o .env)
from app.core.agent import agente_grafo
from app.core.turno import (
    ResultadoTurno, executar_turno, aguardar_vez, porta_fechada,
    turno_midia_nao_suportada, turno_audio_falhou, executar_turno_imagem,
)
from app.channels.base import enviar_humanizado, enviar_resultado
from app.channels.telegram import CanalTelegram
from app.api.receber_audio import transcrever_do_cliente
from app.redis_lock import adquirir_lock_esperando, liberar_lock
from app.redis_atraso import calcular_atraso
from app.dedup import ja_processada
from app.canais import resolver_loja, id_bot_telegram
from app.chaves import exigir_loja
from app.logs import registrar_canal_desconhecido

CANAL = "telegram"
VARIAVEL_PADRAO = "TELEGRAM_TOKEN"

# Definidos no main(). Sem loja definida, nada é atendido (nunca "loja 1 por reserva").
BOT_ID = ""
LOJA_DO_BOT = None


def _loja_do_bot() -> int:
    return exigir_loja(LOJA_DO_BOT)


async def processar_texto(chat_id: str, texto: str, loja_id: int | None = None):
    """debounce + lock -> executar_turno. Devolve (resposta, fotos) ou (None, [])."""
    loja_id = exigir_loja(loja_id)
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
    loja_id = _loja_do_bot()
    atraso = await calcular_atraso(chat_id, loja_id=loja_id)
    resposta, fotos = await processar_texto(chat_id, texto, loja_id=loja_id)
    if resposta or fotos:
        await enviar_resultado(canal, chat_id, ResultadoTurno(texto=resposta, midias=fotos), atraso)


async def _responder_audio(canal: CanalTelegram, entrada) -> None:
    loja_id = _loja_do_bot()
    chat_id = entrada.lead_id
    # P7c: loja em teste e não é número de teste: nem baixa nem transcreve (custo).
    if porta_fechada(loja_id, CANAL, chat_id):
        return
    print(f"[Telegram][loja {loja_id}] Cliente {chat_id} mandou um áudio. Transcrevendo...")
    bytes_audio = await canal.baixar_midia(entrada)
    texto = None
    if bytes_audio:
        texto, _ = await asyncio.to_thread(
            transcrever_do_cliente, loja_id, chat_id, CANAL, bytes_audio, entrada.mime or "audio/ogg")
    if not texto:
        aviso = turno_audio_falhou(loja_id, CANAL, chat_id)
        if aviso.texto:
            await canal.enviar_texto(chat_id, aviso.texto)
        return
    print(f"[Telegram][loja {loja_id}] Áudio transcrito: {texto}")
    await _responder(canal, chat_id, texto)


async def _responder_imagem(canal: CanalTelegram, entrada) -> None:
    """L5b: foto do cliente. Loja em teste: nem baixa (custo). A imagem não é guardada."""
    loja_id = _loja_do_bot()
    chat_id = entrada.lead_id
    if porta_fechada(loja_id, CANAL, chat_id):
        return
    token = await adquirir_lock_esperando(chat_id, loja_id=loja_id)
    if token is None:
        return
    try:
        imagem = await canal.baixar_midia(entrada)
        atraso = await calcular_atraso(chat_id, loja_id=loja_id)
        resultado = await executar_turno_imagem(
            loja_id, CANAL, chat_id, imagem or b"", entrada.mime or "image/jpeg", entrada.texto,
            grafo=agente_grafo, leitor=None if imagem else _leitura_falhou)
    finally:
        await liberar_lock(chat_id, token, loja_id=loja_id)
    if not resultado.silenciado and (resultado.texto or resultado.midias):
        await enviar_resultado(canal, chat_id, resultado, atraso)


def _leitura_falhou(imagem, mime):
    """Foto que não deu para baixar: o turno segue como leitura que falhou."""
    from app.imagens import LeituraImagem
    return LeituraImagem(ok=False)


async def ao_receber(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    canal = CanalTelegram(context.bot, BOT_ID)
    for entrada in canal.ler_webhook(update):
        if await ja_processada(CANAL, entrada.id_externo):
            continue
        if entrada.tipo == "texto":
            await _responder(canal, entrada.lead_id, entrada.texto)
        elif entrada.tipo == "audio":
            await _responder_audio(canal, entrada)
        elif entrada.tipo == "imagem":
            await _responder_imagem(canal, entrada)
        else:
            aviso = turno_midia_nao_suportada(_loja_do_bot(), CANAL, entrada.lead_id,
                                              entrada.tipo_original)
            if aviso.texto:
                await enviar_humanizado(canal, entrada.lead_id, aviso.texto)


def main(argv=None) -> None:
    global BOT_ID, LOJA_DO_BOT
    argumentos = sys.argv[1:] if argv is None else list(argv)
    variavel = argumentos[0] if argumentos else VARIAVEL_PADRAO
    if ":" in variavel:
        print("[Telegram] ERRO: passe o NOME da variável do .env, não o token.")
        return
    token = (os.getenv(variavel) or "").strip()
    if not token:
        print(f"[Telegram] ERRO: {variavel} vazio. Confira o .env.")
        return

    BOT_ID = id_bot_telegram(token)
    loja = resolver_loja(CANAL, BOT_ID)
    if loja is None:
        registrar_canal_desconhecido(CANAL, BOT_ID)
        print(f"[Telegram] ERRO: o bot {BOT_ID} não está cadastrado (ou está desativado) em canais.")
        print("  Cadastre em: painel do operador > Lojas e canais.")
        return
    LOJA_DO_BOT = loja

    aplicacao = Application.builder().token(token).concurrent_updates(True).build()
    aplicacao.add_handler(MessageHandler(filters.UpdateType.MESSAGE & ~filters.COMMAND, ao_receber))

    print(f"[Telegram] Bot {BOT_ID} ({variavel}) no ar, atendendo a loja {LOJA_DO_BOT}.")
    print("[Telegram] (Ctrl+C aqui no terminal para parar.)")
    aplicacao.run_polling()


if __name__ == "__main__":
    main()

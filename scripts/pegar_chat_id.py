"""
Mostra o chat_id de quem mandar mensagem para o bot de avisos.
Uso: python scripts/pegar_chat_id.py
Serve também, no futuro, para pegar o chat_id dos vendedores e gestores.
"""
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_AVISOS_TOKEN", "").strip()
if not TOKEN:
    sys.exit("TELEGRAM_AVISOS_TOKEN não encontrado no .env")

URL = f"https://api.telegram.org/bot{TOKEN}"
bot = httpx.get(f"{URL}/getMe").json()["result"]["username"]
print(f"Abra t.me/{bot} no Telegram, toque em Iniciar e mande 'oi'.")
print("Esperando até 2 minutos... (Ctrl+C para cancelar)\n")

for _ in range(4):
    resposta = httpx.get(f"{URL}/getUpdates", params={"timeout": 30}, timeout=40).json()
    if not resposta.get("ok"):
        sys.exit(f"Erro do Telegram: {resposta}")
    achados = {}
    for update in resposta["result"]:
        msg = update.get("message") or update.get("edited_message")
        if msg:
            chat = msg["chat"]
            achados[chat["id"]] = chat.get("first_name") or chat.get("title") or "?"
    if achados:
        for chat_id, nome in achados.items():
            print(f"chat_id: {chat_id}   ({nome})")
        break
else:
    print("Nenhuma mensagem chegou. Confira se mandou para o bot certo.")

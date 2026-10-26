"""Canal Telegram, no contrato de app/channels/base.py.
Recebe o 'bot' pronto (context.bot), por isso não importa a biblioteca aqui."""
from __future__ import annotations

from app.channels.base import Canal, MensagemEntrada

# Ordem importa: animation vem antes de document (o GIF também tem document).
_NAO_SUPORTADOS = (
    ("animation", "animation"), ("photo", "image"), ("sticker", "sticker"),
    ("video", "video"), ("video_note", "video"), ("document", "document"),
    ("location", "location"), ("contact", "contacts"),
)


class CanalTelegram(Canal):
    nome = "telegram"
    duracao_digitando = 4.0    # o "digitando" do Telegram some em ~5 s

    def __init__(self, bot, bot_id: str = ""):
        self.bot = bot
        self.bot_id = bot_id

    def ler_webhook(self, update) -> list[MensagemEntrada]:
        msg = getattr(update, "message", None)          # edições são ignoradas
        chat = getattr(update, "effective_chat", None)
        if msg is None or chat is None:
            return []
        data = getattr(msg, "date", None)
        comum = dict(
            canal=self.nome,
            # message_id só é único dentro do chat: por isso bot + chat + id.
            id_externo=f"{self.bot_id}:{chat.id}:{msg.message_id}",
            lead_id=str(chat.id),
            id_canal=self.bot_id,
            hora=int(data.timestamp()) if data else 0,
        )

        texto = (getattr(msg, "text", None) or "").strip()
        if texto:
            return [MensagemEntrada(tipo="texto", texto=texto, tipo_original="text", **comum)]

        audio = getattr(msg, "voice", None) or getattr(msg, "audio", None)
        if audio is not None:
            return [MensagemEntrada(tipo="audio", id_midia=audio.file_id,
                                    mime=getattr(audio, "mime_type", None) or "audio/ogg",
                                    tipo_original="audio", **comum)]

        for atributo, tipo_original in _NAO_SUPORTADOS:
            if getattr(msg, atributo, None):
                return [MensagemEntrada(tipo="nao_suportado", tipo_original=tipo_original, **comum)]

        return []   # mensagens de serviço (entrou no grupo etc.)

    async def enviar_texto(self, lead_id: str, texto: str) -> bool:
        try:
            await self.bot.send_message(chat_id=lead_id, text=texto)
            return True
        except Exception as erro:
            print(f"[Telegram] Erro ao enviar texto para {lead_id}: {erro}")
            return False

    async def enviar_midia(self, lead_id: str, url: str) -> bool:
        try:
            await self.bot.send_photo(chat_id=lead_id, photo=url)
            return True
        except Exception as erro:
            print(f"[Telegram] Erro ao enviar foto {url}: {erro}")
            return False

    async def digitando(self, lead_id: str) -> None:
        try:
            await self.bot.send_chat_action(chat_id=lead_id, action="typing")
        except Exception:
            pass

    async def baixar_midia(self, entrada: MensagemEntrada) -> bytes | None:
        try:
            arquivo = await self.bot.get_file(entrada.id_midia)
            return bytes(await arquivo.download_as_bytearray())
        except Exception as erro:
            print(f"[Telegram] Erro ao baixar mídia: {erro}")
            return None

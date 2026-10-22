"""
Transcrição de áudio para o Agente Léo.

Duas camadas:
- transcrever_bytes(bytes, mime): manda os bytes do áudio pro Gemini e
  devolve o texto. É igual para qualquer canal (WhatsApp, Telegram...).
- transcrever_audio(id_audio): fluxo específico do WhatsApp/Meta (baixa o
  áudio pelo id de mídia e chama transcrever_bytes).
"""
import httpx
from google import genai

from app.config import (
    WHATSAPP_TOKEN,
    WHATSAPP_API_VERSION,
    GOOGLE_API_KEY,
    MODELO_LLM,
)


def transcrever_bytes(bytes_audio: bytes, mime: str = "audio/ogg") -> str | None:
    """Manda os bytes do áudio pro Gemini e devolve o texto transcrito.
    Devolve None se algo falhar (nunca lança exceção)."""
    try:
        cliente_gemini = genai.Client(api_key=GOOGLE_API_KEY)
        resposta = cliente_gemini.models.generate_content(
            model=MODELO_LLM,
            contents=[
                "Transcreva este áudio em português do Brasil. "
                "Responda APENAS com a transcrição, sem comentários.",
                genai.types.Part.from_bytes(data=bytes_audio, mime_type=mime),
            ],
        )
        texto = (resposta.text or "").strip()
        return texto or None
    except Exception as e:
        print(f"[Audio] Erro ao transcrever no Gemini: {e}")
        return None


async def transcrever_audio(id_audio: str) -> str | None:
    """Fluxo do WhatsApp/Meta: baixa o áudio pelo id e transcreve.
    Devolve None se não houver token ou se algo falhar."""

    if not WHATSAPP_TOKEN:
        print("[WhatsApp] AVISO: WHATSAPP_TOKEN vazio. "
              "Transcrição de áudio pulada (ainda em modo local).")
        return None

    cabecalho = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

    try:
        async with httpx.AsyncClient(timeout=30) as cliente:
            url_meta = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{id_audio}"
            resp = await cliente.get(url_meta, headers=cabecalho)
            resp.raise_for_status()
            dados_midia = resp.json()
            url_arquivo = dados_midia["url"]
            mime = dados_midia.get("mime_type", "audio/ogg")

            resp_audio = await cliente.get(url_arquivo, headers=cabecalho)
            resp_audio.raise_for_status()
            bytes_audio = resp_audio.content

        # A transcrição em si é igual pra todos os canais.
        return transcrever_bytes(bytes_audio, mime)

    except Exception as e:
        print(f"[WhatsApp] Erro ao baixar áudio: {e}")
        return None

"""
Recebe áudio do cliente no WhatsApp e devolve o texto transcrito.

Fluxo (seção 4.3 do PDF — "se for áudio, vai direto ao Gemini"):
1) A Meta manda só um id de mídia. Com o token, pegamos a URL do arquivo.
2) Baixamos o áudio (bytes) dessa URL.
3) Enviamos os bytes pro Gemini, que entende áudio de forma nativa, e
   pedimos a transcrição em texto.

Sem WHATSAPP_TOKEN (modo local, ainda sem Meta), a função avisa e devolve
None, sem quebrar o webhook — mesmo padrão do envio.
"""
import httpx
from google import genai

from app.config import (
    WHATSAPP_TOKEN,
    WHATSAPP_API_VERSION,
    GOOGLE_API_KEY,
    MODELO_LLM,
)


async def transcrever_audio(id_audio: str) -> str | None:
    """Baixa o áudio da Meta pelo id e devolve o texto transcrito pelo Gemini.
    Devolve None se não houver token ou se algo falhar (nunca lança exceção)."""

    if not WHATSAPP_TOKEN:
        print("[WhatsApp] AVISO: WHATSAPP_TOKEN vazio. "
              "Transcrição de áudio pulada (ainda em modo local).")
        return None

    cabecalho = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

    try:
        async with httpx.AsyncClient(timeout=30) as cliente:
            # 1) Pega a URL do arquivo de mídia a partir do id.
            url_meta = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{id_audio}"
            resp = await cliente.get(url_meta, headers=cabecalho)
            resp.raise_for_status()
            dados_midia = resp.json()
            url_arquivo = dados_midia["url"]
            mime = dados_midia.get("mime_type", "audio/ogg")

            # 2) Baixa os bytes do áudio (a URL também exige o token).
            resp_audio = await cliente.get(url_arquivo, headers=cabecalho)
            resp_audio.raise_for_status()
            bytes_audio = resp_audio.content

        # 3) Manda pro Gemini transcrever (entendimento de áudio nativo).
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
        print(f"[WhatsApp] Erro ao transcrever áudio: {e}")
        return None

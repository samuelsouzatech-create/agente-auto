"""
Transcrição de áudio para o Agente Léo.

Este é o ÚNICO arquivo que conhece o SDK do fornecedor de IA para áudio
(hoje, google-genai). Se trocar de fornecedor, é aqui que muda,
inclusive a leitura dos tokens (uso_da_resposta).

- transcrever_bytes_com_uso(bytes, mime)  -> (texto, Uso)
- transcrever_bytes(bytes, mime)          -> texto (compatibilidade)
- transcrever_audio(id_audio, loja_id=..) -> texto (WhatsApp, token DA LOJA)
"""
import httpx
from google import genai

from app.config import WHATSAPP_API_VERSION, GOOGLE_API_KEY, MODELO_LLM
from app.credenciais import SemCredencial, credencial_whatsapp
from app.custos import Uso

# Uso de cada transcrição do WhatsApp, guardado pelo id do áudio até o
# webhook pegar (pegar_uso_da_transcricao) e registrar o custo.
_uso_por_audio: dict[str, Uso] = {}
_LIMITE_USOS = 1000


def uso_da_resposta(resposta) -> Uso:
    """Tokens da resposta do SDK (formato google-genai). Zero se faltar algo."""
    try:
        meta = getattr(resposta, "usage_metadata", None)
        if meta is None:
            return Uso()
        entrada = int(getattr(meta, "prompt_token_count", 0) or 0)
        saida = int(getattr(meta, "candidates_token_count", 0) or 0)
        audio = 0
        for detalhe in getattr(meta, "prompt_tokens_details", None) or []:
            if "AUDIO" in str(getattr(detalhe, "modality", "")).upper():
                audio += int(getattr(detalhe, "token_count", 0) or 0)
        audio = min(audio, entrada)
        return Uso(entrada - audio, saida, audio)
    except Exception:
        return Uso()


def transcrever_bytes_com_uso(bytes_audio: bytes, mime: str = "audio/ogg") -> tuple[str | None, Uso]:
    """Transcreve e devolve (texto, uso). Nunca lança exceção."""
    try:
        cliente_ia = genai.Client(api_key=GOOGLE_API_KEY)
        resposta = cliente_ia.models.generate_content(
            model=MODELO_LLM,
            contents=[
                "Transcreva este áudio em português do Brasil. "
                "Responda APENAS com a transcrição, sem comentários.",
                genai.types.Part.from_bytes(data=bytes_audio, mime_type=mime),
            ],
        )
        texto = (resposta.text or "").strip()
        return (texto or None), uso_da_resposta(resposta)
    except Exception as e:
        print(f"[Audio] Erro ao transcrever na IA: {e}")
        return None, Uso()


def transcrever_bytes(bytes_audio: bytes, mime: str = "audio/ogg") -> str | None:
    """Compatibilidade: só o texto."""
    return transcrever_bytes_com_uso(bytes_audio, mime)[0]


def pegar_uso_da_transcricao(id_audio: str) -> Uso | None:
    """Devolve (e esquece) o uso da transcrição daquele áudio do WhatsApp."""
    return _uso_por_audio.pop(id_audio, None)


async def transcrever_audio(id_audio: str, *, loja_id: int) -> str | None:
    """WhatsApp: baixa o áudio pelo id (com o token DA LOJA) e transcreve.
    Devolve None se a loja não tiver credencial ou se algo falhar."""
    try:
        cred = credencial_whatsapp(loja_id)
    except SemCredencial as erro:
        print(f"[WhatsApp][loja {loja_id}] Transcrição de áudio pulada: {erro}.")
        return None

    cabecalho = {"Authorization": f"Bearer {cred.token}"}
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

        texto, uso = transcrever_bytes_com_uso(bytes_audio, mime)
        if len(_uso_por_audio) > _LIMITE_USOS:
            _uso_por_audio.clear()
        _uso_por_audio[id_audio] = uso
        return texto
    except Exception as e:
        print(f"[WhatsApp][loja {loja_id}] Erro ao baixar áudio: {type(e).__name__}")
        return None

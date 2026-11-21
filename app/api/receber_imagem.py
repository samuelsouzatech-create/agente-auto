"""L5: baixa a foto que o cliente mandou no WhatsApp (com o token DA LOJA).
A imagem só fica na memória durante o turno: nada é gravado em disco nem no banco."""
import httpx

from app.config import WHATSAPP_API_VERSION
from app.credenciais import SemCredencial, credencial_whatsapp

from app.limites_midia import LIMITE_FOTO_BYTES as LIMITE_BYTES, MidiaGrandeDemais, conferir_foto   # N2
from app.log import logger as _logger   # N3: registro técnico (logs/leo.log)
_log = _logger("receber_imagem")


async def baixar_imagem_whatsapp(id_midia: str, *, loja_id: int) -> tuple[bytes, str] | None:
    """(bytes, mime) ou None se a loja não tiver credencial ou se algo falhar."""
    try:
        cred = credencial_whatsapp(loja_id)
    except SemCredencial as erro:
        _log.info(f"[WhatsApp][loja {loja_id}] Foto não baixada: {erro}.")
        return None
    cabecalho = {"Authorization": f"Bearer {cred.token}"}
    try:
        async with httpx.AsyncClient(timeout=30) as cliente:
            resp = await cliente.get(f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{id_midia}",
                                     headers=cabecalho)
            resp.raise_for_status()
            dados = resp.json()
            conferir_foto(dados.get("file_size"))          # N2: antes de baixar, se a Meta informar
            arquivo = await cliente.get(dados["url"], headers=cabecalho)
            arquivo.raise_for_status()
        conferir_foto(len(arquivo.content))
        return arquivo.content, dados.get("mime_type", "image/jpeg")
    except MidiaGrandeDemais:
        _log.warning(f"[WhatsApp][loja {loja_id}] Foto grande demais. Não lida.")
        raise
    except Exception as erro:
        _log.error(f"[WhatsApp][loja {loja_id}] Erro ao baixar foto: {type(erro).__name__}")
        return None

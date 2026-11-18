"""L5: baixa a foto que o cliente mandou no WhatsApp (com o token DA LOJA).
A imagem só fica na memória durante o turno: nada é gravado em disco nem no banco."""
import httpx

from app.config import WHATSAPP_API_VERSION
from app.credenciais import SemCredencial, credencial_whatsapp

LIMITE_BYTES = 10 * 1024 * 1024      # foto maior que isso não é lida


async def baixar_imagem_whatsapp(id_midia: str, *, loja_id: int) -> tuple[bytes, str] | None:
    """(bytes, mime) ou None se a loja não tiver credencial ou se algo falhar."""
    try:
        cred = credencial_whatsapp(loja_id)
    except SemCredencial as erro:
        print(f"[WhatsApp][loja {loja_id}] Foto não baixada: {erro}.")
        return None
    cabecalho = {"Authorization": f"Bearer {cred.token}"}
    try:
        async with httpx.AsyncClient(timeout=30) as cliente:
            resp = await cliente.get(f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{id_midia}",
                                     headers=cabecalho)
            resp.raise_for_status()
            dados = resp.json()
            arquivo = await cliente.get(dados["url"], headers=cabecalho)
            arquivo.raise_for_status()
        if len(arquivo.content) > LIMITE_BYTES:
            print(f"[WhatsApp][loja {loja_id}] Foto grande demais. Não lida.")
            return None
        return arquivo.content, dados.get("mime_type", "image/jpeg")
    except Exception as erro:
        print(f"[WhatsApp][loja {loja_id}] Erro ao baixar foto: {type(erro).__name__}")
        return None

"""Canal simulador: guarda o que 'enviaria' numa lista. Usado nos testes e,
na Etapa 4, na página de demonstração. Não tem janela de 24 h."""
from __future__ import annotations

import base64
import binascii
import uuid

from app.channels.base import Canal, MensagemEntrada
from app.resultado_envio import ResultadoEnvio
from app.templates import ValoresFaltando, preencher


def _imagem(valor) -> bytes:
    """L5: imagem em base64 no payload do simulador. Inválida ou vazia: b""."""
    if not valor:
        return b""
    try:
        return base64.b64decode(str(valor), validate=True)
    except (binascii.Error, ValueError):
        return b""


class CanalSimulador(Canal):
    nome = "simulador"
    duracao_digitando = 0.5
    respiro_s = 0
    pausa_entre_bolhas = 0

    def __init__(self):
        self.enviadas: list[tuple[str, str]] = []

    def ler_webhook(self, payload) -> list[MensagemEntrada]:
        payload = payload if isinstance(payload, dict) else {}
        texto = str(payload.get("texto", "")).strip()
        lead_id = str(payload.get("lead_id", "")).strip()
        imagem = _imagem(payload.get("imagem_base64"))
        if lead_id and imagem:                      # L5: foto, com ou sem legenda
            return [MensagemEntrada(canal=self.nome, id_externo=str(payload.get("id") or uuid.uuid4().hex),
                                    lead_id=lead_id, tipo="imagem", texto=texto, tipo_original="image",
                                    mime=str(payload.get("mime") or "image/jpeg"), conteudo=imagem)]
        if not texto or not lead_id:
            return []
        return [MensagemEntrada(canal=self.nome, id_externo=str(payload.get("id") or uuid.uuid4().hex),
                                lead_id=lead_id, tipo="texto", texto=texto, tipo_original="text")]

    async def enviar_texto(self, lead_id: str, texto: str) -> bool:
        self.enviadas.append(("texto", texto))
        return True

    async def enviar_midia(self, lead_id: str, url: str) -> bool:
        self.enviadas.append(("midia", url))
        return True

    async def enviar_foto(self, lead_id: str, loja_id: int, ref: str) -> bool:
        """Simulador: nada sai; anota a foto do depósito (só as desta loja)."""
        from app import fotos
        if fotos.chave_da_ref(loja_id, ref) is None:
            return False
        self.enviadas.append(("midia", ref))
        return True

    async def enviar_template(self, lead_id: str, modelo, valores: dict) -> ResultadoEnvio:
        try:
            texto = preencher(modelo, valores)
        except ValoresFaltando as erro:
            return ResultadoEnvio(ok=False, detalhe=str(erro))
        self.enviadas.append(("modelo", texto))
        return ResultadoEnvio(ok=True, id_externo=f"sim-{uuid.uuid4().hex[:8]}")

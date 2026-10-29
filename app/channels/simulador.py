"""Canal simulador: guarda o que 'enviaria' numa lista. Usado nos testes e,
na Etapa 4, na página de demonstração. Não tem janela de 24 h."""
from __future__ import annotations

import uuid

from app.channels.base import Canal, MensagemEntrada
from app.resultado_envio import ResultadoEnvio
from app.templates import ValoresFaltando, preencher


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

    async def enviar_template(self, lead_id: str, modelo, valores: dict) -> ResultadoEnvio:
        try:
            texto = preencher(modelo, valores)
        except ValoresFaltando as erro:
            return ResultadoEnvio(ok=False, detalhe=str(erro))
        self.enviadas.append(("modelo", texto))
        return ResultadoEnvio(ok=True, id_externo=f"sim-{uuid.uuid4().hex[:8]}")

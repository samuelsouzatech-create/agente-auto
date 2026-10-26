"""
Contrato único dos canais (Etapa 1, Bloco 4 - item 1.7).

Todo canal (WhatsApp, Telegram, simulador e, na Etapa 3, Instagram) sabe:
  - ler_webhook(payload)  -> lista de MensagemEntrada (várias por pacote)
  - enviar_texto / enviar_midia
  - marcar_lida / digitando (quando o canal tiver)
  - enviar_template / janela_aberta (implementados na Etapa 2)
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.humanizador import dividir_em_bolhas


@dataclass(frozen=True)
class MensagemEntrada:
    canal: str
    id_externo: str          # id da mensagem no canal (usado no dedup)
    lead_id: str             # quem mandou (número, chat_id...)
    tipo: str                # "texto" | "audio" | "nao_suportado"
    texto: str = ""
    id_midia: str = ""       # áudio: id para baixar
    mime: str = ""
    tipo_original: str = ""  # tipo cru do canal: "text", "image", "sticker"...
    id_canal: str = ""       # conta da LOJA que recebeu (phone_number_id, id do bot)
    hora: int = 0            # timestamp da mensagem


class Canal(ABC):
    nome = ""
    duracao_digitando = 20.0   # por quanto tempo o "digitando..." fica aceso
    respiro_s = 1.0            # pausa curta antes de cada bolha
    pausa_entre_bolhas = 2.0

    @abstractmethod
    def ler_webhook(self, payload) -> list[MensagemEntrada]:
        ...

    @abstractmethod
    async def enviar_texto(self, lead_id: str, texto: str) -> bool:
        ...

    @abstractmethod
    async def enviar_midia(self, lead_id: str, url: str) -> bool:
        ...

    async def marcar_lida(self, id_mensagem: str, digitando: bool = False) -> bool:
        return False

    async def digitando(self, lead_id: str) -> None:
        return None

    async def baixar_midia(self, entrada: MensagemEntrada) -> bytes | None:
        return None

    async def enviar_template(self, lead_id: str, nome: str, variaveis: list) -> bool:
        raise NotImplementedError(f"{self.nome}: modelos de mensagem chegam na Etapa 2.")

    def janela_aberta(self, loja_id: int, lead_id: str) -> bool:
        raise NotImplementedError(f"{self.nome}: janela de 24h chega na Etapa 2.")


async def esperar_digitando(canal: Canal, lead_id: str, segundos: float) -> None:
    """Espera mantendo o 'digitando...' aceso (reaciona antes de apagar)."""
    restante = segundos
    while restante > 0:
        await canal.digitando(lead_id)
        passo = min(max(canal.duracao_digitando, 0.5), restante)
        await asyncio.sleep(passo)
        restante -= passo


async def enviar_humanizado(canal: Canal, lead_id: str, texto: str | None,
                            atraso: float = 0.0) -> None:
    """Divide em bolhas e envia uma a uma, com 'digitando...' e pausas."""
    bolhas = dividir_em_bolhas(texto or "")
    if not bolhas:
        return
    if atraso > 0:
        await esperar_digitando(canal, lead_id, atraso)
    for i, bolha in enumerate(bolhas):
        await canal.digitando(lead_id)
        if canal.respiro_s:
            await asyncio.sleep(canal.respiro_s)
        await canal.enviar_texto(lead_id, bolha)
        if i < len(bolhas) - 1 and canal.pausa_entre_bolhas:
            await asyncio.sleep(canal.pausa_entre_bolhas)


async def enviar_resultado(canal: Canal, lead_id: str, resultado, atraso: float = 0.0) -> None:
    """Envia o resultado de um turno: texto em bolhas, depois as mídias."""
    if getattr(resultado, "silenciado", False):
        return
    await enviar_humanizado(canal, lead_id, resultado.texto, atraso)
    for url in resultado.midias or []:
        await canal.enviar_midia(lead_id, url)

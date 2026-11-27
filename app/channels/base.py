"""
Contrato único dos canais (Etapa 1, Bloco 4 - item 1.7; Etapa 2, Bloco 1).

Todo canal (WhatsApp, Telegram, simulador e, na Etapa 3, Instagram) sabe:
  - ler_webhook(payload)  -> lista de MensagemEntrada (várias por pacote)
  - enviar_texto / enviar_midia
  - marcar_lida / digitando (quando o canal tiver)
  - janela_aberta(loja_id, lead_id, agora): regra única em app/janela.py
  - enviar_template(lead_id, modelo, valores): só canais com modelos (WhatsApp)
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from app import janela as _janela
from app.humanizador import dividir_em_bolhas
from app.resultado_envio import ResultadoEnvio  # noqa: F401  (reexportado)


@dataclass(frozen=True)
class MensagemEntrada:
    canal: str
    id_externo: str          # id da mensagem no canal (usado no dedup)
    lead_id: str             # quem mandou (número, chat_id...)
    tipo: str                # "texto" | "audio" | "imagem" (L5) | "nao_suportado"
    texto: str = ""          # imagem: a legenda (pode vir vazia)
    id_midia: str = ""       # áudio e imagem: id para baixar
    mime: str = ""
    tipo_original: str = ""  # tipo cru do canal: "text", "image", "sticker"...
    id_canal: str = ""       # conta da LOJA que recebeu (phone_number_id, id do bot)
    hora: int = 0            # timestamp da mensagem
    conteudo: bytes = b""    # L5, só no simulador: a imagem já vem junto (nunca é guardada)
    tamanho: int = 0         # N2: bytes da mídia, quando o canal informa (checa o limite antes de baixar)
    duracao: int = 0         # N2: segundos do áudio, quando o canal informa
    nome_perfil: str = ""    # RG1: nome do perfil do WhatsApp (contacts[].profile.name), se veio


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

    async def enviar_foto(self, lead_id: str, loja_id: int, ref: str) -> bool:
        """Maratona Fotos: manda UMA foto do depósito. Padrão: pelo endereço https público
        (só a tomada nuvem tem); sem endereço, é falha (o canal não tem como mandar)."""
        from app import fotos
        url = fotos.endereco_publico(loja_id, ref)
        if not url:
            return False
        return await self.enviar_midia(lead_id, url)

    async def marcar_lida(self, id_mensagem: str, digitando: bool = False) -> bool:
        return False

    async def digitando(self, lead_id: str) -> None:
        return None

    async def baixar_midia(self, entrada: MensagemEntrada) -> bytes | None:
        return None

    async def enviar_template(self, lead_id: str, modelo, valores: dict) -> ResultadoEnvio:
        raise NotImplementedError(
            f"{self.nome}: este canal não usa modelos de mensagem (texto livre sempre).")

    def janela_aberta(self, loja_id: int, lead_id: str, agora: datetime) -> bool:
        return _janela.janela_aberta(loja_id, lead_id, self.nome, agora)


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


async def enviar_resultado(canal: Canal, lead_id: str, resultado, atraso: float = 0.0, *,
                           loja_id: int) -> list[str]:
    """Envia o resultado de um turno. Maratona Fotos: primeiro as fotos (do depósito), depois o
    texto em bolhas; se alguma foto falhar, a trava de app/envio_fotos.py corrige o texto e abre
    o chamado. Devolve as fotos que falharam."""
    if getattr(resultado, "silenciado", False):
        return []
    from app.envio_fotos import enviar_fotos_e_texto
    refs = list(resultado.midias or [])
    if refs and atraso > 0:
        await esperar_digitando(canal, lead_id, atraso)
        atraso = 0.0

    async def _foto(ref: str) -> bool:
        return await canal.enviar_foto(lead_id, loja_id, ref)

    async def _texto(texto: str) -> None:
        await enviar_humanizado(canal, lead_id, texto, atraso)

    return await enviar_fotos_e_texto(loja_id=loja_id, lead_id=lead_id, texto=resultado.texto,
                                      refs=refs, enviar_foto=_foto, enviar_texto=_texto)

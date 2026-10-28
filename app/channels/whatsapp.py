"""Canal WhatsApp (Cloud API da Meta), no contrato de app/channels/base.py.

Revisão da Etapa 1: o canal sabe de qual loja é (CanalWhatsApp(loja_id)),
e todo envio sai pelo número dessa loja. Para só LER o webhook, não
precisa de loja: a loja é descoberta depois, pelo phone_number_id.
"""
from __future__ import annotations

from app.channels.base import Canal, MensagemEntrada
from app.chaves import exigir_loja
from app.api.enviar_whatsapp import (
    enviar_texto_whatsapp, enviar_foto_whatsapp, marcar_lida_whatsapp,
)

# Tipos que não pedem resposta (reação com emoji, avisos do sistema).
TIPOS_IGNORADOS = {"reaction", "system"}


def _dicts(valor) -> list[dict]:
    return [x for x in valor if isinstance(x, dict)] if isinstance(valor, list) else []


def _inteiro(valor) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return 0


class CanalWhatsApp(Canal):
    nome = "whatsapp"
    duracao_digitando = 20.0   # o indicador da Meta dura até ~25 s

    def __init__(self, loja_id: int | None = None):
        self.loja_id = loja_id

    def _loja(self, loja_id=None) -> int:
        return exigir_loja(loja_id if loja_id is not None else self.loja_id)

    def ler_webhook(self, payload) -> list[MensagemEntrada]:
        """Lê TODAS as mensagens do pacote (a Meta pode mandar várias).
        Status de entrega/leitura e lixo são ignorados."""
        entradas = []
        if not isinstance(payload, dict):
            return entradas
        for entry in _dicts(payload.get("entry")):
            for change in _dicts(entry.get("changes")):
                valor = change.get("value")
                if not isinstance(valor, dict):
                    continue
                metadata = valor.get("metadata") if isinstance(valor.get("metadata"), dict) else {}
                id_canal = metadata.get("phone_number_id") or ""
                for msg in _dicts(valor.get("messages")):
                    entrada = self._converter(msg, id_canal)
                    if entrada:
                        entradas.append(entrada)
        return entradas

    def _converter(self, msg: dict, id_canal: str) -> MensagemEntrada | None:
        id_ext, de, tipo = msg.get("id"), msg.get("from"), msg.get("type")
        if not id_ext or not de or not tipo or tipo in TIPOS_IGNORADOS:
            return None
        comum = dict(canal=self.nome, id_externo=str(id_ext), lead_id=str(de),
                     tipo_original=tipo, id_canal=str(id_canal), hora=_inteiro(msg.get("timestamp")))
        corpo = msg.get(tipo) if isinstance(msg.get(tipo), dict) else {}

        if tipo == "audio":
            id_midia = corpo.get("id")
            if not id_midia:
                return None
            return MensagemEntrada(tipo="audio", id_midia=str(id_midia),
                                   mime=corpo.get("mime_type", ""), **comum)

        texto = ""
        if tipo == "text":
            texto = corpo.get("body", "")
        elif tipo == "button":                       # resposta a botão de template
            texto = corpo.get("text") or corpo.get("payload") or ""
        elif tipo == "interactive":                  # botão / lista interativa
            escolha = corpo.get("button_reply") or corpo.get("list_reply") or {}
            texto = escolha.get("title", "") if isinstance(escolha, dict) else ""
        else:
            return MensagemEntrada(tipo="nao_suportado", **comum)

        texto = str(texto).strip()
        return MensagemEntrada(tipo="texto", texto=texto, **comum) if texto else None

    async def enviar_texto(self, lead_id: str, texto: str) -> bool:
        return await enviar_texto_whatsapp(lead_id, texto, loja_id=self._loja())

    async def enviar_midia(self, lead_id: str, url: str) -> bool:
        return await enviar_foto_whatsapp(lead_id, url, loja_id=self._loja())

    async def marcar_lida(self, id_mensagem: str, digitando: bool = False,
                          loja_id: int | None = None) -> bool:
        return await marcar_lida_whatsapp(id_mensagem, loja_id=self._loja(loja_id),
                                          digitando=digitando)

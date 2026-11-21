"""
Limites de mídia do cliente (Maratona 3, N2 / revisão #4).

Áudio acima de 2 minutos ou 10 MB e foto acima de 10 MB não vão para a IA: o cliente recebe uma
resposta fixa e a conversa registra o que chegou. Quando o canal informa tamanho/duração, a
checagem é feita ANTES de baixar; depois de baixar, o tamanho real é conferido de novo.
"""
LIMITE_AUDIO_BYTES = 10 * 1024 * 1024
LIMITE_AUDIO_SEGUNDOS = 120
LIMITE_FOTO_BYTES = 10 * 1024 * 1024

MENSAGEM_AUDIO_LONGO = ("Esse áudio ficou longo demais para eu ouvir. Pode mandar um áudio mais curto "
                        "(até 2 minutos) ou escrever?")
MENSAGEM_FOTO_GRANDE = "Essa foto veio grande demais para eu abrir. Pode mandar outra, menor?"


class MidiaGrandeDemais(Exception):
    """A mídia passou do limite (tipo: "audio" ou "imagem"). Nada foi mandado para a IA."""

    def __init__(self, tipo: str):
        super().__init__(f"{tipo} acima do limite")
        self.tipo = tipo


def _numero(valor) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def audio_passou_do_limite(tamanho=0, duracao=0) -> bool:
    return _numero(tamanho) > LIMITE_AUDIO_BYTES or _numero(duracao) > LIMITE_AUDIO_SEGUNDOS


def foto_passou_do_limite(tamanho=0) -> bool:
    return _numero(tamanho) > LIMITE_FOTO_BYTES


def conferir_audio(tamanho=0, duracao=0) -> None:
    if audio_passou_do_limite(tamanho, duracao):
        raise MidiaGrandeDemais("audio")


def conferir_foto(tamanho=0) -> None:
    if foto_passou_do_limite(tamanho):
        raise MidiaGrandeDemais("imagem")

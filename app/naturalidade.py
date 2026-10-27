"""Alerta de naturalidade (Bloco 7A).

Frases com cara de sistema não podem chegar ao cliente. Não barramos a
resposta (gerar outra dobraria o custo): o turno avisa no terminal e o
prompt é ajustado. Palavras comuns de carro ("comandos no volante",
"menu da central") ficam de fora de propósito.
"""
import re

_PADROES = [
    r"\bdigite\b",
    r"palavra[- ]chave",
    r"cancelar (a |sua )?inscri\w*",
    r"descadastr\w*",
    r"\btransferindo\b",
    r"\btransferir (voc[eê]|a conversa|o atendimento|seu atendimento)",
    r"vou te desconectar|desconectando",
    r"atendente humano",
    r"encerr\w* (o |este |seu )?atendimento",
]
_REGEX = re.compile("|".join(f"(?:{p})" for p in _PADROES), re.IGNORECASE)


def parece_robotica(texto: str | None) -> str | None:
    """Devolve o trecho com cara de robô, ou None se a frase está natural."""
    if not texto:
        return None
    achado = _REGEX.search(texto)
    return achado.group(0) if achado else None

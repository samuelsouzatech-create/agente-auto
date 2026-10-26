"""Limpeza do texto do Léo antes de enviar ao cliente.

O Gemini às vezes responde com Markdown (**negrito**, listas com *, títulos
com #). Telegram e WhatsApp mostram esses símbolos crus, então limpamos.
O Streamlit não usa esta função (ele entende Markdown).
"""
import re

_MARCADOR = re.compile(r"^(\s*)[*+]\s+", re.M)           # "*   item" -> "- item"
_NEGRITO = re.compile(r"(\*\*|__)(.+?)\1", re.S)          # **texto** -> texto
_ITALICO = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_TITULO = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)          # "## Título" -> "Título"
_LINHAS_VAZIAS = re.compile(r"\n{3,}")


def limpar_markdown(texto: str) -> str:
    if not texto:
        return texto
    t = _MARCADOR.sub(r"\1- ", texto)   # antes do itálico, de propósito
    t = _NEGRITO.sub(r"\2", t)
    t = _ITALICO.sub(r"\1", t)
    t = _TITULO.sub("", t)
    t = _LINHAS_VAZIAS.sub("\n\n", t)
    return t.strip()

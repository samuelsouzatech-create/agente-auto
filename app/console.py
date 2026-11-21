"""
O que aparece no console (Maratona 3, N1 / revisão #2).

Em canal real (WhatsApp, Telegram, Instagram), o console nunca mostra o texto do cliente nem o
número inteiro: só os 4 últimos dígitos. Simulador e bancada continuam mostrando tudo (são
conversas de teste e a saída deles não muda).
Canal desconhecido (ex.: jobs): conta como real se o id parecer telefone (8 dígitos ou mais).
"""
import re

CANAIS_REAIS = frozenset({"whatsapp", "telegram", "instagram"})


def e_canal_real(canal: str | None, lead_id=None) -> bool:
    if canal:
        return str(canal).lower() in CANAIS_REAIS
    return len(re.sub(r"\D", "", str(lead_id or ""))) >= 8


def id_no_console(lead_id, canal: str | None = None) -> str:
    """Número/id do cliente para o console: em canal real, só os 4 últimos dígitos."""
    texto = str(lead_id if lead_id is not None else "")
    if not e_canal_real(canal, texto):
        return texto
    return "****" + texto[-4:]


def texto_no_console(texto, canal: str | None = None, lead_id=None) -> str:
    """Texto do cliente (ou da conversa) para o console: em canal real, só o tamanho."""
    texto = str(texto or "")
    if not e_canal_real(canal, lead_id):
        return texto
    return f"(texto oculto, {len(texto)} caracteres)"

"""
Janela de 24 horas (Etapa 2, Bloco 1).

Conta a partir da ÚLTIMA MENSAGEM DO CLIENTE naquele canal, naquela loja.
Mensagens do Léo, do vendedor ou de modelos NÃO abrem a janela.
Faltando menos de 10 minutos, a janela já conta como fechada, para não
perder a corrida entre a decisão e o envio.

Telegram e simulador não têm janela. Canal desconhecido: fechada (seguro).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from banco import conectar
from app.chaves import exigir_loja
from app.relogio import do_banco

DURACAO_JANELA = timedelta(hours=24)
MARGEM_SEGURANCA = timedelta(minutes=10)
CANAIS_COM_JANELA = frozenset({"whatsapp", "instagram"})
CANAIS_SEM_JANELA = frozenset({"telegram", "simulador"})


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def ultima_mensagem_do_cliente(loja_id, lead_id: str, canal: str) -> datetime | None:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT criado_em FROM mensagens "
            "WHERE loja_id = ? AND lead_id = ? AND canal = ? AND direcao = 'cliente' "
            "ORDER BY criado_em DESC, id DESC LIMIT 1",
            (loja_id, str(lead_id), canal),
        ).fetchone()
    finally:
        conexao.close()
    return do_banco(linha["criado_em"]) if linha and linha["criado_em"] else None


def janela_fecha_em(loja_id, lead_id: str, canal: str) -> datetime | None:
    ultima = ultima_mensagem_do_cliente(loja_id, lead_id, canal)
    return ultima + DURACAO_JANELA if ultima else None


def janela_aberta(loja_id, lead_id: str, canal: str, agora: datetime) -> bool:
    loja_id = exigir_loja(loja_id)
    if canal in CANAIS_SEM_JANELA:
        return True
    if canal not in CANAIS_COM_JANELA:
        return False
    fecha = janela_fecha_em(loja_id, lead_id, canal)
    return fecha is not None and _utc(agora) < fecha - MARGEM_SEGURANCA

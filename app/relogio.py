"""
Relógio do sistema (Etapa 1, Bloco 7B). Tudo que depende de hora passa por aqui.

O banco guarda horas em UTC ("AAAA-MM-DD HH:MM:SS", o CURRENT_TIMESTAMP do
SQLite). A loja vive no fuso dela (config "fuso"). As funções recebem um
'agora' para os testes adiantarem o relógio sem esperar de verdade.
A Etapa 2 (remarketing) usa as mesmas funções com o horário de envio.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

FORMATO_BANCO = "%Y-%m-%d %H:%M:%S"
FUSO_PADRAO = "America/Recife"
HORARIO_HUMANO = "atendimento.horario_humano"
DIAS_HUMANO = "atendimento.dias_humano"


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _utc(dt: datetime) -> datetime:
    """Sem fuso = já é UTC (é como o banco guarda)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def para_banco(dt: datetime) -> str:
    return _utc(dt).strftime(FORMATO_BANCO)


def do_banco(texto) -> datetime:
    return datetime.strptime(str(texto)[:19], FORMATO_BANCO).replace(tzinfo=timezone.utc)


def fuso(loja) -> ZoneInfo:
    return ZoneInfo(loja.get("fuso") or FUSO_PADRAO)


def hora_local(loja, dt: datetime) -> datetime:
    return _utc(dt).astimezone(fuso(loja))


def dia_local(loja, dt: datetime) -> date:
    return hora_local(loja, dt).date()


def _dia(valor) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor).strip()[:10])


def limites_do_dia_em_utc(nome_fuso: str, dia) -> tuple[str, str]:
    """Começo e fim (em UTC, formato do banco) de um dia no fuso da loja."""
    z = ZoneInfo(nome_fuso or FUSO_PADRAO)
    d = _dia(dia)
    inicio = datetime.combine(d, time(0), tzinfo=z)
    fim = datetime.combine(d + timedelta(days=1), time(0), tzinfo=z)
    return para_banco(inicio), para_banco(fim)


def faixa(texto: str) -> tuple[time, time]:
    inicio, fim = str(texto).split("-")
    return time.fromisoformat(inicio), time.fromisoformat(fim)


def no_horario(loja, dt: datetime, chave_horario: str = HORARIO_HUMANO,
               chave_dias: str = DIAS_HUMANO) -> bool:
    local = hora_local(loja, dt)
    inicio, fim = faixa(loja.get(chave_horario))
    return local.weekday() in (loja.get(chave_dias) or []) and inicio <= local.time() < fim


def abertura_do_dia(loja, dt: datetime, chave_horario: str = HORARIO_HUMANO) -> datetime:
    """Hora (UTC) em que o expediente de hoje começou, no fuso da loja."""
    local = hora_local(loja, dt)
    inicio, _ = faixa(loja.get(chave_horario))
    return datetime.combine(local.date(), inicio, tzinfo=fuso(loja)).astimezone(timezone.utc)


def minutos_no_expediente(loja, desde: datetime, agora: datetime,
                          chave_horario: str = HORARIO_HUMANO) -> int:
    """Minutos de espera contados só a partir da abertura de hoje.
    Lead que chamou às 23h: às 9h05 conta 5 minutos, e não 10 horas."""
    inicio = max(_utc(desde), abertura_do_dia(loja, agora, chave_horario))
    return max(0, int((_utc(agora) - inicio).total_seconds() // 60))

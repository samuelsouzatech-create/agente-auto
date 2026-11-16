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


HORARIO_SEMANA = "atendimento.horario_semana"
NOMES_DIAS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
DIAS_COMPLETOS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
                  "sexta-feira", "sábado", "domingo")


# ------------------------------------------------------------ H13: horário por dia
# Fonte única do horário da loja: o Léo, os avisos, o painel, a API e o
# remarketing perguntam AQUI se a loja está aberta, quando abre e como
# descrever o horário. Formato novo: atendimento.horario_semana =
# {"0": "08:00-18:00", ..., "5": "08:00-13:00"} (0 = segunda; dia ausente =
# fechado). Sem ele, vale o formato antigo (um horário + lista de dias).

def horario_do_dia(loja, dia: int):
    """("08:00", "13:00") do dia (0 = segunda), ou None se a loja não abre."""
    semana = loja.get(HORARIO_SEMANA)
    if isinstance(semana, dict) and semana:
        texto = semana.get(str(dia)) or semana.get(dia)
    else:
        texto = loja.get(HORARIO_HUMANO) if dia in (loja.get(DIAS_HUMANO) or []) else None
    if not texto or "-" not in str(texto):
        return None
    inicio, fim = str(texto).split("-", 1)
    return inicio.strip(), fim.strip()


def _faixa_do_dia(loja, dia: int):
    h = horario_do_dia(loja, dia)
    if h is None:
        return None
    return time.fromisoformat(h[0]), time.fromisoformat(h[1])


def no_horario(loja, dt: datetime, chave_horario: str = HORARIO_HUMANO,
               chave_dias: str = DIAS_HUMANO) -> bool:
    local = hora_local(loja, dt)
    if (chave_horario, chave_dias) != (HORARIO_HUMANO, DIAS_HUMANO):
        inicio, fim = faixa(loja.get(chave_horario))
        return local.weekday() in (loja.get(chave_dias) or []) and inicio <= local.time() < fim
    faixa_hoje = _faixa_do_dia(loja, local.weekday())
    return faixa_hoje is not None and faixa_hoje[0] <= local.time() < faixa_hoje[1]


def abertura_do_dia(loja, dt: datetime, chave_horario: str = HORARIO_HUMANO) -> datetime:
    """Hora (UTC) em que o expediente de hoje começou, no fuso da loja.
    Dia fechado: devolve o próprio 'dt' (nenhum minuto de expediente hoje).
    Espera que atravessa a noite conta da abertura de hoje (lacuna aceita no H13)."""
    local = hora_local(loja, dt)
    if chave_horario != HORARIO_HUMANO:
        inicio, _ = faixa(loja.get(chave_horario))
    else:
        faixa_hoje = _faixa_do_dia(loja, local.weekday())
        if faixa_hoje is None:
            return _utc(dt)
        inicio = faixa_hoje[0]
    return datetime.combine(local.date(), inicio, tzinfo=fuso(loja)).astimezone(timezone.utc)


def fechamento_do_dia(loja, dt: datetime, chave_horario: str = HORARIO_HUMANO) -> datetime:
    """H14: hora (UTC) em que o expediente de hoje termina, no fuso da loja.
    Dia fechado: devolve o próprio 'dt' (nenhum minuto de expediente hoje)."""
    local = hora_local(loja, dt)
    if chave_horario != HORARIO_HUMANO:
        _, fim = faixa(loja.get(chave_horario))
    else:
        faixa_hoje = _faixa_do_dia(loja, local.weekday())
        if faixa_hoje is None:
            return _utc(dt)
        fim = faixa_hoje[1]
    return datetime.combine(local.date(), fim, tzinfo=fuso(loja)).astimezone(timezone.utc)


def minutos_no_expediente(loja, desde: datetime, agora: datetime,
                          chave_horario: str = HORARIO_HUMANO) -> int:
    """Minutos de espera contados só DENTRO do expediente de hoje:
    da abertura de hoje (ou da chegada) até o fechamento de hoje (ou agora).
    Lead que chamou às 23h: às 9h05 conta 5 minutos, e não 10 horas.
    H14: chegou 17:50, loja fecha 18:00, olhou às 21:00 = 10 minutos, não 190."""
    inicio = max(_utc(desde), abertura_do_dia(loja, agora, chave_horario))
    fim = min(_utc(agora), fechamento_do_dia(loja, agora, chave_horario))
    return max(0, int((fim - inicio).total_seconds() // 60))


def proxima_abertura_da_loja(loja, dt: datetime):
    """Próxima vez (UTC) que a loja abre depois de 'dt'; None se nunca abre."""
    local = hora_local(loja, dt)
    for d in range(8):
        dia = local.date() + timedelta(days=d)
        faixa_dia = _faixa_do_dia(loja, dia.weekday())
        if faixa_dia is None:
            continue
        abre = datetime.combine(dia, faixa_dia[0], tzinfo=fuso(loja))
        if abre > local:
            return abre.astimezone(timezone.utc)
    return None


def status_agora(loja, dt: datetime) -> str:
    """Status pronto para o Léo repetir (ele não faz conta de horário):
    "Agora a loja está ABERTA até 13:00." ou
    "Agora a loja está FECHADA; abre amanhã, sábado, às 08:00."."""
    local = hora_local(loja, dt)
    hoje = _faixa_do_dia(loja, local.weekday())
    if hoje is not None and hoje[0] <= local.time() < hoje[1]:
        return f"Agora a loja está ABERTA até {hoje[1]:%H:%M}."
    abre = proxima_abertura_da_loja(loja, dt)
    if abre is None:
        return "Agora a loja está FECHADA."
    abre = abre.astimezone(fuso(loja))
    dias = (abre.date() - local.date()).days
    nome = DIAS_COMPLETOS[abre.weekday()]
    hora = f"{abre:%H:%M}"
    if dias == 0:
        quando = f"hoje, às {hora}"
    elif dias == 1:
        quando = f"amanhã, {nome}, às {hora}"
    else:
        artigo = "no" if abre.weekday() >= 5 else "na"
        quando = f"{artigo} {nome}, às {hora}"
    return f"Agora a loja está FECHADA; abre {quando}."


def descrever_horarios(loja) -> str:
    """Texto único do horário, para o Léo, as telas e a API:
    "de segunda a sexta, das 08:00 às 18:00; sábado, das 08:00 às 13:00; domingo, fechado"."""
    dias = [horario_do_dia(loja, d) for d in range(7)]
    if not any(dias):
        return ""
    grupos = []
    for d, h in enumerate(dias):
        if grupos and grupos[-1][2] == h:
            grupos[-1][1] = d
        else:
            grupos.append([d, d, h])
    partes = []
    for primeiro, ultimo, h in grupos:
        if primeiro == ultimo:
            nome = NOMES_DIAS[primeiro]
        elif ultimo == primeiro + 1:
            nome = f"{NOMES_DIAS[primeiro]} e {NOMES_DIAS[ultimo]}"
        else:
            nome = f"de {NOMES_DIAS[primeiro]} a {NOMES_DIAS[ultimo]}"
        partes.append(f"{nome}, das {h[0]} às {h[1]}" if h else f"{nome}, fechado")
    return "; ".join(partes)


texto_do_horario = descrever_horarios   # nome usado nas decisões do H13


def horario_da_semana(loja) -> list[dict]:
    """Os 7 dias para a API (/auth/eu): dia, dia_texto, abre, fecha, fechado."""
    saida = []
    for d in range(7):
        h = horario_do_dia(loja, d)
        saida.append({"dia": d, "dia_texto": DIAS_COMPLETOS[d].capitalize(),
                      "abre": h[0] if h else None, "fecha": h[1] if h else None,
                      "fechado": h is None})
    return saida

# ------------------------------------------------------------ H14: horário marcado
def conferir_horario_marcado(loja, dia, hora: time, duracao_min: int = 0):
    """H14: None se 'hora' (no fuso da loja) cabe no expediente daquele dia,
    contando a duração (a visita precisa TERMINAR até o fechamento).
    Senão, devolve o motivo pronto, em português, com o horário certo do dia."""
    d = _dia(dia)
    quando = f"{DIAS_COMPLETOS[d.weekday()]}, {d:%d/%m}"
    faixa_dia = _faixa_do_dia(loja, d.weekday())
    if faixa_dia is None:
        return f"{quando}: a loja fica fechada"
    abre, fecha = faixa_dia
    horario = f"a loja abre das {abre:%H:%M} às {fecha:%H:%M}"
    if hora < abre or hora >= fecha:
        return f"{quando}: {horario}"
    ultimo = (datetime.combine(d, fecha) - timedelta(minutes=duracao_min)).time()
    if hora > ultimo:
        return (f"{quando}: {horario}; como leva {duracao_min} minutos, "
                f"o último horário para começar é {ultimo:%H:%M}")
    return None

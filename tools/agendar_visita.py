"""
Agenda visita, test-drive ou ligação com vendedor.

H14: só dentro do expediente do dia. O Léo passa o dia e a hora como o
cliente falou ("sábado 10h", "12/11 às 15h"); o CÓDIGO entende o dia, faz
a conta da data e confere com app/relogio.py (função única de horário).
Fora do expediente, horário que já passou, ou se faltar dia ou hora:
NÃO agenda e devolve ao Léo o horário certo, para ele oferecer outro.
"""
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from banco import conectar
from app import relogio
from app.lojas import carregar_loja

# Regra de produto (H14): quanto tempo cada tipo ocupa. Visita e test-drive
# precisam TERMINAR até o fechamento. Não há campo de configuração para isso.
DURACAO_MIN = {"visita": 30, "test-drive": 30, "ligacao": 0}
DURACAO_PADRAO = 30
_DIAS = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3,
         "sexta": 4, "sabado": 5, "domingo": 6}


def _normal(texto):
    t = unicodedata.normalize("NFKD", str(texto).lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _data(ano, mes, dia):
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def entender_hora(texto):
    """'15h', '10h30', '10:30', '14 horas', 'às 14', '3 da tarde' -> time. Senão None."""
    t = _normal(texto)
    m = (re.search(r"\b([01]?\d|2[0-3])\s*(?:h|:)\s*([0-5]\d)?", t)
         or re.search(r"\b([01]?\d|2[0-3])\s*horas?\b()", t)
         or re.search(r"\bas\s+([01]?\d|2[0-3])\b()(?!\s*[/:-])", t)
         or re.search(r"\b([01]?\d)\s+da\s+(?:manha|tarde|noite)\b()", t))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if h < 12 and re.search(r"\bda\s+(?:tarde|noite)\b", t):
        h += 12
    return time(h, mi)


def entender_dia(texto, hoje, hora=None, agora_hora=None):
    """'AAAA-MM-DD', 'DD/MM', 'hoje', 'amanhã', 'depois de amanhã' ou dia da
    semana -> a data (a conta é do código, não do Léo). Senão None."""
    t = _normal(texto)
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return _data(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        ano = int(m[3]) if m[3] else hoje.year
        if ano < 100:
            ano += 2000
        d = _data(ano, int(m[2]), int(m[1]))
        if d and not m[3] and d < hoje:
            d = _data(ano + 1, int(m[2]), int(m[1]))
        return d
    if "depois de amanha" in t:
        return hoje + timedelta(days=2)
    if re.search(r"\bamanha\b", t):
        return hoje + timedelta(days=1)
    if re.search(r"\bhoje\b", t):
        return hoje
    for nome, n in _DIAS.items():
        if re.search(rf"\b{nome}\b", t):
            d = hoje + timedelta(days=(n - hoje.weekday()) % 7)
            if d == hoje and hora is not None and agora_hora is not None and hora <= agora_hora:
                d += timedelta(days=7)
            return d
    return None


def _recusa(loja, tipo, dia, hora, agora):
    """Texto 'NÃO AGENDADO: ...' para o Léo, ou None se pode agendar."""
    horario = relogio.descrever_horarios(loja)
    fim = f" Horário da loja: {horario}." if horario else ""
    oferecer = (" Não diga que agendou. Explique ao cliente o horário desse dia e ofereça "
                "outro dia e hora dentro do expediente; quando ele escolher, chame "
                "agendar_visita de novo.")
    if dia is None or hora is None:
        falta = ("o dia e a hora" if dia is None and hora is None
                 else "o dia" if dia is None else "a hora")
        return (f"NÃO AGENDADO: faltou {falta}. Não diga que agendou. Pergunte ao cliente "
                f"o dia e a hora (ex.: sábado às 10h) e chame agendar_visita de novo.{fim}")
    if datetime.combine(dia, hora, tzinfo=agora.tzinfo) <= agora:
        return f"NÃO AGENDADO: esse horário já passou.{fim}{oferecer}"
    motivo = relogio.conferir_horario_marcado(loja, dia, hora, DURACAO_MIN.get(tipo, DURACAO_PADRAO))
    if motivo:
        return f"NÃO AGENDADO: {motivo}.{fim}{oferecer}"
    return None


@tool
def agendar_visita(nome_cliente: str, tipo: str, data_hora: str,
                   lead_id: Annotated[str, InjectedToolArg] = "",
                   *, loja_id: Annotated[int, InjectedToolArg]) -> str:
    """Agenda uma visita, test-drive ou ligação com vendedor.
    Se o cliente já tiver um agendamento desse tipo, ATUALIZA o horário
    (o cliente pode remarcar). Não cria agendamentos duplicados.
    O sistema confere se o dia e a hora cabem no horário da loja. Se a
    resposta começar com "NÃO AGENDADO", nada foi marcado.

    Parâmetros:
    - nome_cliente: nome de quem está agendando
    - tipo: "visita", "test-drive" ou "ligacao"
    - data_hora: dia e hora como o cliente pediu (ex: "sábado 10h", "12/10 às 15h", "amanhã às 9h")
    """
    loja = carregar_loja(loja_id)
    agora = relogio.hora_local(loja, relogio.agora_utc())
    hora = entender_hora(data_hora)
    dia = entender_dia(data_hora, agora.date(), hora, agora.time())
    recusa = _recusa(loja, tipo, dia, hora, agora)
    if recusa:
        return recusa
    conferido = f" Dia conferido: {relogio.DIAS_COMPLETOS[dia.weekday()]}, {dia:%d/%m}, às {hora:%H:%M}."

    conexao = conectar()
    try:
        if lead_id:
            existente = conexao.execute(
                "SELECT id FROM agendamentos WHERE loja_id = ? AND lead_id = ? AND tipo = ?",
                (loja_id, lead_id, tipo),
            ).fetchone()
            if existente:
                conexao.execute(
                    "UPDATE agendamentos SET nome_cliente = ?, data_hora = ?, status = 'agendado' WHERE id = ?",
                    (nome_cliente, data_hora, existente["id"]),
                )
                conexao.commit()
                return f"Agendamento atualizado: {tipo} para {nome_cliente} em {data_hora}.{conferido}"

        conexao.execute(
            "INSERT INTO agendamentos (loja_id, lead_id, nome_cliente, tipo, data_hora) VALUES (?, ?, ?, ?, ?)",
            (loja_id, lead_id, nome_cliente, tipo, data_hora),
        )
        conexao.commit()
    finally:
        conexao.close()
    return f"Agendamento confirmado: {tipo} para {nome_cliente} em {data_hora}.{conferido}"

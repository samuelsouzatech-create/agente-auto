"""
Agenda visita, test-drive ou ligação com vendedor.

H14: só dentro do expediente do dia. O Léo passa o dia e a hora como o
cliente falou; o CÓDIGO entende, faz a conta da data e confere com
app/relogio.py (função única de horário).
- Fora do expediente, horário que já passou, ou faltou dia/hora: NÃO agenda
  e devolve ao Léo o horário certo, para ele oferecer outro.
- Na dúvida ("às 3", "dia 15" sem mês, o dia de hoje pelo nome,
  "semana que vem", "próximo"): NÃO agenda; o Léo pergunta ao cliente.
- Grava a data já resolvida ("sábado, 14/11, às 10:00"), nunca "amanhã".
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
# precisam TERMINAR até o fechamento. Sem campo de configuração (lacuna no contrato).
DURACAO_MIN = {"visita": 30, "test-drive": 30, "ligacao": 0}
DURACAO_PADRAO = 30
# 1h a 7h sem "da manhã/da tarde": pode ser 13h a 19h. Na dúvida, pergunta.
HORA_AMBIGUA = range(1, 8)
_DIAS = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3,
         "sexta": 4, "sabado": 5, "domingo": 6}
_MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
          "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11,
          "dezembro": 12}
_PERIODO = re.compile(r"\b(?:da|de|a)\s+(manha|tarde|noite)\b")


def _normal(texto):
    t = unicodedata.normalize("NFKD", str(texto).lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"(\d)t(\d)", r"\1 \2", t)        # 2026-11-14T10:00


def _data(ano, mes, dia):
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def _data_ou_duvida(d):
    return (d, None) if d else (None, "essa data não existe; qual é o dia certo?")


def entender_hora(texto):
    """-> (hora, dúvida). Aceita '15h', '10h30', '10:30', '14 horas', 'às 14',
    '3 da tarde'. Sem hora: (None, None)."""
    t = _normal(texto)
    m = (re.search(r"\b([01]?\d|2[0-3])\s*(?:h|:)\s*([0-5]\d)?", t)
         or re.search(r"\b([01]?\d|2[0-3])\s*horas?\b()", t)
         or re.search(r"\bas\s+([01]?\d|2[0-3])\b()(?!\s*[/:-])", t)
         or re.search(r"\b([01]?\d)\s+(?:da|de|a)\s+(?:manha|tarde|noite)\b()", t))
    if not m:
        return None, None
    bruto = m.group(1)
    h, mi = int(bruto), int(m.group(2) or 0)
    periodo = _PERIODO.search(t)
    if periodo:
        if periodo.group(1) != "manha" and h < 12:
            h += 12
    elif h in HORA_AMBIGUA and not bruto.startswith("0"):
        return None, f"às {h} da manhã ou às {h + 12}h (da tarde)?"
    return time(h, mi), None


def entender_dia(texto, agora):
    """-> (dia, dúvida). A conta da data é do código, não do Léo.
    'agora' é a hora local da loja. Sem dia: (None, None)."""
    t = _normal(texto)
    hoje = agora.date()
    if re.search(r"semana que vem|proxima semana|\bque vem\b|\bproxim[oa]\b", t):
        return None, ("qual a data exata (dia e mês)? 'semana que vem' ou 'próximo' "
                      "pode querer dizer mais de um dia")
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return _data_ou_duvida(_data(int(m[1]), int(m[2]), int(m[3])))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        ano = int(m[3]) if m[3] else hoje.year
        if ano < 100:
            ano += 2000
        d = _data(ano, int(m[2]), int(m[1]))
        if d and not m[3] and d < hoje:
            d = _data(ano + 1, int(m[2]), int(m[1]))
        return _data_ou_duvida(d)
    m = re.search(r"\b(\d{1,2})\s+de\s+(" + "|".join(_MESES) + r")\b", t)
    if m:
        d = _data(hoje.year, _MESES[m[2]], int(m[1]))
        if d and d < hoje:
            d = _data(hoje.year + 1, _MESES[m[2]], int(m[1]))
        return _data_ou_duvida(d)
    m = re.search(r"\bdia\s+(\d{1,2})\b", t)
    if m:
        return None, f"dia {int(m[1])} de qual mês?"
    if "depois de amanha" in t:
        return hoje + timedelta(days=2), None
    if re.search(r"\bamanha\b", t):
        return hoje + timedelta(days=1), None
    if re.search(r"\bhoje\b", t):
        return hoje, None
    nomes = [n for n in _DIAS if re.search(rf"\b{n}\b", t)]
    if len(nomes) > 1:
        return None, "qual dia: " + " ou ".join(nomes) + "?"
    if nomes:
        n = _DIAS[nomes[0]]
        d = hoje + timedelta(days=(n - hoje.weekday()) % 7)
        if d == hoje:
            prox = hoje + timedelta(days=7)
            return None, (f"hoje ({hoje:%d/%m}) ou no próximo "
                          f"{relogio.DIAS_COMPLETOS[n]} ({prox:%d/%m})?")
        return d, None
    return None, None


def _quando(dia, hora):
    return f"{relogio.DIAS_COMPLETOS[dia.weekday()]}, {dia:%d/%m}, às {hora:%H:%M}"


def _avaliar(loja, tipo, texto, agora):
    """-> (recusa, quando). recusa = 'NÃO AGENDADO: ...' para o Léo, ou None."""
    hora, duvida_hora = entender_hora(texto)
    dia, duvida_dia = entender_dia(texto, agora)
    horario = relogio.descrever_horarios(loja)
    fim = f" Horário da loja: {horario}." if horario else ""
    outro = (" Não diga que agendou. Explique ao cliente o horário desse dia e ofereça "
             "outro dia e hora dentro do expediente; quando ele escolher, chame "
             "agendar_visita de novo.")
    if dia is not None:
        fechado = relogio.conferir_horario_marcado(loja, dia, time(0, 0))
        if fechado and fechado.endswith("fechada"):
            return f"NÃO AGENDADO: {fechado}.{fim}{outro}", None
    duvidas = [d for d in (duvida_dia, duvida_hora) if d]
    if duvidas:
        return ("NÃO AGENDADO: preciso confirmar com o cliente: " + " ".join(duvidas)
                + " Não diga que agendou e não escolha por ele: pergunte e, com a "
                  "resposta, chame agendar_visita de novo." + fim), None
    if dia is None or hora is None:
        falta = ("o dia e a hora" if dia is None and hora is None
                 else "o dia" if dia is None else "a hora")
        return (f"NÃO AGENDADO: faltou {falta}. Não diga que agendou. Pergunte ao cliente "
                f"o dia e a hora (ex.: sábado às 10h) e chame agendar_visita de novo.{fim}"), None
    if datetime.combine(dia, hora, tzinfo=agora.tzinfo) <= agora:
        return f"NÃO AGENDADO: esse horário já passou.{fim}{outro}", None
    motivo = relogio.conferir_horario_marcado(loja, dia, hora, DURACAO_MIN.get(tipo, DURACAO_PADRAO))
    if motivo:
        return f"NÃO AGENDADO: {motivo}.{fim}{outro}", None
    return None, _quando(dia, hora)


@tool
def agendar_visita(nome_cliente: str, tipo: str, data_hora: str,
                   lead_id: Annotated[str, InjectedToolArg] = "",
                   *, loja_id: Annotated[int, InjectedToolArg]) -> str:
    """Agenda uma visita, test-drive ou ligação com vendedor.
    Se o cliente já tiver um agendamento desse tipo, ATUALIZA o horário
    (o cliente pode remarcar). Não cria agendamentos duplicados.
    O sistema confere se o dia e a hora cabem no horário da loja. Se a
    resposta começar com "NÃO AGENDADO", nada foi marcado: siga a orientação.

    Parâmetros:
    - nome_cliente: nome de quem está agendando
    - tipo: "visita", "test-drive" ou "ligacao"
    - data_hora: dia e hora EXATAMENTE como o cliente falou (ex: "sábado 10h",
      "12/10 às 15h", "amanhã às 9h"). Não converta "às 3" em 15h nem escolha o dia por ele.
    """
    loja = carregar_loja(loja_id)
    agora = relogio.hora_local(loja, relogio.agora_utc())
    recusa, quando = _avaliar(loja, tipo, data_hora, agora)
    if recusa:
        return recusa

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
                    (nome_cliente, quando, existente["id"]),
                )
                conexao.commit()
                return (f"Agendamento atualizado: {tipo} para {nome_cliente} em {quando}. "
                        "Confirme ao cliente exatamente esse dia e hora.")

        conexao.execute(
            "INSERT INTO agendamentos (loja_id, lead_id, nome_cliente, tipo, data_hora) VALUES (?, ?, ?, ?, ?)",
            (loja_id, lead_id, nome_cliente, tipo, quando),
        )
        conexao.commit()
    finally:
        conexao.close()
    return (f"Agendamento confirmado: {tipo} para {nome_cliente} em {quando}. "
            "Confirme ao cliente exatamente esse dia e hora.")

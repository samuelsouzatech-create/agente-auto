"""
Tela Resultado (GET /resultado, C2): números da semana ou do mês, no formato do contrato.

Camada fina sobre app/painel_leitura.resultado_do_periodo (P4 e P7c): todas as
contas são de lá. Aqui só:
- o período: a semana (segunda a domingo) ou o mês que contém 'data'
  (padrão: hoje, no fuso da loja);
- o rótulo pronto ("2 a 8 de novembro", "novembro de 2026");
- os tempos e o "contando desde" no formato do contrato.
Dado inválido: 422 invalido, com o campo. Só lê.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from app.api_painel.erros import ErroApi
from app.api_painel.formato import horario
from app.lojas import carregar_loja
from app.painel_leitura import resultado_do_periodo
from app.relogio import agora_utc, hora_local

SEMANA, MES = "semana", "mes"
VISOES = (SEMANA, MES)
ANO_MINIMO, ANO_MAXIMO = 2000, 2100
MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro")


def periodo_da_visao(visao: str, dia: date) -> tuple:
    if visao == SEMANA:
        inicio = dia - timedelta(days=dia.weekday())
        return inicio, inicio + timedelta(days=6)
    ultimo = calendar.monthrange(dia.year, dia.month)[1]
    return dia.replace(day=1), dia.replace(day=ultimo)


def rotulo_do_periodo(visao: str, inicio: date, fim: date) -> str:
    if visao == MES:
        return f"{MESES[inicio.month - 1]} de {inicio.year}"
    mes_i, mes_f = MESES[inicio.month - 1], MESES[fim.month - 1]
    if inicio.year != fim.year:
        return f"{inicio.day} de {mes_i} de {inicio.year} a {fim.day} de {mes_f} de {fim.year}"
    if inicio.month != fim.month:
        return f"{inicio.day} de {mes_i} a {fim.day} de {mes_f}"
    return f"{inicio.day} a {fim.day} de {mes_f}"


def _dia_pedido(loja, data, agora) -> date:
    if data is None or not str(data).strip():
        return hora_local(loja, agora).date()
    try:
        dia = date.fromisoformat(str(data).strip())
    except ValueError:
        raise ErroApi("invalido", {"data": "Data inválida."}) from None
    if not ANO_MINIMO <= dia.year <= ANO_MAXIMO:
        raise ErroApi("invalido", {"data": f"Escolha uma data entre {ANO_MINIMO} e {ANO_MAXIMO}."})
    return dia


def _tempo(segundos, texto) -> dict:
    return {"segundos": None if segundos is None else float(segundos), "texto": texto}


def montar_resultado(loja_id: int, visao=SEMANA, data=None, agora=None) -> dict:
    visao = str(visao or SEMANA).strip().lower()
    if visao not in VISOES:
        raise ErroApi("invalido", {"visao": "Escolha semana ou mês."})
    agora = agora or agora_utc()
    loja = carregar_loja(loja_id)
    inicio, fim = periodo_da_visao(visao, _dia_pedido(loja, data, agora))
    r = resultado_do_periodo(loja_id, inicio, fim)
    return {
        "periodo": {"inicio": r["inicio"], "fim": r["fim"],
                    "rotulo": rotulo_do_periodo(visao, inicio, fim)},
        "conversas_atendidas": r["conversas_atendidas"],
        "fora_do_horario": r["fora_do_horario"],
        "primeira_resposta": _tempo(r["primeira_resposta_s"], r["primeira_resposta_texto"]),
        "ate_vendedor_assumir": _tempo(r["ate_vendedor_assumir_s"], r["ate_vendedor_assumir_texto"]),
        "passados_ao_vendedor": r["passados_ao_vendedor"],
        "visitas_marcadas": r["visitas_marcadas"],
        "vendas_registradas": r["vendas_registradas"],
        "funil": r["funil"],
        "por_dia": r["por_dia"],
        "dados_de_teste": r["dados_de_teste"],
        "contando_desde": horario(loja, r["contando_desde"], agora),
    }

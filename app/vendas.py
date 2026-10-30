"""
Vendas da loja (Etapa 2, Bloco 5A): o botão "Vendido".

Fonte de acontecimentos do segmento de veículos. Cada venda agenda a régua
de pós-venda da loja (app/regua.py). O motor não conhece carro: quem diz as
datas (venda e fim do financiamento) é este arquivo.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime

from banco import conectar
from app import regua
from app.chaves import exigir_loja
from app.lojas import carregar_loja, modulo_ativo
from app.relogio import agora_utc, dia_local

FORMAS = ("avista", "financiado")
EVENTO = "venda"
MAX_MESES = 120


class VendaInvalida(ValueError):
    pass


def somar_meses(dia: date, meses: int) -> date:
    total = dia.month - 1 + meses
    ano, mes = dia.year + total // 12, total % 12 + 1
    return date(ano, mes, min(dia.day, calendar.monthrange(ano, mes)[1]))


def datas_da_venda(data_venda: date, forma: str, meses: int | None) -> dict:
    fim = somar_meses(data_venda, meses) if forma == "financiado" and meses else None
    return {"venda": data_venda, "fim_financiamento": fim}


def _dia(valor) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor).strip()[:10])
    except ValueError:
        raise VendaInvalida("Data da venda inválida.")


def _meses(forma: str, valor) -> int | None:
    if forma == "avista" or valor in (None, "", 0):
        return None
    try:
        meses = int(valor)
    except (TypeError, ValueError):
        raise VendaInvalida("Meses de financiamento precisa ser um número.")
    if not 1 <= meses <= MAX_MESES:
        raise VendaInvalida(f"Meses de financiamento precisa estar entre 1 e {MAX_MESES}.")
    return meses


def _texto_carro(linha) -> str:
    if not linha or not linha["modelo"]:
        return ""
    return f"{linha['marca']} {linha['modelo']} {linha['ano']}"


def registrar_venda(loja_id, lead_id, veiculo_id, data_venda, forma_pagamento, *,
                    meses_financiamento=None, vendedor: str = "", agora: datetime | None = None) -> dict:
    loja_id = exigir_loja(loja_id)
    agora = agora or agora_utc()
    loja = carregar_loja(loja_id)
    lead_id = str(lead_id or "").strip()
    if not lead_id:
        raise VendaInvalida("Venda sem cliente.")
    if forma_pagamento not in FORMAS:
        raise VendaInvalida(f"Forma de pagamento inválida ({', '.join(FORMAS)}).")
    meses = _meses(forma_pagamento, meses_financiamento)
    dia = _dia(data_venda)
    if dia > dia_local(loja, agora):
        raise VendaInvalida("A data da venda não pode ser no futuro.")

    conexao = conectar()
    try:
        carro = conexao.execute(
            "SELECT id, marca, modelo, ano, status FROM estoque WHERE id = ? AND loja_id = ?",
            (veiculo_id, loja_id)).fetchone()
        if carro is None:
            raise VendaInvalida("Este carro não está no estoque desta loja.")
        if carro["status"] == "vendido":
            raise VendaInvalida("Este carro já está como vendido.")
        repetida = conexao.execute(
            "SELECT 1 FROM vendas WHERE loja_id = ? AND lead_id = ? AND veiculo_id = ?",
            (loja_id, lead_id, veiculo_id)).fetchone()
        if repetida:
            raise VendaInvalida("Esta venda já foi registrada.")
        venda_id = conexao.execute(
            "INSERT INTO vendas (loja_id, lead_id, veiculo_id, data_venda, forma_pagamento, "
            "meses_financiamento, vendedor) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (loja_id, lead_id, veiculo_id, dia.isoformat(), forma_pagamento, meses, vendedor)).lastrowid
        conexao.execute("UPDATE estoque SET status = 'vendido' WHERE id = ? AND loja_id = ?",
                        (veiculo_id, loja_id))
        conexao.execute(
            "INSERT INTO resultados (lead_id, loja_id, resultado, motivo, vendedor) "
            "VALUES (?, ?, 'comprou', ?, ?)", (lead_id, loja_id, _texto_carro(carro), vendedor))
        conexao.commit()
    finally:
        conexao.close()

    ligado = modulo_ativo(loja, "pos_venda")
    passos = []
    if ligado:
        passos = regua.agendar(loja_id, lead_id, EVENTO, venda_id,
                               datas=datas_da_venda(dia, forma_pagamento, meses),
                               pagamento=forma_pagamento, inicio=dia, agora=agora)
    return {"venda_id": venda_id, "carro": _texto_carro(carro),
            "pos_venda_ligado": ligado, "pos_venda": passos}


_SELECT = ("SELECT v.*, e.marca, e.modelo, e.ano FROM vendas v "
           "LEFT JOIN estoque e ON e.id = v.veiculo_id AND e.loja_id = v.loja_id ")


def vendas_do_lead(loja_id, lead_id: str) -> list[dict]:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linhas = conexao.execute(_SELECT + "WHERE v.loja_id = ? AND v.lead_id = ? "
                                 "ORDER BY v.data_venda DESC, v.id DESC", (loja_id, lead_id)).fetchall()
    finally:
        conexao.close()
    return [{**dict(l), "carro": _texto_carro(l)} for l in linhas]


def valores_da_venda(loja_id, venda_id: int) -> dict:
    """Variáveis que a venda empresta aos modelos de mensagem."""
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linha = conexao.execute(_SELECT + "WHERE v.loja_id = ? AND v.id = ?", (loja_id, venda_id)).fetchone()
    finally:
        conexao.close()
    return {"carro": _texto_carro(linha)} if linha and _texto_carro(linha) else {}

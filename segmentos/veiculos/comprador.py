"""
Quem já comprou (Etapa 2, Bloco 5B) - pacote do segmento de veículos.

O motor (app/cliente_da_casa.py) chama contexto_do_lead e não sabe o que é
carro. Busca as vendas desta loja pelo MESMO contato e, no WhatsApp, também
pelo telefone normalizado (com ou sem o 9). No Telegram o lead_id é um número
de chat, não telefone: só vale o mesmo contato.
"""
from datetime import date

from banco import conectar
from app.chaves import exigir_loja
from app.telefone import normalizar_telefone_br

CANAIS_COM_TELEFONE = {"whatsapp"}
LIMITE = 3


def _dia(valor):
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


def _detalhe(forma, meses) -> str:
    if forma == "financiado":
        return f"financiado em {meses}x" if meses else "financiado"
    return "à vista" if forma == "avista" else ""


def compras_do_lead(loja_id, lead_id, canal: str = "") -> list[dict]:
    loja_id = exigir_loja(loja_id)
    lead_id = str(lead_id or "").strip()
    if not lead_id:
        return []
    fone = normalizar_telefone_br(lead_id) if canal in CANAIS_COM_TELEFONE else ""
    conexao = conectar()
    try:
        conexao.create_function("fone_br", 1, normalizar_telefone_br)
        linhas = conexao.execute(
            "SELECT v.data_venda, v.forma_pagamento, v.meses_financiamento, "
            "e.marca, e.modelo, e.ano "
            "FROM vendas v LEFT JOIN estoque e ON e.id = v.veiculo_id AND e.loja_id = v.loja_id "
            "WHERE v.loja_id = ? AND (v.lead_id = ? OR (? != '' AND fone_br(v.lead_id) = ?)) "
            "ORDER BY v.data_venda DESC, v.id DESC LIMIT ?",
            (loja_id, lead_id, fone, fone, LIMITE)).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]


def contexto_do_lead(loja_id, lead_id, canal: str = "") -> list[dict]:
    """Gancho do motor: [{"descricao", "data", "detalhe"}], mais recente primeiro."""
    saida = []
    for l in compras_do_lead(loja_id, lead_id, canal):
        partes = [str(p) for p in (l["marca"], l["modelo"], l["ano"]) if p]
        saida.append({
            "descricao": " ".join(partes) or "um carro da loja",
            "data": _dia(l["data_venda"]),
            "detalhe": _detalhe(l["forma_pagamento"], l["meses_financiamento"]),
        })
    return saida

"""
Quem já comprou (Etapa 2, Blocos 5B e 6A) - pacote do segmento de veículos.

O motor (app/cliente_da_casa.py) chama contexto_do_lead e não sabe o que é
carro. Junta duas fontes desta loja:
  - vendas (botão "Vendido"): pelo MESMO contato e, no WhatsApp, pelo telefone
  - compras_anteriores (base importada, Bloco 6A): pelo telefone, só no WhatsApp
No Telegram o lead_id é um número de chat, não telefone: só vale o mesmo contato.
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


def compras_importadas(loja_id, lead_id, canal: str = "") -> list[dict]:
    loja_id = exigir_loja(loja_id)
    if canal not in CANAIS_COM_TELEFONE:
        return []
    fone = normalizar_telefone_br(lead_id)
    if not fone:
        return []
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT descricao, data_compra, forma_pagamento, meses_financiamento "
            "FROM compras_anteriores WHERE loja_id = ? AND telefone = ? "
            "ORDER BY data_compra DESC, id DESC LIMIT ?", (loja_id, fone, LIMITE)).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]


def contexto_do_lead(loja_id, lead_id, canal: str = "") -> list[dict]:
    """Gancho do motor: [{"descricao", "data", "detalhe"}], mais recente primeiro."""
    saida, vistos = [], set()

    def juntar(descricao, data, detalhe):
        chave = (descricao.lower(), data)
        if chave not in vistos:              # mesma compra nas duas fontes: aparece uma vez
            vistos.add(chave)
            saida.append({"descricao": descricao, "data": data, "detalhe": detalhe})

    for l in compras_do_lead(loja_id, lead_id, canal):
        partes = [str(p) for p in (l["marca"], l["modelo"], l["ano"]) if p]
        juntar(" ".join(partes) or "um carro da loja", _dia(l["data_venda"]),
               _detalhe(l["forma_pagamento"], l["meses_financiamento"]))
    for l in compras_importadas(loja_id, lead_id, canal):
        juntar(l["descricao"], _dia(l["data_compra"]),
               _detalhe(l["forma_pagamento"], l["meses_financiamento"]))
    saida.sort(key=lambda c: c["data"] or date.min, reverse=True)
    return saida[:LIMITE]

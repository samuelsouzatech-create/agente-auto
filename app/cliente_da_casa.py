"""
Cliente da casa (Etapa 2, Bloco 5B): este contato já comprou nesta loja?

O motor não conhece carro: pergunta ao pacote do segmento, pelo gancho
opcional segmentos/<segmento>/comprador.py -> contexto_do_lead(loja_id, lead_id, canal).
Segmento sem gancho, ou qualquer falha: segue como lead normal.
Nunca derruba a conversa.
"""
from __future__ import annotations

from app.segmentos import modulo_do_segmento

GANCHO = "comprador"
FUNCAO = "contexto_do_lead"


def compras_do_cliente(loja, lead_id, canal) -> list[dict]:
    lead_id = str(lead_id or "").strip()
    if not lead_id:
        return []
    try:
        segmento = getattr(loja, "segmento", None) or "veiculos"
        modulo = modulo_do_segmento(segmento, GANCHO)
        funcao = getattr(modulo, FUNCAO, None) if modulo else None
        if funcao is None:
            return []
        compras = funcao(loja.id, lead_id, canal or "") or []
        return [c for c in compras if isinstance(c, dict) and c.get("descricao")]
    except Exception as erro:
        print(f"[Agente] Aviso: não consegui ver se o cliente já comprou ({erro!r}). "
              "Segue como lead normal.")
        return []

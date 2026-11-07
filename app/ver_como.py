"""
Leitura da tela "Ver como a loja" (S5): a lista do Atender e o estado da loja.
Sem Streamlit, só lê. loja_id obrigatório. Horário no fuso da loja.
A fila de handoff é buscada UMA vez por tela (não uma por conversa).
"""
from __future__ import annotations

from app.apresentacao import horario_para_tela, nome_do_canal, nomes_dos_clientes
from app.chaves import exigir_loja
from app.estado_loja import situacao_da_loja
from app.handoff import listar_handoffs
from app.lojas import carregar_loja
from app.mensagens import listar_conversas
from app.permissoes import operador_pode_agir

ORDEM_DOS_ESTADOS = {"aguardando_humano": 0, "humano_assumiu": 1, "ativo": 2}


def rotulos_de_estado(nome_agente: str) -> dict:
    return {
        "ativo": f"🤖 {nome_agente} atendendo",
        "aguardando_humano": "🟡 Esperando vendedor",
        "humano_assumiu": "🧑 Com vendedor",
    }


def conversas_para_atender(loja_id, *, agora=None) -> list[dict]:
    """Uma linha por cliente: quem espera vendedor primeiro, depois quem está
    com vendedor, depois o resto; dentro de cada grupo, o mais recente primeiro."""
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    rotulos = rotulos_de_estado(loja.get("nome_agente", "Léo"))

    abertos = {}
    for h in listar_handoffs(loja_id, apenas_abertos=True):
        abertos[h["lead_id"]] = h            # vem do mais antigo: fica o mais novo
    por_lead = {c["lead_id"]: c for c in listar_conversas(loja_id)}
    ids = list(por_lead) + [l for l in abertos if l not in por_lead]
    nomes = nomes_dos_clientes(loja_id, ids)

    saida = []
    for lead_id in ids:
        conversa = por_lead.get(lead_id, {})
        handoff = abertos.get(lead_id) or {}
        estado = handoff.get("estado") or "ativo"
        ultima = conversa.get("ultima_mensagem") or handoff.get("criado_em") or ""
        saida.append({
            "lead_id": lead_id,
            "nome": nomes.get(str(lead_id), "Cliente sem nome"),
            "canal": conversa.get("canal") or "",
            "origem": nome_do_canal(conversa.get("canal")),
            "estado": estado,
            "estado_rotulo": rotulos.get(estado, estado),
            "vendedor": handoff.get("vendedor") if estado == "humano_assumiu" else None,
            "motivo": (handoff.get("motivo") or "").strip(),
            "ultima_iso": str(ultima),
            "ultima": horario_para_tela(loja, ultima, agora=agora) if ultima else "",
        })
    saida.sort(key=lambda c: c["ultima_iso"], reverse=True)
    saida.sort(key=lambda c: ORDEM_DOS_ESTADOS.get(c["estado"], 9))
    return saida


def situacao_para_tela(loja_id) -> dict:
    loja_id = exigir_loja(loja_id)
    return {"rotulo": situacao_da_loja(loja_id)["rotulo"],
            "pode_agir": operador_pode_agir(loja_id)}

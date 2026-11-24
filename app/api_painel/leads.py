"""
Tela Leads (GET /leads, C2): clientes por etapa, no formato do contrato.

Camada fina sobre app/painel_leitura.etapas_dos_leads (P4): etapa, carro, nome,
origem e próximo passo vêm prontos de lá. Aqui só:
- periodo: 7, 30 ou 90 dias (outro valor vira 30; o contrato não prevê 422 aqui);
- busca: até 80 caracteres (o resto é cortado); a busca sem acento é de app/;
- etapa: filtra a lista. A contagem por etapa é do período inteiro (com a busca),
  para as abas de etapa mostrarem quantos há em cada uma;
- paginação (50 por padrão, máximo 100) e o horário no formato {iso, texto}.
Só lê: nada aqui grava no banco.
"""
from __future__ import annotations

import math

from app.painel_leitura import ORDEM_DAS_ETAPAS, ROTULOS_ETAPA, etapas_dos_leads
from app.relogio import agora_utc

PERIODOS = (7, 30, 90)
PERIODO_PADRAO = 30
MAX_BUSCA = 80
TAMANHO_PADRAO, TAMANHO_MAXIMO = 50, 100


def _numero(valor, padrao: int, minimo: int, maximo: int) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        n = padrao
    return max(minimo, min(n, maximo))


def _ultimo_contato(linha: dict):
    iso = linha.get("ultimo_contato_iso")
    if not iso:
        return None
    return {"iso": iso, "texto": linha["ultimo_contato"]}


def _item(linha: dict, resumo: dict | None = None) -> dict:
    extra = resumo or {}
    return {
        "lead": str(linha["lead_id"]),
        "nome": linha["nome"],
        "carro": linha["carro"],
        "origem": linha["origem"],
        "ultimo_contato": _ultimo_contato(linha),
        "etapa": linha["etapa"],
        "etapa_rotulo": linha["etapa_rotulo"],
        "proximo_passo": linha["proximo_passo"],
        "canais": extra.get("canais") or [],                  # v1.3 (IG3)
        "como_chegou": extra.get("como_chegou"),               # v1.3 (IG3)
    }


def _um_cartao_por_cliente(loja_id: int, linhas: list[dict]) -> list[dict]:
    """IG3: a conversa do WhatsApp do mesmo cliente do Instagram não vira outro cartão."""
    from app.instagram_whatsapp import vinculos
    mapa = vinculos(loja_id)
    if not mapa:
        return linhas
    presentes = {str(l["lead_id"]) for l in linhas}
    return [l for l in linhas if mapa.get(str(l["lead_id"])) not in presentes]


def _itens(loja_id: int, linhas: list[dict]) -> list[dict]:
    from app.instagram_whatsapp import resumo_dos_clientes
    resumo = resumo_dos_clientes(loja_id, [l["lead_id"] for l in linhas])
    return [_item(l, resumo.get(str(l["lead_id"]))) for l in linhas]


def montar_leads(loja_id: int, periodo=PERIODO_PADRAO, busca=None, etapa=None,
                 pagina=1, tamanho=TAMANHO_PADRAO, agora=None) -> dict:
    agora = agora or agora_utc()
    dias = periodo if periodo in PERIODOS else PERIODO_PADRAO
    termo = " ".join(str(busca or "").split())[:MAX_BUSCA] or None
    linhas = etapas_dos_leads(loja_id, dias, termo, agora=agora)
    linhas = _um_cartao_por_cliente(loja_id, linhas)                        # IG3

    contagem = {e: 0 for e in ORDEM_DAS_ETAPAS}
    for linha in linhas:
        contagem[linha["etapa"]] += 1
    if etapa in ROTULOS_ETAPA:
        linhas = [l for l in linhas if l["etapa"] == etapa]

    tamanho = _numero(tamanho, TAMANHO_PADRAO, 1, TAMANHO_MAXIMO)
    total = len(linhas)
    paginas = max(1, math.ceil(total / tamanho))
    pagina = _numero(pagina, 1, 1, paginas)
    inicio = (pagina - 1) * tamanho
    return {
        "pagina": pagina,
        "paginas": paginas,
        "total": total,
        "tamanho": tamanho,
        "periodo_dias": dias,
        "itens": _itens(loja_id, linhas[inicio:inicio + tamanho]),
        "contagem_por_etapa": [{"etapa": e, "rotulo": ROTULOS_ETAPA[e], "total": contagem[e]}
                               for e in ORDEM_DAS_ETAPAS],
    }

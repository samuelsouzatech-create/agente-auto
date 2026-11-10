"""
Tela Acompanhamento (GET /acompanhamento, C2d): as mensagens automáticas da loja.

- modo: o que acontece DE VERDADE (contrato, item 5). Nunca "Ligadas" se nada sai.
  Ordem: loja em teste > pausado > algum tipo saindo de verdade > só simulando.
- pausa: o mesmo formato da luz de saúde.
- proximos, historico e bloqueios: de app/painel_envios.py e app/bloqueios.py,
  com o nome do cliente e o horário prontos (fuso da loja).
- resultado_do_mes: enviados, responderam e agendaram. O custo da Meta NÃO vai
  para a loja (é assunto do operador).
Só lê: nada aqui grava no banco.
"""
from __future__ import annotations

from app import modo_envio, painel_envios
from app.api_painel.formato import horario
from app.apresentacao import nome_do_canal, nomes_dos_clientes
from app.bloqueios import ROTULOS_TIPO, descricao, listar_ativos
from app.estado_loja import esta_no_ar
from app.lojas import carregar_loja
from app.pausa import situacao as situacao_da_pausa
from app.relogio import agora_utc

TIPOS = ("remarketing", "pos_venda", "reativacao")
MAX_PROXIMOS = 100
MAX_HISTORICO = 50
SEM_NOME = "Cliente sem nome"
MODOS = {
    "bloqueado_em_teste": ("Bloqueado: loja em teste",
                           "Nada é enviado a clientes reais enquanto a loja estiver em teste."),
    "pausadas": ("Pausadas", "Nada sai até você retomar."),
    "enviando": ("Enviando", "As mensagens automáticas estão saindo de verdade."),
    "so_simulando": ("Só simulando", "Nada sai de verdade: as mensagens só são simuladas."),
}
EM_TESTE = "Bloqueado: loja em teste"
PAUSADA = "Pausada"
DE_VERDADE = "Enviando de verdade"
SIMULANDO = "Só simulando"


def montar_pausa(loja, loja_id: int, agora) -> dict:
    p = situacao_da_pausa(loja_id)
    if not p["pausado"]:
        return {"ativa": False, "por": None, "desde": None, "motivo": None}
    return {"ativa": True, "por": p["usuario"] or None,
            "desde": horario(loja, p["em"], agora), "motivo": p["motivo"] or None}


def _modo(loja, loja_id: int, pausado: bool) -> dict:
    if not esta_no_ar(loja_id):
        estado, situacoes = "bloqueado_em_teste", {t: EM_TESTE for t in TIPOS}
    elif pausado:
        estado, situacoes = "pausadas", {t: PAUSADA for t in TIPOS}
    else:
        reais = {t: modo_envio.real_para(loja, t) for t in TIPOS}
        estado = "enviando" if any(reais.values()) else "so_simulando"
        situacoes = {t: DE_VERDADE if reais[t] else SIMULANDO for t in TIPOS}
    rotulo, detalhe = MODOS[estado]
    return {"estado": estado, "rotulo": rotulo, "detalhe": detalhe,
            "por_tipo": [{"tipo": t, "tipo_rotulo": painel_envios.TIPOS[t],
                          "situacao": situacoes[t]} for t in TIPOS]}


def _uso(loja_id: int, agora) -> dict:
    uso = painel_envios.uso_do_limite(loja_id, agora)
    usados, limite = int(uso["usados"] or 0), uso["limite"]
    if limite is None:
        palavra = "contato" if usados == 1 else "contatos"
        return {"usados": usados, "texto": f"{usados} {palavra} neste mês"}
    return {"usados": usados, "limite": int(limite),
            "texto": f"{usados} de {limite} contatos neste mês"}


def _passo(valor):
    try:
        return None if valor is None else int(valor)
    except (TypeError, ValueError):
        return None


def montar_bloqueio(loja, b: dict, nomes: dict, agora) -> dict:
    lead = str(b["lead_id"])
    return {"id": int(b["id"]), "lead": lead, "cliente": nomes.get(lead, SEM_NOME),
            "tipo": b["tipo"], "tipo_rotulo": ROTULOS_TIPO.get(b["tipo"], b["tipo"]),
            "passo": _passo(b.get("passo")), "descricao": descricao(b),
            "criado_em": horario(loja, b.get("criado_em"), agora),
            "por": b.get("criado_por") or None}


def _item_envio(loja, i: dict, nomes: dict, agora) -> dict:
    lead = str(i["lead_id"])
    b = i.get("bloqueio")
    canal = i.get("canal") or ""
    return {"tipo": i["tipo"], "tipo_rotulo": painel_envios.TIPOS.get(i["tipo"], i["tipo"]),
            "lead": lead, "cliente": nomes.get(lead, SEM_NOME),
            "canal": nome_do_canal(canal) if canal else "",
            "passo": _passo(i.get("passo")), "quando": horario(loja, i.get("quando"), agora),
            "situacao": str(i.get("situacao") or ""), "detalhe": str(i.get("detalhe") or ""),
            "bloqueio": montar_bloqueio(loja, b, nomes, agora) if b else None,
            "pode_bloquear": not b}


def _item_historico(loja, h: dict, nomes: dict, agora) -> dict | None:
    quando = horario(loja, h.get("quando"), agora)
    if quando is None:
        return None
    lead = str(h["lead_id"])
    estado = str(h.get("estado") or "")
    return {"tipo": h["tipo"], "tipo_rotulo": painel_envios.TIPOS.get(h["tipo"], h["tipo"]),
            "lead": lead, "cliente": nomes.get(lead, SEM_NOME),
            "estado": estado, "estado_rotulo": painel_envios.ROTULOS_ESTADO.get(estado, estado),
            "motivo": h.get("motivo") or "", "texto": h.get("texto") or "",
            "detalhe": h.get("detalhe") or "", "quando": quando}


def montar_acompanhamento(loja_id: int, agora=None) -> dict:
    agora = agora or agora_utc()
    loja = carregar_loja(loja_id)
    pausa = montar_pausa(loja, loja_id, agora)
    fila = painel_envios.fila(loja_id, agora)[:MAX_PROXIMOS]
    feitos = painel_envios.historico(loja_id, MAX_HISTORICO)
    ativos = listar_ativos(loja_id)
    nomes = nomes_dos_clientes(loja_id, [str(x["lead_id"]) for x in fila + feitos + ativos
                                         if x.get("lead_id")])
    historico = [h for h in (_item_historico(loja, x, nomes, agora) for x in feitos) if h]
    total = painel_envios.resultado_do_mes(loja_id, agora)["total"]
    return {
        "modo": _modo(loja, loja_id, pausa["ativa"]),
        "pausa": pausa,
        "uso_mes": _uso(loja_id, agora),
        "proximos": [_item_envio(loja, i, nomes, agora) for i in fila],
        "historico": historico,
        "bloqueios_ativos": [montar_bloqueio(loja, b, nomes, agora) for b in ativos],
        "resultado_do_mes": {c: int(total[c]) for c in ("enviados", "responderam", "agendaram")},
    }

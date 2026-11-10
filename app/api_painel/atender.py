"""
Tela Atender (GET /atender, C2b): três listas de cartões, no formato do contrato.

- esperando: o Léo chamou um vendedor e ninguém assumiu (mais antigo primeiro).
- com_vendedor: um vendedor assumiu.
- conversas_de_hoje: quem trocou mensagem hoje, no fuso da loja (mais recente primeiro).
- espera: contada só dentro do expediente (relogio.minutos_no_expediente),
  igual ao aviso ao gerente. Só aparece em quem está esperando.
- janela de 24 h: app/janela.py. Telegram e simulador não têm janela.
- telefone só no WhatsApp (no Telegram o id do chat não é telefone).
- etiqueta: ainda vazia; a etiqueta neutra entra no C2c, com o cartão da conversa.
Só lê: nada aqui grava no banco.
"""
from __future__ import annotations

from banco import conectar
from app.apresentacao import CANAIS_COM_TELEFONE, nome_do_canal, nomes_dos_clientes
from app.api_painel.formato import horario
from app.handoff import listar_handoffs
from app.janela import CANAIS_COM_JANELA, CANAIS_SEM_JANELA, janela_aberta, janela_fecha_em
from app.lojas import carregar_loja
from app.mensagens import listar_conversas
from app.relogio import (FUSO_PADRAO, agora_utc, do_banco, hora_local,
                         limites_do_dia_em_utc, minutos_no_expediente)
from app.telefone import formatar_telefone_br, normalizar_telefone_br

ATUALIZAR_EM_SEGUNDOS = 20          # contrato, regra 10
MAX_HOJE = 200
_LOTE = 400
JANELA_FECHADA = "Faz mais de 24 h que o cliente não escreve."
SEM_MENSAGEM = "O cliente ainda não escreveu por este canal."
CANAL_SEM_RESPOSTA = "Este canal não aceita resposta pelo painel."
AGUARDANDO, ASSUMIDO, NENHUM = "aguardando", "humano_assumiu", "nenhum"


def texto_da_espera(minutos: int) -> str:
    if minutos < 1:
        return "esperando há menos de 1 min"
    if minutos < 60:
        return f"esperando há {minutos} min"
    horas, resto = divmod(minutos, 60)
    return f"esperando há {horas} h {resto:02d} min"


def _estado(handoff) -> str:
    if handoff is None:
        return NENHUM
    return ASSUMIDO if handoff["estado"] == "humano_assumiu" else AGUARDANDO


def _carros(loja_id: int, leads) -> dict:
    """lead -> carro de interesse (do estoque; senão o que o Léo anotou)."""
    ids = list(dict.fromkeys(leads))
    saida = {}
    if not ids:
        return saida
    conexao = conectar()
    conexao.execute("PRAGMA query_only = ON")
    try:
        for i in range(0, len(ids), _LOTE):
            parte = ids[i:i + _LOTE]
            marcas = ",".join("?" * len(parte))
            for l in conexao.execute(
                    f"SELECT lead_id, interesse FROM leads "
                    f"WHERE loja_id = ? AND lead_id IN ({marcas})", (loja_id, *parte)):
                if (l["interesse"] or "").strip():
                    saida[l["lead_id"]] = l["interesse"].strip()
            for l in conexao.execute(
                    f"SELECT i.lead_id, e.marca, e.modelo, e.ano FROM interesse_veiculo i "
                    f"JOIN estoque e ON e.id = i.veiculo_id AND e.loja_id = i.loja_id "
                    f"WHERE i.loja_id = ? AND i.lead_id IN ({marcas})", (loja_id, *parte)):
                texto = " ".join(str(p) for p in (l["marca"], l["modelo"], l["ano"])
                                 if p not in (None, ""))
                if texto:
                    saida[l["lead_id"]] = texto
    finally:
        conexao.close()
    return saida


def janela_do_cartao(loja, loja_id: int, lead: str, canal: str, agora) -> dict:
    if canal in CANAIS_SEM_JANELA:
        return {"aberta": True, "fecha_em": None, "explicacao": None}
    if canal not in CANAIS_COM_JANELA:
        return {"aberta": False, "fecha_em": None,
                "explicacao": CANAL_SEM_RESPOSTA if canal else SEM_MENSAGEM}
    fecha = janela_fecha_em(loja_id, lead, canal)
    if janela_aberta(loja_id, lead, canal, agora):
        return {"aberta": True, "fecha_em": horario(loja, fecha, agora), "explicacao": None}
    return {"aberta": False, "fecha_em": None,
            "explicacao": JANELA_FECHADA if fecha else SEM_MENSAGEM}


def _cartao(loja, loja_id, lead, conversa, handoff, nomes, carros, agora) -> dict:
    canal = (conversa or {}).get("canal") or ""
    estado = _estado(handoff)
    cartao = {"lead": lead, "nome": nomes.get(lead, "Cliente sem nome")}
    if canal in CANAIS_COM_TELEFONE:
        fone = normalizar_telefone_br(lead)
        if fone:
            cartao["telefone"] = formatar_telefone_br(fone)
    espera = None
    if estado == AGUARDANDO and handoff.get("criado_em"):
        minutos = minutos_no_expediente(loja, do_banco(handoff["criado_em"]), agora)
        espera = {"minutos": minutos, "texto": texto_da_espera(minutos)}
    cartao.update({
        "origem": nome_do_canal(canal),
        "carro": carros.get(lead, ""),
        "motivo": ((handoff or {}).get("motivo") or "").strip(),
        "etiqueta": "",
        "ultima_mensagem": horario(loja, (conversa or {}).get("ultima_mensagem"), agora),
        "espera": espera,
        "estado_do_chamado": estado,
        "assumido_por": handoff.get("vendedor") if estado == ASSUMIDO else None,
        "janela": janela_do_cartao(loja, loja_id, lead, canal, agora),
    })
    return cartao


def montar_atender(loja_id: int, agora=None) -> dict:
    agora = agora or agora_utc()
    loja = carregar_loja(loja_id)

    abertos = {}
    for h in listar_handoffs(loja_id):            # do mais antigo ao mais novo
        abertos[h["lead_id"]] = h                 # vale o mais novo de cada cliente
    em_ordem = sorted(abertos.values(), key=lambda h: (str(h.get("criado_em") or ""), h["id"]))

    conversas = {c["lead_id"]: c for c in listar_conversas(loja_id)}   # mais recente primeiro
    inicio, fim = limites_do_dia_em_utc(loja.get("fuso") or FUSO_PADRAO,
                                        hora_local(loja, agora).date())
    hoje = [lead for lead, c in conversas.items()
            if inicio <= str(c.get("ultima_mensagem") or "")[:19] < fim][:MAX_HOJE]

    leads = list(dict.fromkeys([h["lead_id"] for h in em_ordem] + hoje))
    nomes = nomes_dos_clientes(loja_id, leads)
    carros = _carros(loja_id, leads)

    def cartao(lead):
        return _cartao(loja, loja_id, lead, conversas.get(lead), abertos.get(lead),
                       nomes, carros, agora)

    return {
        "atualizar_em_segundos": ATUALIZAR_EM_SEGUNDOS,
        "esperando": [cartao(h["lead_id"]) for h in em_ordem if _estado(h) == AGUARDANDO],
        "com_vendedor": [cartao(h["lead_id"]) for h in em_ordem if _estado(h) == ASSUMIDO],
        "conversas_de_hoje": [cartao(lead) for lead in hoje],
    }

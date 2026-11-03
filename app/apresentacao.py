"""
Camada de apresentação (P3 do Plano Mestre): horário e nomes para as telas e a API.

Regra: o banco continua em UTC; quem mostra converte AQUI, no fuso da loja.
A tela não converte horário nem monta nome de cliente sozinha.
Só leitura: nada aqui grava no banco.
"""
from __future__ import annotations

from datetime import date, datetime

from banco import conectar
from app.chaves import exigir_loja
from app.lojas import carregar_loja
from app.relogio import agora_utc, do_banco, hora_local
from app.telefone import formatar_telefone_br, normalizar_telefone_br

SEM_HORA = "—"
DIAS_CURTOS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")
NOMES_DOS_CANAIS = {"whatsapp": "WhatsApp", "telegram": "Telegram",
                    "instagram": "Instagram", "simulador": "Simulador"}
# Só no WhatsApp o lead_id é telefone. No Telegram é o número do chat,
# que às vezes PARECE celular: não pode virar telefone na tela.
CANAIS_COM_TELEFONE = {"whatsapp"}
_LOTE = 400


def _loja(loja):
    """Aceita a loja já carregada ou o número dela."""
    if isinstance(loja, int):
        return carregar_loja(loja)
    return loja


def _instante(valor) -> datetime | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor
    try:
        return do_banco(str(valor).strip().replace("T", " "))
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------ horário

def horario_para_tela(loja, valor, *, agora: datetime | None = None) -> str:
    """Hora do banco (UTC) -> texto no fuso da loja:
    "hoje 21:40", "ontem 09:00", "amanhã 10:00", "seg 09:00" (até 6 dias),
    "29/10 15:10" (mesmo ano) ou "29/10/2025 15:10". Vazio ou inválido: "—"."""
    instante = _instante(valor)
    if instante is None:
        return SEM_HORA
    loja = _loja(loja)
    local = hora_local(loja, instante)
    hoje = hora_local(loja, agora or agora_utc()).date()
    dias = (local.date() - hoje).days
    hora = local.strftime("%H:%M")
    if dias == 0:
        return f"hoje {hora}"
    if dias == -1:
        return f"ontem {hora}"
    if dias == 1:
        return f"amanhã {hora}"
    if -6 <= dias <= 6:
        return f"{DIAS_CURTOS[local.weekday()]} {hora}"
    if local.year == hoje.year:
        return f"{local:%d/%m} {hora}"
    return f"{local:%d/%m/%Y} {hora}"


def horario_iso_local(loja, valor) -> str | None:
    """Para a API: "2026-11-02T21:40:00-03:00". Vazio ou inválido: None."""
    instante = _instante(valor)
    if instante is None:
        return None
    return hora_local(_loja(loja), instante).isoformat(timespec="seconds")


def data_para_tela(valor) -> str:
    """Data sem hora (venda, retomar em...): "02/11/2026". Vazio ou inválido: "—"."""
    if valor is None or valor == "":
        return SEM_HORA
    if isinstance(valor, datetime):
        valor = valor.date()
    if not isinstance(valor, date):
        try:
            valor = date.fromisoformat(str(valor).strip()[:10])
        except ValueError:
            return SEM_HORA
    return valor.strftime("%d/%m/%Y")


def nome_do_canal(canal) -> str:
    if not canal:
        return SEM_HORA
    return NOMES_DOS_CANAIS.get(canal, str(canal))


# ------------------------------------------------------------ nomes

def _partes(lista):
    for i in range(0, len(lista), _LOTE):
        yield lista[i:i + _LOTE]


def _sem_nome(lead_id: str) -> str:
    final = str(lead_id)[-4:]
    return f"Cliente sem nome (…{final})" if final else "Cliente sem nome"


def nomes_dos_clientes(loja_id, lead_ids) -> dict[str, str]:
    """lead_id -> como o cliente aparece na tela, para uma lista inteira.
    Ordem: nome que o Léo anotou (leads) -> nome da base importada (contatos)
    -> telefone formatado (só WhatsApp ou canal desconhecido) -> "Cliente sem nome (…1234)"."""
    loja_id = exigir_loja(loja_id)
    ids = list(dict.fromkeys(str(l) for l in lead_ids if l not in (None, "")))
    if not ids:
        return {}
    nomes, canais, fones = {}, {}, {}
    conexao = conectar()
    try:
        for parte in _partes(ids):
            marcas = ",".join("?" * len(parte))
            for l in conexao.execute(
                    f"SELECT lead_id, nome FROM leads WHERE loja_id = ? AND lead_id IN ({marcas})",
                    (loja_id, *parte)):
                if (l["nome"] or "").strip():
                    nomes[l["lead_id"]] = l["nome"].strip()
            for l in conexao.execute(
                    f"SELECT m.lead_id, m.canal FROM mensagens m "
                    f"WHERE m.loja_id = ? AND m.lead_id IN ({marcas}) "
                    f"AND m.id = (SELECT MAX(y.id) FROM mensagens y "
                    f"WHERE y.loja_id = m.loja_id AND y.lead_id = m.lead_id)",
                    (loja_id, *parte)):
                canais[l["lead_id"]] = l["canal"] or ""

        for lead_id in ids:
            if lead_id in nomes:
                continue
            canal = canais.get(lead_id)
            if canal and canal not in CANAIS_COM_TELEFONE:
                continue
            fone = normalizar_telefone_br(lead_id)
            if fone:
                fones[lead_id] = fone

        da_base = {}
        lista_fones = list(set(fones.values()))
        for parte in _partes(lista_fones):
            marcas = ",".join("?" * len(parte))
            for l in conexao.execute(
                    f"SELECT telefone, nome FROM contatos WHERE loja_id = ? AND telefone IN ({marcas})",
                    (loja_id, *parte)):
                if (l["nome"] or "").strip():
                    da_base[l["telefone"]] = l["nome"].strip()
    finally:
        conexao.close()

    saida = {}
    for lead_id in ids:
        if lead_id in nomes:
            saida[lead_id] = nomes[lead_id]
        elif lead_id in fones:
            saida[lead_id] = da_base.get(fones[lead_id]) or formatar_telefone_br(fones[lead_id])
        else:
            saida[lead_id] = _sem_nome(lead_id)
    return saida


def nome_do_cliente(loja_id, lead_id) -> str:
    """Um cliente só. Para listas, use nomes_dos_clientes (uma ida ao banco)."""
    return nomes_dos_clientes(loja_id, [lead_id]).get(str(lead_id), "Cliente sem nome")

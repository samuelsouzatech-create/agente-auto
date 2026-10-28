"""
Tarefas do relógio (Etapa 1, Bloco 7B - item 1.10).

Handoff: aviso ao vendedor na hora; re-aviso depois de handoff.reaviso_min;
gestor depois de handoff.gestor_min (tempos da Configuração da loja).
Os lembretes só contam minutos DENTRO do horário de atendimento humano.

Gasto: alerta ao operador em 80% e em 100% do teto diário, uma vez por dia
(o dia vira à meia-noite no fuso da loja). Não bloqueia o agente.

Toda função recebe 'agora' (UTC) para os testes adiantarem o relógio.
"""
from __future__ import annotations

from datetime import datetime

from app import avisos, custos, relogio
from app.lojas import Loja, carregar_loja
from app.lojas_admin import listar_lojas
from app.usuarios import contatos_para_aviso
from banco import conectar

COLUNA = {"aviso": "avisado_em", "reaviso": "reavisado_em", "gestor": "gestor_avisado_em"}
FAIXAS_GASTO = ((1.0, "gasto_100"), (0.8, "gasto_80"))   # a maior primeiro
LIMITE_RESUMO = 600


# ---------------------------------------------------------------- apoio
def _ids_lojas_ativas() -> list[int]:
    return [l["id"] for l in listar_lojas() if l["ativo"]]


def _chats(loja_id: int, papel: str) -> list[str]:
    return [u["contato_telegram"] for u in contatos_para_aviso(loja_id, papel)]


def _abertos(loja_id: int) -> list[dict]:
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT id, lead_id, motivo, resumo, criado_em, avisado_em, reavisado_em, "
            "gestor_avisado_em FROM handoffs "
            "WHERE loja_id = ? AND estado = 'aguardando_humano' ORDER BY id",
            (loja_id,),
        ).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]


def _ainda_esperando(handoff_id: int) -> bool:
    conexao = conectar()
    try:
        linha = conexao.execute("SELECT estado FROM handoffs WHERE id = ?", (handoff_id,)).fetchone()
    finally:
        conexao.close()
    return bool(linha) and linha["estado"] == "aguardando_humano"


def _dados_do_lead(loja_id: int, lead_id: str) -> dict:
    conexao = conectar()
    try:
        lead = conexao.execute(
            "SELECT nome FROM leads WHERE loja_id = ? AND lead_id = ?", (loja_id, lead_id)
        ).fetchone()
        canal = conexao.execute(
            "SELECT canal FROM mensagens WHERE loja_id = ? AND lead_id = ? "
            "AND COALESCE(canal, '') != '' ORDER BY id DESC LIMIT 1",
            (loja_id, lead_id),
        ).fetchone()
    finally:
        conexao.close()
    return {"nome": lead["nome"] if lead and lead["nome"] else None,
            "canal": canal["canal"] if canal else None}


def _marcar(handoff_id: int, etapa: str, agora: datetime) -> None:
    coluna = COLUNA[etapa]                      # vem do dicionário fixo, não do usuário
    conexao = conectar()
    try:
        conexao.execute(f"UPDATE handoffs SET {coluna} = ? WHERE id = ? AND {coluna} IS NULL",
                        (relogio.para_banco(agora), handoff_id))
        conexao.commit()
    finally:
        conexao.close()


def _brl(valor: float) -> str:
    texto = f"{float(valor or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


# ---------------------------------------------------------------- handoff
def _texto_handoff(loja: Loja, h: dict, dados: dict, etapa: str, minutos: int,
                   no_horario: bool) -> str:
    cabecalho = {
        "aviso": f"🔔 {loja.nome}: cliente esperando um vendedor.",
        "reaviso": f"⏰ {loja.nome}: cliente esperando há {minutos} min e ninguém assumiu ainda.",
        "gestor": f"🚨 {loja.nome}: cliente esperando há {minutos} min sem ninguém assumir.",
    }[etapa]
    cliente = dados["nome"] or h["lead_id"]
    if dados["canal"]:
        cliente += f" (via {dados['canal']})"
    linhas = [cabecalho, "", f"Cliente: {cliente}", f"Motivo: {h['motivo'] or '-'}"]
    resumo = (h["resumo"] or "").strip()
    if resumo:
        linhas.append(f"Resumo: {resumo[:LIMITE_RESUMO]}")
    linhas += ["", "Para atender: painel da loja > Fila de handoff > Assumir."]
    if etapa == "aviso" and not no_horario:
        linhas.append("Fora do horário de atendimento. O lembrete vem quando a loja abrir.")
    return "\n".join(linhas)


def _handoffs_da_loja(loja: Loja, agora: datetime) -> int:
    abertos = _abertos(loja.id)
    if not abertos:
        return 0
    vendedores = _chats(loja.id, "vendedor")
    gestores = _chats(loja.id, "gestor")
    equipe = vendedores or gestores             # sem vendedor, o gestor recebe
    no_horario = relogio.no_horario(loja, agora)
    reaviso_min = loja.get("handoff.reaviso_min", 5)
    gestor_min = loja.get("handoff.gestor_min", 10)

    enviados = 0
    for h in abertos:
        etapas = []
        if not h["avisado_em"]:
            etapas.append(("aviso", equipe, 0))
        if no_horario and h["criado_em"]:
            minutos = relogio.minutos_no_expediente(loja, relogio.do_banco(h["criado_em"]), agora)
            if not h["reavisado_em"] and minutos >= reaviso_min:
                etapas.append(("reaviso", equipe, minutos))
            if not h["gestor_avisado_em"] and minutos >= gestor_min:
                etapas.append(("gestor", gestores, minutos))
        if not etapas:
            continue

        dados = _dados_do_lead(loja.id, h["lead_id"])
        for etapa, destinos, minutos in etapas:
            if not _ainda_esperando(h["id"]):   # alguém assumiu no meio do ciclo
                break
            r = avisos.avisar_uma_vez(
                loja.id, f"handoff_{etapa}", f"handoff:{h['id']}", destinos,
                _texto_handoff(loja, h, dados, etapa, minutos, no_horario),
            )
            enviados += r["enviados"]
            if r["concluido"]:
                _marcar(h["id"], etapa, agora)
    return enviados


def verificar_handoffs(agora: datetime | None = None) -> int:
    agora = agora or relogio.agora_utc()
    total = 0
    for loja_id in _ids_lojas_ativas():
        try:
            total += _handoffs_da_loja(carregar_loja(loja_id), agora)
        except Exception as erro:               # uma loja com problema não trava as outras
            print(f"[Avisos] Erro nos handoffs da loja {loja_id}: {erro!r}")
    return total


# ---------------------------------------------------------------- gasto
def _texto_gasto(loja: Loja, dia, gasto: float, teto: float, faixa: float) -> str:
    if faixa >= 1.0:
        cabecalho = f"💰 {loja.nome}: passou do teto diário de custo."
    else:
        cabecalho = f"💰 {loja.nome}: chegou a 80% do teto diário de custo."
    pct = int(round(gasto / teto * 100))
    return (f"{cabecalho}\n\nGasto de hoje ({dia:%d/%m}): {_brl(gasto)} de {_brl(teto)} ({pct}%).\n"
            "O agente continua respondendo normalmente. Ajuste em Plano e limites, se precisar.")


def _gasto_da_loja(loja: Loja, agora: datetime, chat: str) -> int:
    teto = loja.get("custos.teto_diario_llm")
    if not teto:
        return 0
    dia = relogio.dia_local(loja, agora)
    gasto = custos.gasto_do_dia(loja.id, dia, fuso=loja.get("fuso"))
    for faixa, tipo in FAIXAS_GASTO:
        if gasto >= teto * faixa:
            r = avisos.avisar_uma_vez(loja.id, tipo, f"loja:{loja.id}:{dia.isoformat()}",
                                      [chat] if chat else [],
                                      _texto_gasto(loja, dia, gasto, teto, faixa))
            return r["enviados"]
    return 0


def verificar_gastos(agora: datetime | None = None) -> int:
    agora = agora or relogio.agora_utc()
    chat = avisos.chat_do_operador()
    total = 0
    for loja_id in _ids_lojas_ativas():
        try:
            total += _gasto_da_loja(carregar_loja(loja_id), agora, chat)
        except Exception as erro:
            print(f"[Avisos] Erro no gasto da loja {loja_id}: {erro!r}")
    return total


# ---------------------------------------------------------------- ciclo
def rodar_ciclo(agora: datetime | None = None) -> dict:
    agora = agora or relogio.agora_utc()
    return {"handoffs": verificar_handoffs(agora), "gastos": verificar_gastos(agora)}

"""
Pausar todos os envios da loja (Etapa 2, Bloco 7).

Um clique para parar TUDO o que a loja manda por iniciativa própria:
retomadas, pós-venda e reativação. O dono da loja e o operador podem
pausar, e os dois podem retomar.

O atendimento de quem escreve NÃO para: o assistente continua respondendo
normalmente. Pausar envios não é desligar o assistente.

Cada pausa e cada retomada fica gravada (quem, papel, quando, motivo).
Ao retomar, passos de pós-venda que venceram há mais de 3 dias durante a
pausa são cancelados ("obrigado pela compra" um mês depois soa estranho).
"""
from __future__ import annotations

from datetime import datetime, timezone

from banco import conectar
from app.chaves import exigir_loja
from app.lojas import PAPEIS
from app.regua import TOLERANCIA_ATRASO
from app.relogio import agora_utc, do_banco, para_banco

MAX_MOTIVO = 200
MOTIVO_CANCELADO = "pausa_longa"
MOTIVOS = {MOTIVO_CANCELADO: "Venceu durante a pausa dos envios"}
ROTULOS_PAPEL = {"cliente": "loja", "operador": "operador"}


class PausaInvalida(ValueError):
    pass


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _ultima(loja_id) -> dict | None:
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT * FROM pausas_envio WHERE loja_id = ? ORDER BY id DESC LIMIT 1",
            (loja_id,)).fetchone()
    finally:
        conexao.close()
    return dict(linha) if linha else None


def situacao(loja_id) -> dict:
    loja_id = exigir_loja(loja_id)
    ultima = _ultima(loja_id)
    if not ultima or ultima["acao"] != "pausar":
        return {"pausado": False, "usuario": None, "papel": None, "motivo": None, "em": None}
    return {"pausado": True, "usuario": ultima["usuario"], "papel": ultima["papel"],
            "motivo": ultima["motivo"] or "", "em": do_banco(ultima["criado_em"])}


def pausado(loja_id) -> bool:
    """Os jobs perguntam aqui antes de cada loja."""
    return situacao(loja_id)["pausado"]


def _validar(usuario, papel) -> str:
    if papel not in PAPEIS:
        raise PausaInvalida(f"Papel '{papel}' não existe.")
    usuario = " ".join(str(usuario or "").split())
    if not usuario:
        raise PausaInvalida("Informe quem está fazendo isto.")
    return usuario


def pausar(loja_id, *, usuario: str, papel: str, motivo: str = "",
           agora: datetime | None = None) -> dict:
    loja_id = exigir_loja(loja_id)
    usuario = _validar(usuario, papel)
    motivo = " ".join(str(motivo or "").split())[:MAX_MOTIVO]
    if pausado(loja_id):
        raise PausaInvalida("Os envios desta loja já estão pausados.")
    agora = _utc(agora or agora_utc())
    conexao = conectar()
    try:
        conexao.execute(
            "INSERT INTO pausas_envio (loja_id, acao, usuario, papel, motivo, criado_em) "
            "VALUES (?, 'pausar', ?, ?, ?, ?)", (loja_id, usuario, papel, motivo, para_banco(agora)))
        conexao.commit()
    finally:
        conexao.close()
    return situacao(loja_id)


def retomar(loja_id, *, usuario: str, papel: str, agora: datetime | None = None) -> dict:
    loja_id = exigir_loja(loja_id)
    usuario = _validar(usuario, papel)
    if not pausado(loja_id):
        raise PausaInvalida("Os envios desta loja não estão pausados.")
    agora = _utc(agora or agora_utc())
    conexao = conectar()
    try:
        conexao.execute(
            "INSERT INTO pausas_envio (loja_id, acao, usuario, papel, criado_em) "
            "VALUES (?, 'retomar', ?, ?, ?)", (loja_id, usuario, papel, para_banco(agora)))
        cancelados = conexao.execute(
            "UPDATE regua_execucoes SET estado = 'cancelado', motivo = ?, executado_em = ? "
            "WHERE loja_id = ? AND estado = 'agendado' AND agendado_para < ?",
            (MOTIVO_CANCELADO, para_banco(agora), loja_id,
             para_banco(agora - TOLERANCIA_ATRASO))).rowcount
        conexao.commit()
    finally:
        conexao.close()
    return {"cancelados": cancelados}


def historico(loja_id, limite: int = 20) -> list[dict]:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT acao, usuario, papel, motivo, criado_em FROM pausas_envio "
            "WHERE loja_id = ? ORDER BY id DESC LIMIT ?", (loja_id, limite)).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]

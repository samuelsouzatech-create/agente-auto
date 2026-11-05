"""
Mensagens automáticas (S6 do Plano Mestre, Fase 3): dados da tela do operador.

Duas perguntas:
  situacao_agora(): por que cada cliente recebe ou não a retomada HOJE.
      Usa a mesma decisão do robô (app/elegibilidade.py), com a fotografia
      da loja: poucas consultas por loja, nenhuma por cliente.
  gravado_no_mes(): o que ficou GRAVADO no mês, por tipo, resultado e
      motivo (uma consulta agrupada por tipo). Pulos passageiros (fora do
      horário, limite do mês, carência) não são gravados quando passam, por
      isso não aparecem aqui. Histórico completo exigiria tabela nova
      (decisão D-3 do S6: só com decisão do Samuel e migração própria).

Só leitura. Não importa Streamlit nem os jobs.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from banco import conectar
from app import painel_envios as pe
from app.apresentacao import horario_para_tela, nome_do_canal, nomes_dos_clientes
from app.chaves import exigir_loja
from app.elegibilidade import ROTULOS, candidatos
from app.lojas import carregar_loja
from app.relogio import para_banco

TIPOS = pe.TIPOS
AVISO_NO_MES = ("“No mês” mostra só o que ficou gravado. Pulos passageiros (fora do horário, "
                "limite do mês, carência) não ficam guardados depois que passam.")

# Uma consulta por tipo, agrupada por resultado e motivo (nunca por cliente).
_CONSULTAS_DO_MES = {
    "remarketing": (
        "SELECT estado, COALESCE(motivo_bloqueio, '') AS motivo, COUNT(*) AS n "
        "FROM remarketing_envios WHERE loja_id = ? "
        "AND COALESCE(enviado_em, criado_em) >= ? AND COALESCE(enviado_em, criado_em) <= ? "
        "GROUP BY estado, COALESCE(motivo_bloqueio, '')"),
    "pos_venda": (
        "SELECT estado, COALESCE(motivo, '') AS motivo, COUNT(*) AS n "
        "FROM regua_execucoes WHERE loja_id = ? AND estado != 'agendado' "
        "AND COALESCE(executado_em, criado_em) >= ? AND COALESCE(executado_em, criado_em) <= ? "
        "GROUP BY estado, COALESCE(motivo, '')"),
    "reativacao": (
        "SELECT estado, COALESCE(motivo, '') AS motivo, COUNT(*) AS n "
        "FROM reativacao WHERE loja_id = ? AND estado != 'na_fila' "
        "AND COALESCE(enviado_em, atualizado_em, criado_em) >= ? "
        "AND COALESCE(enviado_em, atualizado_em, criado_em) <= ? "
        "GROUP BY estado, COALESCE(motivo, '')"),
}


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _motivo(codigo) -> str:
    if not codigo:
        return ""
    return pe.MOTIVOS.get(codigo, str(codigo).replace("_", " "))


def situacao_agora(loja_id, agora: datetime) -> dict:
    """Retomada: quem pode receber agora e, para quem não pode, o motivo e
    quando será o próximo contato (no fuso da loja)."""
    loja_id = exigir_loja(loja_id)
    agora = _utc(agora)
    loja = carregar_loja(loja_id)
    decisoes = candidatos(loja_id, agora)
    nomes = nomes_dos_clientes(loja_id, [d.lead_id for d in decisoes])
    itens = []
    for d in decisoes:
        if d.elegivel:
            quando = "agora"
        elif d.proximo_em:
            quando = horario_para_tela(loja, d.proximo_em, agora=agora)
        else:
            quando = "—"
        itens.append({"lead_id": d.lead_id, "cliente": nomes.get(d.lead_id, "Cliente sem nome"),
                      "canal": nome_do_canal(d.canal), "pode": d.elegivel, "motivo": d.motivo,
                      "situacao": d.rotulo, "toque": d.toque, "quando": quando})
    itens.sort(key=lambda i: not i["pode"])          # quem pode vem primeiro; o resto na ordem da fila
    contagem = Counter(i["motivo"] for i in itens)
    resumo = [{"motivo": m, "situacao": ROTULOS[m], "clientes": contagem[m]}
              for m in ROTULOS if contagem.get(m)]
    modo = pe.situacao_do_modo(loja)["remarketing"]
    return {"itens": itens, "resumo": resumo, "podem_agora": contagem.get("elegivel", 0),
            "limite": pe.uso_do_limite(loja_id, agora),
            "modo": pe.ROTULOS_MODO.get(modo, modo)}


def gravado_no_mes(loja_id, agora: datetime) -> dict:
    """O que ficou gravado do começo do mês (fuso da loja) até agora."""
    loja_id = exigir_loja(loja_id)
    agora = _utc(agora)
    loja = carregar_loja(loja_id)
    de, ate = para_banco(pe.inicio_do_mes(loja, agora)), para_banco(agora)
    linhas = []
    conexao = conectar()
    try:
        for tipo, sql in _CONSULTAS_DO_MES.items():
            for l in conexao.execute(sql, (loja_id, de, ate)).fetchall():
                linhas.append({"tipo": tipo, "mensagem": TIPOS[tipo], "estado": l["estado"],
                               "resultado": pe.ROTULOS_ESTADO.get(l["estado"], l["estado"]),
                               "motivo": _motivo(l["motivo"]), "quantidade": int(l["n"])})
    finally:
        conexao.close()
    ordem = list(TIPOS)
    linhas.sort(key=lambda x: (ordem.index(x["tipo"]), -x["quantidade"], x["resultado"]))
    totais = {tipo: sum(x["quantidade"] for x in linhas if x["tipo"] == tipo) for tipo in TIPOS}
    return {"linhas": linhas, "totais": totais}

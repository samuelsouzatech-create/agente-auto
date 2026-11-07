"""
Bloqueios de envio escolhidos pela LOJA (P5 do Plano Mestre).

"Não enviar": segura UMA mensagem (um toque da retomada, um passo do
pós-venda ou a reativação). "Não procurar mais": tipo 'todos', segura tudo
o que a loja mandaria por iniciativa própria para aquele cliente.

Não é opt-out: opt-out (tabela optouts) é o pedido do CLIENTE (LGPD e regra
da Meta). O bloqueio é escolha da loja e pode ser desfeito. Desfazer não
apaga a linha: grava quem desfez e quando.

Enquanto bloqueada, a mensagem fica parada (não é cancelada): desfazendo,
sai na próxima rodada, se ainda valer. Nada aqui mexe no atendimento:
quem escreve para a loja continua sendo atendido normalmente.

passo: remarketing = número do toque; pos_venda = a linha agendada da régua;
reativacao = vazio. Bloqueio com passo vazio vale para todas daquele tipo.

P6: bloquear e desfazer gravam no Registro (registro_acoes), na mesma
transação, com o nome do ator. Marca repetida não grava de novo.
"""
from __future__ import annotations

from datetime import datetime

from banco import conectar
from app.chaves import exigir_loja
from app.registro import registrar
from app.permissoes import exigir_pode_agir
from app.relogio import agora_utc, do_banco, para_banco

TIPOS = ("remarketing", "pos_venda", "reativacao", "todos")
ROTULOS_TIPO = {"remarketing": "Retomada", "pos_venda": "Pós-venda",
                "reativacao": "Reativação", "todos": "Não procurar mais"}


class BloqueioInvalido(ValueError):
    pass


def _limpo(texto) -> str:
    return " ".join(str(texto or "").split())


def _linha(l) -> dict:
    d = dict(l)
    d["criado_em"] = do_banco(d["criado_em"]) if d.get("criado_em") else None
    d["desfeito_em"] = do_banco(d["desfeito_em"]) if d.get("desfeito_em") else None
    return d


def bloquear(loja_id, lead_id, tipo: str, passo, autor: str, *,
             agora: datetime | None = None) -> int:
    """Marca para não enviar. Se a mesma marca já está ativa, devolve a que existe."""
    loja_id = exigir_loja(loja_id)
    exigir_pode_agir(loja_id)        # S5: loja No ar, operador só vê
    lead_id, autor = _limpo(lead_id), _limpo(autor)
    if not lead_id:
        raise BloqueioInvalido("Cliente não informado.")
    if tipo not in TIPOS:
        raise BloqueioInvalido("Tipo de mensagem inválido.")
    if not autor:
        raise BloqueioInvalido("Informe quem está marcando.")
    if tipo == "todos" or passo is None:
        passo = None
    else:
        try:
            passo = int(passo)
        except (TypeError, ValueError):
            raise BloqueioInvalido("Mensagem inválida.") from None
    conexao = conectar()
    try:
        existente = conexao.execute(
            "SELECT id FROM bloqueios_envio WHERE loja_id = ? AND lead_id = ? AND tipo = ? "
            "AND passo IS ? AND desfeito_em IS NULL", (loja_id, lead_id, tipo, passo)).fetchone()
        if existente:
            return int(existente["id"])
        cursor = conexao.execute(
            "INSERT INTO bloqueios_envio (loja_id, lead_id, tipo, passo, criado_por, criado_em) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (loja_id, lead_id, tipo, passo, autor, para_banco(agora or agora_utc())))
        novo_id = int(cursor.lastrowid)
        registrar("bloquear_envio", loja_id, None,
                  {"bloqueio_id": novo_id, "tipo": tipo, "passo": passo},
                  conexao=conexao, alvo=f"lead:{lead_id}")
        conexao.commit()
        return novo_id
    finally:
        conexao.close()


def desfazer(loja_id, bloqueio_id, autor: str, *, agora: datetime | None = None) -> bool:
    """True se desfez agora. False se já estava desfeito ou é de outra loja."""
    loja_id = exigir_loja(loja_id)
    autor = _limpo(autor)
    if not autor:
        raise BloqueioInvalido("Informe quem está desfazendo.")
    conexao = conectar()
    try:
        marca = conexao.execute(
            "SELECT lead_id, tipo, passo FROM bloqueios_envio "
            "WHERE id = ? AND loja_id = ? AND desfeito_em IS NULL",
            (int(bloqueio_id), loja_id)).fetchone()
        n = conexao.execute(
            "UPDATE bloqueios_envio SET desfeito_por = ?, desfeito_em = ? "
            "WHERE id = ? AND loja_id = ? AND desfeito_em IS NULL",
            (autor, para_banco(agora or agora_utc()), int(bloqueio_id), loja_id)).rowcount
        if n == 1 and marca is not None:
            registrar("desfazer_bloqueio", loja_id,
                      {"bloqueio_id": int(bloqueio_id), "tipo": marca["tipo"],
                       "passo": marca["passo"], "ativo": True},
                      {"ativo": False},
                      conexao=conexao, alvo=f"lead:{marca['lead_id']}")
        conexao.commit()
    finally:
        conexao.close()
    return n == 1


def bloqueio_ativo(loja_id, lead_id, tipo: str, passo) -> dict | None:
    """A marca que segura esta mensagem ('todos' primeiro), ou None."""
    loja_id = exigir_loja(loja_id)
    passo = None if passo is None else int(passo)
    conexao = conectar()
    try:
        l = conexao.execute(
            "SELECT * FROM bloqueios_envio WHERE loja_id = ? AND lead_id = ? "
            "AND desfeito_em IS NULL "
            "AND (tipo = 'todos' OR (tipo = ? AND (passo IS NULL OR passo = ?))) "
            "ORDER BY (tipo = 'todos') DESC, id DESC LIMIT 1",
            (loja_id, _limpo(lead_id), tipo, passo)).fetchone()
    finally:
        conexao.close()
    return _linha(l) if l else None


def bloqueado(loja_id, lead_id, tipo: str, passo) -> bool:
    return bloqueio_ativo(loja_id, lead_id, tipo, passo) is not None


def leads_bloqueados(loja_id, tipo: str) -> set[str]:
    """Clientes com o tipo inteiro bloqueado (passo vazio) ou 'todos'."""
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT DISTINCT lead_id FROM bloqueios_envio WHERE loja_id = ? "
            "AND desfeito_em IS NULL AND (tipo = 'todos' OR (tipo = ? AND passo IS NULL))",
            (loja_id, tipo)).fetchall()
    finally:
        conexao.close()
    return {l["lead_id"] for l in linhas}


def listar_ativos(loja_id) -> list[dict]:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT * FROM bloqueios_envio WHERE loja_id = ? AND desfeito_em IS NULL "
            "ORDER BY id DESC", (loja_id,)).fetchall()
    finally:
        conexao.close()
    return [_linha(l) for l in linhas]


def total_ativos(loja_id) -> int:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        return int(conexao.execute(
            "SELECT COUNT(*) FROM bloqueios_envio WHERE loja_id = ? AND desfeito_em IS NULL",
            (loja_id,)).fetchone()[0])
    finally:
        conexao.close()


def descricao(b: dict) -> str:
    """Texto da tela para uma marca (sem número interno)."""
    if b["tipo"] == "todos":
        return "Não procurar mais (nenhuma retomada, pós-venda ou reativação)"
    nome = ROTULOS_TIPO.get(b["tipo"], b["tipo"])
    if b["passo"] is None:
        return f"{nome}: nenhuma mensagem"
    if b["tipo"] == "remarketing":
        return f"{nome}: toque {b['passo']}"
    return f"{nome}: uma mensagem"

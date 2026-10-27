"""Situação do lead percebida pelo Léo na conversa (Etapa 1, Bloco 7A).

Ninguém digita comando. O Léo percebe pelo jeito do cliente e anota:
  pediu_tempo    -> "agora não", "mês que vem eu vejo"   (a loja espera)
  sem_interesse  -> "já comprei", "desisti"              (a loja não procura)
  nao_contatar   -> "para de me mandar mensagem"         (nunca procurar)

Regras:
  - Quando o próprio lead escreve, o Léo SEMPRE responde. Isto aqui só
    controla se a LOJA pode procurar o lead (remarketing/pós-venda, Etapa 2).
  - 'nao_contatar' também grava em optouts (exigência da LGPD e da Meta).
  - Só a loja desfaz o 'nao_contatar', pelo painel ("Reativar contato").
"""
from datetime import date, timedelta

from banco import conectar

SITUACOES = ("pediu_tempo", "sem_interesse", "nao_contatar")
ROTULOS = {
    "pediu_tempo": "Pediu um tempo",
    "sem_interesse": "Sem interesse no momento",
    "nao_contatar": "Não quer ser procurado",
}
DIAS_PADRAO_TEMPO = 30     # cliente não disse quando
MAX_DIAS_TEMPO = 180


class SituacaoInvalida(ValueError):
    pass


def _dias(valor) -> int:
    try:
        dias = int(float(valor or 0))
    except (TypeError, ValueError):
        dias = 0
    return dias if 0 < dias <= MAX_DIAS_TEMPO else DIAS_PADRAO_TEMPO


def situacao_do_lead(loja_id: int, lead_id: str) -> dict | None:
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT * FROM situacao_lead WHERE loja_id = ? AND lead_id = ?",
            (loja_id, lead_id),
        ).fetchone()
    finally:
        conexao.close()
    return dict(linha) if linha else None


def registrar_situacao(loja_id: int, lead_id: str, situacao: str, motivo: str = "",
                       canal: str = "", dias=0, hoje: date | None = None) -> dict:
    situacao = str(situacao or "").strip().lower()
    if situacao not in SITUACOES:
        raise SituacaoInvalida(f"situação '{situacao}' não existe. Use: {', '.join(SITUACOES)}.")
    if not lead_id:
        raise SituacaoInvalida("conversa sem lead_id.")

    atual = situacao_do_lead(loja_id, lead_id)
    if atual and atual["situacao"] == "nao_contatar" and situacao != "nao_contatar":
        return atual          # só a loja desfaz, pelo painel

    hoje = hoje or date.today()
    retomar = (hoje + timedelta(days=_dias(dias))).isoformat() if situacao == "pediu_tempo" else None
    motivo = (motivo or "").strip()[:300]

    conexao = conectar()
    try:
        conexao.execute(
            """INSERT INTO situacao_lead (loja_id, lead_id, situacao, motivo, retomar_em)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (loja_id, lead_id) DO UPDATE SET
                   situacao = excluded.situacao,
                   motivo = excluded.motivo,
                   retomar_em = excluded.retomar_em,
                   atualizado_em = CURRENT_TIMESTAMP""",
            (loja_id, lead_id, situacao, motivo, retomar),
        )
        if situacao == "nao_contatar":
            conexao.execute(
                "INSERT OR IGNORE INTO optouts (loja_id, lead_id, canal, motivo) VALUES (?, ?, ?, ?)",
                (loja_id, lead_id, canal or "todos", motivo),
            )
        conexao.commit()
    finally:
        conexao.close()
    return situacao_do_lead(loja_id, lead_id)


def pode_contatar(loja_id: int, lead_id: str, hoje: date | None = None) -> bool:
    """A LOJA pode procurar este lead por conta própria? (usado na Etapa 2)"""
    conexao = conectar()
    try:
        bloqueado = conexao.execute(
            "SELECT 1 FROM optouts WHERE loja_id = ? AND lead_id = ? LIMIT 1",
            (loja_id, lead_id),
        ).fetchone()
    finally:
        conexao.close()
    if bloqueado:
        return False
    situacao = situacao_do_lead(loja_id, lead_id)
    if situacao is None:
        return True
    if situacao["situacao"] == "pediu_tempo" and situacao.get("retomar_em"):
        return (hoje or date.today()) >= date.fromisoformat(situacao["retomar_em"])
    return False


def reativar_contato(loja_id: int, lead_id: str) -> None:
    """Botão do painel: o cliente pediu pessoalmente para voltar a ser procurado."""
    conexao = conectar()
    try:
        conexao.execute("DELETE FROM situacao_lead WHERE loja_id = ? AND lead_id = ?", (loja_id, lead_id))
        conexao.execute("DELETE FROM optouts WHERE loja_id = ? AND lead_id = ?", (loja_id, lead_id))
        conexao.commit()
    finally:
        conexao.close()


def listar_situacoes(loja_id: int) -> list[dict]:
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT * FROM situacao_lead WHERE loja_id = ? ORDER BY atualizado_em DESC", (loja_id,)
        ).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]

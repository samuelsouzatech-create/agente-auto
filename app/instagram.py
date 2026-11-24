"""
Regras do Instagram que não são "porta" (IG1, Maratona 4). A porta é app/api/webhook_instagram.py;
o canal (ler e mandar) é app/channels/instagram.py.

- Eco (I3): a resposta que a CONTA da loja mandou volta como eco. Se o id é de uma bolha que o
  Léo mandou (mensagens.id_externo, migração 21), é descartado. Se não é, foi um vendedor
  respondendo pelo app do Instagram: a mensagem vai para a conversa e o Léo fica quieto
  (humano assumiu), até alguém devolver pelo painel ou o prazo de silêncio vencer.
- Origem do lead (I5): anuncio, perfil, comentario ou direto, gravada na primeira vez.
"""
from __future__ import annotations

from app.chaves import exigir_loja
from app.log import logger as _logger
from banco import conectar

_log = _logger("instagram")

CANAL = "instagram"
ORIGENS = ("anuncio", "perfil", "comentario", "direto")
AUTOR_DO_APP = "Vendedor (app do Instagram)"
NOME_SISTEMA = "Instagram"


def gravar_ids_do_leo(loja_id, lead_id: str, ids: list[str]) -> None:
    """Junta os ids das bolhas que o Léo acabou de mandar à última fala dele nesta conversa."""
    ids = [str(i).strip() for i in ids or [] if str(i).strip()]
    if not ids:
        return
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT id, id_externo FROM mensagens WHERE loja_id = ? AND lead_id = ? AND canal = ? "
            "AND direcao = 'leo' ORDER BY id DESC LIMIT 1", (loja_id, lead_id, CANAL)).fetchone()
        if linha is None:                         # nada gravado (não deveria): só avisa
            _log.warning(f"[Instagram][loja {loja_id}] ids enviados sem fala do Léo gravada.")
            return
        else:
            atuais = (linha["id_externo"] or "").split()
            novos = " ".join(atuais + [i for i in ids if i not in atuais])
            conexao.execute("UPDATE mensagens SET id_externo = ? WHERE id = ?", (novos, linha["id"]))
        conexao.commit()
    finally:
        conexao.close()


def e_eco_do_leo(loja_id, lead_id: str, id_externo: str) -> bool:
    if not id_externo:
        return False
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT 1 FROM mensagens WHERE loja_id = ? AND lead_id = ? AND canal = ? AND direcao = 'leo' "
            "AND id_externo IS NOT NULL AND strpos(' ' || id_externo || ' ', ' ' || ? || ' ') > 0 LIMIT 1",
            (loja_id, lead_id, CANAL, id_externo)).fetchone()
    finally:
        conexao.close()
    return linha is not None


def vendedor_respondeu_pelo_app(loja_id, lead_id: str, texto: str) -> None:
    """I3: o eco NÃO é do Léo: um vendedor respondeu pelo app. Grava na conversa e o Léo para."""
    from app.ator import como_sistema
    from app.handoff import assumir_conversa
    from app.mensagens import salvar_mensagem
    loja_id = exigir_loja(loja_id)
    salvar_mensagem(lead_id, "vendedor", texto or "[mensagem do vendedor pelo app]", canal=CANAL,
                    loja_id=loja_id, autor=AUTOR_DO_APP)
    with como_sistema(NOME_SISTEMA, "webhook"):
        assumir_conversa(lead_id, AUTOR_DO_APP, loja_id=loja_id)


def anotar_origem(loja_id, lead_id: str, origem: str, detalhe: str = "") -> None:
    """I5: de onde veio o lead. Só a PRIMEIRA origem fica (quem chegou por anúncio continua 'anúncio')."""
    if origem not in ORIGENS:
        return
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        conexao.execute(
            "INSERT INTO leads (lead_id, loja_id, origem, origem_detalhe) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (loja_id, lead_id) DO UPDATE SET "
            "origem = COALESCE(leads.origem, EXCLUDED.origem), "
            "origem_detalhe = COALESCE(leads.origem_detalhe, EXCLUDED.origem_detalhe)",
            (lead_id, loja_id, origem, detalhe or None))
        conexao.commit()
    finally:
        conexao.close()


def origem_do_lead(loja_id, lead_id: str) -> str | None:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linha = conexao.execute("SELECT origem FROM leads WHERE loja_id = ? AND lead_id = ?",
                                (loja_id, lead_id)).fetchone()
    finally:
        conexao.close()
    return linha["origem"] if linha else None

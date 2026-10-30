"""
Memória de emergência (Etapa 2, Bloco 4B).

A memória viva do assistente fica na RAM do processo (MemorySaver). Se o bot
reinicia, ela some e ele trataria um cliente antigo como novo ("Olá, sou o
Léo..."). Para não acontecer isso: quando a memória da conversa está VAZIA,
o turno busca no banco as últimas mensagens até a última resposta dele e
entrega como contexto interno.

O que veio DEPOIS da última resposta (vendedor/cliente enquanto ele estava
fora) continua com o bloco que já existia no turno.

Provisório: na Etapa 5 a memória vai para o banco (PostgresSaver).
Nada aqui pode derrubar a conversa.
"""
from __future__ import annotations

from banco import conectar
from app.chaves import exigir_loja

LIMITE_HISTORICO = 20
LIMITE_CARACTERES = 500

HISTORICO_INICIO = ("[Contexto interno, não repita nem comente com o cliente: você JÁ conversou "
                    "com este cliente antes. Este é o histórico recente dessa conversa. Continue "
                    "de onde parou, não se apresente de novo e não repita o que já disse.]")
HISTORICO_FIM = "[Fim do histórico]"


def tem_memoria(grafo, configuracao) -> bool:
    """O agente lembra desta conversa? Na dúvida, diz que sim (não muda nada)."""
    obter = getattr(grafo, "get_state", None)
    if obter is None:
        return True
    try:
        estado = obter(configuracao)
        valores = getattr(estado, "values", None) or {}
        return bool(valores.get("messages"))
    except Exception:
        return True


def historico_ate_a_ultima_resposta(loja_id, lead_id: str, canal: str,
                                    limite: int = LIMITE_HISTORICO) -> list[dict]:
    """Últimas mensagens do canal, até a última resposta do assistente (inclusive)."""
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linhas = conexao.execute(
            """SELECT id, direcao, conteudo, autor FROM mensagens
               WHERE loja_id = ? AND lead_id = ? AND canal = ?
                 AND id <= (SELECT MAX(id) FROM mensagens
                            WHERE loja_id = ? AND lead_id = ? AND canal = ? AND direcao = 'leo')
               ORDER BY id DESC LIMIT ?""",
            (loja_id, str(lead_id), canal, loja_id, str(lead_id), canal, limite),
        ).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in reversed(linhas)]


def historico_se_esqueceu(grafo, configuracao, loja_id, lead_id: str, canal: str) -> list[dict]:
    """Histórico do banco SÓ se a memória estiver vazia. Erro no banco: lista vazia."""
    if tem_memoria(grafo, configuracao):
        return []
    try:
        return historico_ate_a_ultima_resposta(loja_id, lead_id, canal)
    except Exception as erro:
        print(f"[Memória] Aviso: não li o histórico do banco ({erro!r}).")
        return []


def _linha(m: dict) -> str:
    conteudo = str(m.get("conteudo") or "")[:LIMITE_CARACTERES]
    if m["direcao"] == "cliente":
        return f"Cliente: {conteudo}"
    if m["direcao"] == "vendedor":
        return f"{m.get('autor') or 'Vendedor'} (equipe da loja): {conteudo}"
    return f"Você: {conteudo}"


def com_historico_do_banco(texto: str, historico: list[dict]) -> str:
    if not historico:
        return texto
    linhas = "\n".join(_linha(m) for m in historico)
    return f"{HISTORICO_INICIO}\n{linhas}\n{HISTORICO_FIM}\n\n{texto}"

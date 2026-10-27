"""
Persistência de mensagens da conversa (Fase 3, Bloco 1; Bloco 7A).

A memória viva do Léo continua no MemorySaver (RAM), para ele raciocinar.
Estas funções gravam uma CÓPIA de cada mensagem no banco, para o painel ler
o histórico (processo separado) e para o Léo saber o que o vendedor
conversou enquanto ele estava em silêncio.

direcao: 'cliente' (recebida), 'leo' (assistente) ou 'vendedor' (painel).
"""
from banco import conectar

DIRECOES = ("cliente", "leo", "vendedor")
LIMITE_CONTEXTO = 20


def salvar_mensagem(lead_id: str, direcao: str, conteudo: str,
                    canal: str = "", tipo: str = "texto",
                    loja_id: int = 1, autor: str | None = None) -> None:
    """Grava uma mensagem. Nunca levanta exceção (não derruba a conversa)."""
    try:
        conexao = conectar()
        conexao.execute(
            """INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo, autor)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (lead_id, loja_id, canal, direcao, tipo, conteudo, autor),
        )
        conexao.commit()
        conexao.close()
    except Exception as erro:
        print(f"[Mensagens] ERRO ao salvar mensagem de {lead_id}: {erro!r}")


def historico_do_lead(lead_id: str, loja_id: int = 1) -> list:
    """Todas as mensagens do lead, da mais antiga para a mais nova."""
    conexao = conectar()
    linhas = conexao.execute(
        """SELECT id, direcao, tipo, conteudo, canal, autor, criado_em
           FROM mensagens
           WHERE lead_id = ? AND loja_id = ?
           ORDER BY id ASC""",
        (lead_id, loja_id),
    ).fetchall()
    conexao.close()
    return [dict(l) for l in linhas]


def listar_leads(loja_id: int = 1) -> list:
    """Leads distintos que já trocaram mensagem (mais recente primeiro)."""
    conexao = conectar()
    linhas = conexao.execute(
        """SELECT lead_id,
                  MAX(criado_em) AS ultima_mensagem,
                  COUNT(*)       AS total_mensagens
           FROM mensagens
           WHERE loja_id = ?
           GROUP BY lead_id
           ORDER BY ultima_mensagem DESC""",
        (loja_id,),
    ).fetchall()
    conexao.close()
    return [dict(l) for l in linhas]


def listar_conversas(loja_id: int = 1) -> list:
    """Uma linha por lead, com o canal e a direção da última mensagem."""
    conexao = conectar()
    linhas = conexao.execute(
        """SELECT m.lead_id, m.canal, m.criado_em AS ultima_mensagem,
                  m.direcao AS ultima_direcao,
                  (SELECT COUNT(*) FROM mensagens x
                    WHERE x.loja_id = m.loja_id AND x.lead_id = m.lead_id) AS total_mensagens
           FROM mensagens m
           WHERE m.loja_id = ?
             AND m.id = (SELECT MAX(y.id) FROM mensagens y
                          WHERE y.loja_id = m.loja_id AND y.lead_id = m.lead_id)
           ORDER BY m.id DESC""",
        (loja_id,),
    ).fetchall()
    conexao.close()
    return [dict(l) for l in linhas]


def ja_respondeu(lead_id: str, loja_id: int = 1) -> bool:
    """A loja (assistente ou vendedor) já falou com este lead alguma vez?"""
    conexao = conectar()
    linha = conexao.execute(
        """SELECT 1 FROM mensagens
           WHERE lead_id = ? AND loja_id = ? AND direcao IN ('leo', 'vendedor')
           LIMIT 1""",
        (lead_id, loja_id),
    ).fetchone()
    conexao.close()
    return linha is not None


def mensagens_desde_a_ultima_resposta_do_leo(lead_id: str, loja_id: int = 1,
                                             limite: int = LIMITE_CONTEXTO) -> list:
    """O que aconteceu depois da última fala do Léo (cliente e vendedor
    conversando enquanto ele estava em silêncio). Sem fala do Léo: lista vazia."""
    conexao = conectar()
    linhas = conexao.execute(
        """SELECT id, direcao, conteudo, autor FROM mensagens
           WHERE lead_id = ? AND loja_id = ?
             AND id > (SELECT MAX(id) FROM mensagens
                        WHERE lead_id = ? AND loja_id = ? AND direcao = 'leo')
           ORDER BY id DESC
           LIMIT ?""",
        (lead_id, loja_id, lead_id, loja_id, limite),
    ).fetchall()
    conexao.close()
    return [dict(l) for l in reversed(linhas)]

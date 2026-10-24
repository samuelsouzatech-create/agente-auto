"""
Persistência de mensagens da conversa (Fase 3, Bloco 1).

A memória viva do Léo continua no MemorySaver (RAM), para ele raciocinar.
Estas funções gravam uma CÓPIA de cada mensagem no banco, para o painel do
vendedor conseguir ler o histórico — mesmo sendo um processo separado.
"""
from banco import conectar


def salvar_mensagem(lead_id: str, direcao: str, conteudo: str,
                    canal: str = "", tipo: str = "texto",
                    loja_id: int = 1) -> None:
    """Grava uma mensagem no histórico.
    - direcao: 'cliente' (recebida) ou 'leo' (enviada).
    - canal: 'whatsapp' ou 'telegram'.
    Nunca levanta exceção: se falhar, só avisa no log (não derruba a conversa)."""
    try:
        conexao = conectar()
        conexao.execute(
            """INSERT INTO mensagens (lead_id, loja_id, canal, direcao, tipo, conteudo)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (lead_id, loja_id, canal, direcao, tipo, conteudo),
        )
        conexao.commit()
        conexao.close()
    except Exception as erro:
        print(f"[Mensagens] ERRO ao salvar mensagem de {lead_id}: {erro!r}")


def historico_do_lead(lead_id: str, loja_id: int = 1) -> list:
    """Devolve todas as mensagens de um lead, em ordem (mais antiga primeiro).
    Cada item é um dict com direcao, tipo, conteudo, canal, criado_em."""
    conexao = conectar()
    linhas = conexao.execute(
        """SELECT direcao, tipo, conteudo, canal, criado_em
           FROM mensagens
           WHERE lead_id = ? AND loja_id = ?
           ORDER BY id ASC""",
        (lead_id, loja_id),
    ).fetchall()
    conexao.close()
    return [dict(l) for l in linhas]

def listar_leads(loja_id: int = 1) -> list:
    """Lista os leads distintos que já trocaram mensagem, com o momento
    da última mensagem (mais recente primeiro). Base pra tela de resultado."""
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

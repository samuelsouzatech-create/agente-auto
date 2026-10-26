"""Operações do operador sobre as lojas (Etapa 1, Bloco 5)."""
from banco import conectar


def listar_lojas() -> list[dict]:
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT id, nome, segmento, ativo, criado_em FROM lojas ORDER BY id"
        ).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]


def renomear_loja(loja_id: int, nome: str) -> bool:
    """Troca o nome da loja. Sobe a versão da configuração para o agente
    usar o nome novo já na próxima mensagem."""
    nome = (nome or "").strip()
    if not 1 <= len(nome) <= 80:
        raise ValueError("o nome precisa ter entre 1 e 80 caracteres")
    conexao = conectar()
    try:
        cursor = conexao.execute(
            "UPDATE lojas SET nome = ?, versao_config = versao_config + 1 WHERE id = ?",
            (nome, loja_id),
        )
        conexao.commit()
        return cursor.rowcount > 0
    finally:
        conexao.close()

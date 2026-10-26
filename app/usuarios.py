"""Vendedores e gestores de cada loja (Etapa 1, item 1.8).
No Bloco 7, quem tem contato de Telegram recebe o aviso de lead esperando."""
import re

from banco import conectar

PAPEIS = ("vendedor", "gestor")
_TELEGRAM = re.compile(r"^-?\d{5,20}$")


class UsuarioInvalido(ValueError):
    def __init__(self, erros: list[str]):
        self.erros = erros
        super().__init__("; ".join(erros))


def _normalizar(nome, papel, contato_telegram, contato_whatsapp):
    erros = []
    nome = (nome or "").strip()
    if not 1 <= len(nome) <= 80:
        erros.append("Nome: precisa ter entre 1 e 80 caracteres")
    if papel not in PAPEIS:
        erros.append(f"Papel: use {' ou '.join(PAPEIS)}")
    telegram = (contato_telegram or "").strip()
    if telegram and not _TELEGRAM.match(telegram):
        erros.append("Telegram: use o número do chat (só dígitos), ex.: 123456789")
    whatsapp = re.sub(r"\D", "", contato_whatsapp or "")
    if whatsapp and not 10 <= len(whatsapp) <= 15:
        erros.append("WhatsApp: número com DDI e DDD, ex.: 5581999998888")
    if erros:
        raise UsuarioInvalido(erros)
    return nome, papel, telegram or None, whatsapp or None


def criar_usuario(loja_id: int, nome: str, papel: str = "vendedor",
                  contato_telegram: str = "", contato_whatsapp: str = "") -> int:
    dados = _normalizar(nome, papel, contato_telegram, contato_whatsapp)
    conexao = conectar()
    try:
        if not conexao.execute("SELECT 1 FROM lojas WHERE id = ?", (loja_id,)).fetchone():
            raise UsuarioInvalido([f"Loja {loja_id} não existe"])
        cursor = conexao.execute(
            "INSERT INTO usuarios (loja_id, nome, papel, contato_telegram, contato_whatsapp) "
            "VALUES (?, ?, ?, ?, ?)",
            (loja_id, *dados),
        )
        conexao.commit()
        return cursor.lastrowid
    finally:
        conexao.close()


def atualizar_usuario(usuario_id: int, loja_id: int, nome: str, papel: str,
                      contato_telegram: str = "", contato_whatsapp: str = "") -> bool:
    """Só altera se o usuário for DESTA loja. Devolve False se não achou."""
    dados = _normalizar(nome, papel, contato_telegram, contato_whatsapp)
    conexao = conectar()
    try:
        cursor = conexao.execute(
            "UPDATE usuarios SET nome = ?, papel = ?, contato_telegram = ?, contato_whatsapp = ? "
            "WHERE id = ? AND loja_id = ?",
            (*dados, usuario_id, loja_id),
        )
        conexao.commit()
        return cursor.rowcount > 0
    finally:
        conexao.close()


def definir_ativo(usuario_id: int, loja_id: int, ativo: bool) -> bool:
    conexao = conectar()
    try:
        cursor = conexao.execute(
            "UPDATE usuarios SET ativo = ? WHERE id = ? AND loja_id = ?",
            (1 if ativo else 0, usuario_id, loja_id),
        )
        conexao.commit()
        return cursor.rowcount > 0
    finally:
        conexao.close()


def listar_usuarios(loja_id: int, incluir_inativos: bool = False) -> list[dict]:
    filtro = "" if incluir_inativos else " AND ativo = 1"
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT id, nome, papel, contato_telegram, contato_whatsapp, ativo, criado_em "
            f"FROM usuarios WHERE loja_id = ?{filtro} ORDER BY ativo DESC, papel, nome",
            (loja_id,),
        ).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]


def contatos_para_aviso(loja_id: int, papel: str = "vendedor") -> list[dict]:
    """Usuários ativos deste papel que têm Telegram (usado no Bloco 7)."""
    return [u for u in listar_usuarios(loja_id)
            if u["papel"] == papel and u["contato_telegram"]]

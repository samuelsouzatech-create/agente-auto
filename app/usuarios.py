"""Vendedores e gestores de cada loja (Etapa 1, item 1.8).
No Bloco 7, quem tem contato de Telegram recebe o aviso de lead esperando.

S4b (Fase 3): toda escrita (criar, alterar, desativar, reativar) exige um
ator (app/ator.py) e vai para o Registro na MESMA transação. Ator de uma
loja não mexe na equipe de outra.
Proteção de conflito: atualizar_usuario aceita 'esperado' (os valores que a
tela mostrou). Se o cadastro mudou desde então, levanta PessoaMudou e nada
é gravado. Quem não passa 'esperado' continua funcionando como antes.
Nada é apagado: quem sai é desativado.
"""
import re

from banco import conectar

PAPEIS = ("vendedor", "gestor", "dono")
ROTULOS_PAPEL = {"vendedor": "Vendedor", "gestor": "Gerente", "dono": "Dono"}
CAMPOS_DO_CADASTRO = ("nome", "papel", "contato_telegram", "contato_whatsapp")
_NO_REGISTRO = {"nome": "nome", "papel": "papel",
                "contato_telegram": "telegram", "contato_whatsapp": "whatsapp"}


def rotulo_papel(papel: str) -> str:
    """Como o papel aparece na tela (gestor aparece como Gerente)."""
    return ROTULOS_PAPEL.get(papel, papel)


_TELEGRAM = re.compile(r"^-?\d{5,20}$")


class UsuarioInvalido(ValueError):
    def __init__(self, erros: list[str]):
        self.erros = erros
        super().__init__("; ".join(erros))


class PessoaMudou(ValueError):
    """Outra pessoa mudou este cadastro enquanto a tela estava aberta (S4b)."""


def _normalizar(nome, papel, contato_telegram, contato_whatsapp):
    erros = []
    nome = (nome or "").strip()
    if not 1 <= len(nome) <= 80:
        erros.append("Nome: precisa ter entre 1 e 80 caracteres")
    if papel not in PAPEIS:
        erros.append(f"Papel: use {' ou '.join(ROTULOS_PAPEL[p] for p in PAPEIS)}")
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
    from app.registro import conferir_ator, registrar   # aqui dentro: evita import circular
    conexao = conectar()
    try:
        if not conexao.execute("SELECT 1 FROM lojas WHERE id = ?", (loja_id,)).fetchone():
            raise UsuarioInvalido([f"Loja {loja_id} não existe"])
        conferir_ator(loja_id)
        cursor = conexao.execute(
            "INSERT INTO usuarios (loja_id, nome, papel, contato_telegram, contato_whatsapp) "
            "VALUES (?, ?, ?, ?, ?)",
            (loja_id, *dados),
        )
        novo = cursor.lastrowid
        registrar("criar_pessoa_equipe", loja_id, None,
                  {_NO_REGISTRO[c]: v for c, v in zip(CAMPOS_DO_CADASTRO, dados)},
                  conexao=conexao, alvo=f"usuario:{novo}")
        conexao.commit()
        return novo
    finally:
        conexao.close()


def atualizar_usuario(usuario_id: int, loja_id: int, nome: str, papel: str,
                      contato_telegram: str = "", contato_whatsapp: str = "",
                      *, esperado: dict | None = None) -> bool:
    """Só altera se o usuário for DESTA loja. Devolve False se não achou.
    esperado: os valores que a tela mostrou; se mudaram, PessoaMudou."""
    dados = _normalizar(nome, papel, contato_telegram, contato_whatsapp)
    from app.registro import conferir_ator, registrar   # aqui dentro: evita import circular
    conferir_ator(loja_id)
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT nome, papel, contato_telegram, contato_whatsapp FROM usuarios "
            "WHERE id = ? AND loja_id = ?", (usuario_id, loja_id)).fetchone()
        if linha is None:
            return False
        if esperado is not None and any(linha[c] != esperado.get(c) for c in CAMPOS_DO_CADASTRO):
            raise PessoaMudou("Outra pessoa mudou este cadastro enquanto você editava. "
                              "Nada foi gravado.")
        novos = dict(zip(CAMPOS_DO_CADASTRO, dados))
        mudou = [c for c in CAMPOS_DO_CADASTRO if linha[c] != novos[c]]
        if not mudou:
            return True
        conexao.execute(
            "UPDATE usuarios SET nome = ?, papel = ?, contato_telegram = ?, contato_whatsapp = ? "
            "WHERE id = ? AND loja_id = ?",
            (*dados, usuario_id, loja_id),
        )
        registrar("alterar_pessoa_equipe", loja_id,
                  {_NO_REGISTRO[c]: linha[c] for c in mudou},
                  {**{_NO_REGISTRO[c]: novos[c] for c in mudou}, "pessoa": novos["nome"]},
                  conexao=conexao, alvo=f"usuario:{usuario_id}")
        conexao.commit()
        return True
    finally:
        conexao.close()


def definir_ativo(usuario_id: int, loja_id: int, ativo: bool) -> bool:
    """True se a pessoa é desta loja (mudando ou não); False se não achou.
    Só grava (e só vai para o Registro) quando o estado muda de verdade."""
    from app.registro import conferir_ator, registrar   # aqui dentro: evita import circular
    conferir_ator(loja_id)
    novo = 1 if ativo else 0
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT nome, papel, ativo FROM usuarios WHERE id = ? AND loja_id = ?",
            (usuario_id, loja_id)).fetchone()
        if linha is None:
            return False
        if int(linha["ativo"]) == novo:
            return True
        conexao.execute("UPDATE usuarios SET ativo = ? WHERE id = ? AND loja_id = ?",
                        (novo, usuario_id, loja_id))
        registrar("reativar_pessoa_equipe" if novo else "desativar_pessoa_equipe", loja_id,
                  {"ativo": bool(linha["ativo"])},
                  {"ativo": bool(novo), "nome": linha["nome"], "papel": linha["papel"]},
                  conexao=conexao, alvo=f"usuario:{usuario_id}")
        conexao.commit()
        return True
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

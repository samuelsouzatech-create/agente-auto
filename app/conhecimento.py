"""
Base de conhecimento por loja (Etapa 1, item 1.8).

A tabela 'conhecimento' é a fonte da verdade. O Chroma é só o índice de busca:
cada pedaço leva loja_id e documento_id. Ao salvar, os pedaços antigos daquele
documento são apagados e os novos entram no lugar.
"""
from langchain_text_splitters import RecursiveCharacterTextSplitter

from banco import conectar

TAMANHO_PEDACO = 500
SOBREPOSICAO = 100


class DocumentoInvalido(ValueError):
    def __init__(self, erros: list[str]):
        self.erros = erros
        super().__init__("; ".join(erros))


class DocumentoNaoEncontrado(LookupError):
    pass


class ErroIndexacao(RuntimeError):
    """O texto foi salvo no banco, mas não entrou no índice de busca."""


def _indice():
    """O mesmo Chroma que a tool buscar_conhecimento usa (os testes trocam por um falso)."""
    from tools.buscar_conhecimento import _get_banco_conhecimento
    return _get_banco_conhecimento()


def _id_indice(doc_id: int) -> str:
    return f"doc:{doc_id}"


def dividir(texto: str) -> list[str]:
    divisor = RecursiveCharacterTextSplitter(chunk_size=TAMANHO_PEDACO, chunk_overlap=SOBREPOSICAO)
    return divisor.split_text(texto)


def remover_do_indice(doc_id: int, indice=None) -> None:
    indice = indice or _indice()
    achados = indice.get(where={"documento_id": _id_indice(doc_id)})
    if achados["ids"]:
        indice.delete(ids=achados["ids"])


def indexar(loja_id: int, doc_id: int, titulo: str, texto: str) -> None:
    indice = _indice()
    remover_do_indice(doc_id, indice)
    pedacos = dividir(texto)
    if pedacos:
        indice.add_texts(
            pedacos,
            metadatas=[{"loja_id": int(loja_id), "documento_id": _id_indice(doc_id), "fonte": titulo}
                       for _ in pedacos],
            ids=[f"{_id_indice(doc_id)}:{i}" for i in range(len(pedacos))],
        )


def _validar(titulo: str, texto: str) -> tuple[str, str]:
    titulo, texto = (titulo or "").strip(), (texto or "").strip()
    erros = []
    if not 1 <= len(titulo) <= 120:
        erros.append("Título: precisa ter entre 1 e 120 caracteres")
    if not 1 <= len(texto) <= 50_000:
        erros.append("Texto: não pode ficar vazio (máximo de 50.000 caracteres)")
    if erros:
        raise DocumentoInvalido(erros)
    return titulo, texto


def gravar(loja_id: int, titulo: str, texto: str, doc_id: int | None = None) -> int:
    """Grava só no banco (sem indexar). Devolve o id do documento."""
    titulo, texto = _validar(titulo, texto)
    conexao = conectar()
    try:
        if doc_id is None:
            cursor = conexao.execute(
                "INSERT INTO conhecimento (loja_id, titulo, texto) VALUES (?, ?, ?)",
                (loja_id, titulo, texto),
            )
            doc_id = cursor.lastrowid
        else:
            cursor = conexao.execute(
                "UPDATE conhecimento SET titulo = ?, texto = ?, atualizado_em = CURRENT_TIMESTAMP "
                "WHERE id = ? AND loja_id = ?",
                (titulo, texto, doc_id, loja_id),
            )
            if cursor.rowcount == 0:
                raise DocumentoNaoEncontrado(f"Documento {doc_id} não existe nesta loja.")
        conexao.commit()
        return doc_id
    finally:
        conexao.close()


def salvar_documento(loja_id: int, titulo: str, texto: str, doc_id: int | None = None) -> int:
    """Grava no banco e indexa. Se a indexação falhar, o texto NÃO se perde."""
    doc_id = gravar(loja_id, titulo, texto, doc_id)
    try:
        indexar(loja_id, doc_id, titulo.strip(), texto.strip())
    except Exception as erro:
        raise ErroIndexacao(str(erro)) from erro
    return doc_id


def apagar_documento(loja_id: int, doc_id: int) -> bool:
    conexao = conectar()
    try:
        cursor = conexao.execute(
            "DELETE FROM conhecimento WHERE id = ? AND loja_id = ?", (doc_id, loja_id)
        )
        conexao.commit()
        apagou = cursor.rowcount > 0
    finally:
        conexao.close()
    if apagou:
        try:
            remover_do_indice(doc_id)
        except Exception as erro:
            raise ErroIndexacao(str(erro)) from erro
    return apagou


def listar_documentos(loja_id: int) -> list[dict]:
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT id, titulo, texto, atualizado_em FROM conhecimento "
            "WHERE loja_id = ? ORDER BY titulo",
            (loja_id,),
        ).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]


def existe_titulo(loja_id: int, titulo: str) -> bool:
    conexao = conectar()
    try:
        return conexao.execute(
            "SELECT 1 FROM conhecimento WHERE loja_id = ? AND titulo = ?", (loja_id, titulo)
        ).fetchone() is not None
    finally:
        conexao.close()


def todos_os_documentos() -> list[dict]:
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT id, loja_id, titulo, texto FROM conhecimento ORDER BY loja_id, id"
        ).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]

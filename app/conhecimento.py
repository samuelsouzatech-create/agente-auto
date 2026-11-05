"""
Base de conhecimento por loja (Etapa 1, item 1.8; S4c da Fase 3).

A tabela 'conhecimento' é a fonte da verdade. O Chroma é só o índice de busca:
cada pedaço leva loja_id e documento_id. Ao salvar, os pedaços antigos daquele
documento são apagados e os novos entram no lugar.

S4c: criar, alterar e apagar exigem ator e vão para o Registro na MESMA
transação da escrita no banco (criar_documento, alterar_documento,
apagar_documento; alvo "documento:{id}"). O texto inteiro fica no Registro
(antes/depois) para o Desfazer. O índice é atualizado DEPOIS do commit: se
falhar, o texto não se perde (ErroIndexacao) e reindexar_loja conserta.
Proteção de conflito: 'esperado' = {"titulo", "texto"} que a tela mostrou.
"""
from langchain_text_splitters import RecursiveCharacterTextSplitter

from banco import conectar

TAMANHO_PEDACO = 500
SOBREPOSICAO = 100
ACOES = ("criar_documento", "alterar_documento", "apagar_documento")


class DocumentoInvalido(ValueError):
    def __init__(self, erros: list[str]):
        self.erros = erros
        super().__init__("; ".join(erros))


class DocumentoNaoEncontrado(LookupError):
    pass


class DocumentoMudou(ValueError):
    """Outra pessoa mudou este documento enquanto a tela estava aberta (S4c)."""


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


def _linha(conexao, loja_id, doc_id):
    return conexao.execute("SELECT id, titulo, texto FROM conhecimento WHERE id = ? AND loja_id = ?",
                           (doc_id, loja_id)).fetchone()


def _confere(atual, esperado) -> None:
    if esperado is not None and (atual["titulo"], atual["texto"]) != (
            esperado.get("titulo"), esperado.get("texto")):
        raise DocumentoMudou("Outra pessoa mudou este documento enquanto você editava. "
                             "Nada foi gravado.")


def gravar(loja_id: int, titulo: str, texto: str, doc_id: int | None = None,
           *, esperado: dict | None = None) -> int:
    """Grava só no banco (sem indexar), com Registro. Devolve o id do documento."""
    titulo, texto = _validar(titulo, texto)
    from app.registro import conferir_ator, registrar   # aqui dentro: evita import circular
    conferir_ator(loja_id)
    conexao = conectar()
    try:
        if doc_id is None:
            if not conexao.execute("SELECT 1 FROM lojas WHERE id = ?", (loja_id,)).fetchone():
                raise DocumentoNaoEncontrado(f"A loja {loja_id} não existe.")
            doc_id = conexao.execute(
                "INSERT INTO conhecimento (loja_id, titulo, texto) VALUES (?, ?, ?)",
                (loja_id, titulo, texto)).lastrowid
            registrar("criar_documento", loja_id, None, {"titulo": titulo, "texto": texto},
                      conexao=conexao, alvo=f"documento:{doc_id}")
        else:
            atual = _linha(conexao, loja_id, doc_id)
            if atual is None:
                raise DocumentoNaoEncontrado(f"Documento {doc_id} não existe nesta loja.")
            _confere(atual, esperado)
            if (atual["titulo"], atual["texto"]) == (titulo, texto):
                return doc_id
            conexao.execute(
                "UPDATE conhecimento SET titulo = ?, texto = ?, atualizado_em = CURRENT_TIMESTAMP "
                "WHERE id = ? AND loja_id = ?", (titulo, texto, doc_id, loja_id))
            registrar("alterar_documento", loja_id,
                      {"titulo": atual["titulo"], "texto": atual["texto"]},
                      {"titulo": titulo, "texto": texto},
                      conexao=conexao, alvo=f"documento:{doc_id}")
        conexao.commit()
        return doc_id
    finally:
        conexao.close()


def salvar_documento(loja_id: int, titulo: str, texto: str, doc_id: int | None = None,
                     *, esperado: dict | None = None) -> int:
    """Grava no banco e indexa. Se a indexação falhar, o texto NÃO se perde."""
    doc_id = gravar(loja_id, titulo, texto, doc_id, esperado=esperado)
    try:
        indexar(loja_id, doc_id, titulo.strip(), texto.strip())
    except Exception as erro:
        raise ErroIndexacao(str(erro)) from erro
    return doc_id


def apagar_documento(loja_id: int, doc_id: int, *, esperado: dict | None = None) -> bool:
    from app.registro import conferir_ator, registrar   # aqui dentro: evita import circular
    conferir_ator(loja_id)
    conexao = conectar()
    try:
        atual = _linha(conexao, loja_id, doc_id)
        if atual is None:
            return False
        _confere(atual, esperado)
        conexao.execute("DELETE FROM conhecimento WHERE id = ? AND loja_id = ?", (doc_id, loja_id))
        registrar("apagar_documento", loja_id,
                  {"titulo": atual["titulo"], "texto": atual["texto"]},
                  {"apagado": True, "titulo": atual["titulo"]},
                  conexao=conexao, alvo=f"documento:{doc_id}")
        conexao.commit()
    finally:
        conexao.close()
    try:
        remover_do_indice(doc_id)
    except Exception as erro:
        raise ErroIndexacao(str(erro)) from erro
    return True


def reindexar_loja(loja_id: int) -> int:
    """Refaz o índice SÓ desta loja a partir do banco (não apaga a pasta)."""
    from app.chaves import exigir_loja
    loja_id = exigir_loja(loja_id)
    try:
        indice = _indice()
        achados = indice.get(where={"loja_id": int(loja_id)})
        if achados["ids"]:
            indice.delete(ids=achados["ids"])
        documentos = listar_documentos(loja_id)
        for d in documentos:
            indexar(loja_id, d["id"], d["titulo"], d["texto"])
    except Exception as erro:
        raise ErroIndexacao(str(erro)) from erro
    return len(documentos)


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

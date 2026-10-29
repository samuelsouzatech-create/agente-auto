"""
Modelos de mensagem (templates da Meta) - Etapa 2, Bloco 1.

O registro fica na pasta do segmento (segmentos/<segmento>/modelos.json).
O mesmo arquivo serve para submeter à Meta e para os testes: o texto testado
é o texto aprovado. Variáveis no texto: {nome}, {carro}, {agente}, {loja},
{oficina}. Na Meta viram parâmetros NOMEADOS ({{nome}}).

O status de aprovação é POR LOJA (cada loja tem a própria conta na Meta),
na tabela modelos_loja. Modelo que não está 'aprovado' não sai fora do
modo de teste (quem confere é o job, Bloco 3).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from banco import conectar
from app.chaves import exigir_loja
from app.lojas import carregar_loja
from app.segmentos import pasta_do_segmento

ARQUIVO = "modelos.json"
IDIOMA_PADRAO = "pt_BR"
CATEGORIAS = ("marketing", "utilidade")
CATEGORIA_NA_META = {"marketing": "marketing", "utilidade": "utility"}
VARIAVEIS = ("nome", "carro", "agente", "loja", "oficina")
STATUS = ("rascunho", "submetido", "aprovado", "rejeitado")
LIMITE_TEXTO = 1024          # limite do corpo do modelo: conferir na documentação atual
_NOME = re.compile(r"^[a-z0-9_]{1,512}$")
_VARIAVEL = re.compile(r"\{([a-z_]+)\}")
_ESPACOS = re.compile(r"\s+")


class ModeloInvalido(ValueError):
    """O modelos.json tem algo fora das regras (o arquivo inteiro é recusado)."""


class ModeloInexistente(LookupError):
    pass


class ValoresFaltando(ValueError):
    pass


@dataclass(frozen=True)
class Modelo:
    nome: str
    categoria: str
    idioma: str
    objetivo: str
    texto: str
    variaveis: tuple[str, ...]


def _variaveis_do_texto(texto: str) -> tuple[str, ...]:
    vistas = []
    for v in _VARIAVEL.findall(texto):
        if v not in vistas:
            vistas.append(v)
    return tuple(vistas)


def _validar(item, idioma_padrao: str, origem: str) -> Modelo:
    if not isinstance(item, dict):
        raise ModeloInvalido(f"{origem}: cada modelo precisa ser um objeto")
    nome = item.get("nome")
    if not isinstance(nome, str) or not _NOME.match(nome):
        raise ModeloInvalido(f"{origem}: nome '{nome}' inválido (minúsculas, números e _)")
    onde = f"{origem}, modelo {nome}"
    categoria = item.get("categoria")
    if categoria not in CATEGORIAS:
        raise ModeloInvalido(f"{onde}: categoria '{categoria}' inválida ({', '.join(CATEGORIAS)})")
    texto = item.get("texto")
    if not isinstance(texto, str) or not texto.strip():
        raise ModeloInvalido(f"{onde}: texto vazio")
    texto = texto.strip()
    if len(texto) > LIMITE_TEXTO:
        raise ModeloInvalido(f"{onde}: texto com mais de {LIMITE_TEXTO} caracteres")
    variaveis = _variaveis_do_texto(texto)
    desconhecidas = [v for v in variaveis if v not in VARIAVEIS]
    if desconhecidas:
        raise ModeloInvalido(f"{onde}: variável desconhecida {{{desconhecidas[0]}}} "
                             f"(válidas: {', '.join(VARIAVEIS)})")
    if "{" in _VARIAVEL.sub("", texto) or "}" in _VARIAVEL.sub("", texto):
        raise ModeloInvalido(f"{onde}: chave solta no texto (use só {{nome}}, {{carro}}...)")
    if texto.startswith("{") or texto.endswith("}"):
        raise ModeloInvalido(f"{onde}: a Meta recusa modelo que começa ou termina com variável")
    idioma = item.get("idioma") or idioma_padrao
    return Modelo(nome=nome, categoria=categoria, idioma=str(idioma),
                  objetivo=str(item.get("objetivo") or ""), texto=texto, variaveis=variaveis)


def _ler_arquivo(segmento: str) -> dict:
    caminho = pasta_do_segmento(segmento) / ARQUIVO
    if not caminho.is_file():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as erro:
        raise ModeloInvalido(f"{caminho.name} de {segmento}: JSON inválido ({erro})")
    if not isinstance(dados, dict):
        raise ModeloInvalido(f"{caminho.name} de {segmento}: precisa ser um objeto")
    return dados


_cache: dict[str, tuple[int, dict]] = {}


def carregar_modelos(segmento: str) -> dict[str, Modelo]:
    """Modelos do segmento, validados. Segmento sem modelos.json: {}."""
    caminho = pasta_do_segmento(segmento) / ARQUIVO
    if not caminho.is_file():
        return {}
    chave, modificado = str(caminho), caminho.stat().st_mtime_ns
    guardado = _cache.get(chave)
    if guardado and guardado[0] == modificado:
        return dict(guardado[1])
    dados = _ler_arquivo(segmento)
    lista = dados.get("modelos")
    if not isinstance(lista, list):
        raise ModeloInvalido(f"modelos.json de {segmento}: falta a lista 'modelos'")
    idioma = str(dados.get("idioma_padrao") or IDIOMA_PADRAO)
    modelos: dict[str, Modelo] = {}
    for item in lista:
        modelo = _validar(item, idioma, f"modelos.json de {segmento}")
        if modelo.nome in modelos:
            raise ModeloInvalido(f"modelos.json de {segmento}: nome repetido {modelo.nome}")
        modelos[modelo.nome] = modelo
    _cache[chave] = (modificado, modelos)
    return dict(modelos)


def exemplos_do_segmento(segmento: str) -> dict:
    exemplos = _ler_arquivo(segmento).get("exemplos") or {}
    return dict(exemplos) if isinstance(exemplos, dict) else {}


def modelo_do_segmento(segmento: str, nome: str) -> Modelo:
    modelos = carregar_modelos(segmento)
    if nome not in modelos:
        raise ModeloInexistente(f"O segmento {segmento} não tem o modelo '{nome}'.")
    return modelos[nome]


def modelos_da_loja(loja_id) -> dict[str, Modelo]:
    return carregar_modelos(carregar_loja(exigir_loja(loja_id)).segmento)


# ------------------------------------------------------------ preencher

def _limpar_valor(valor) -> str:
    """A Meta recusa parâmetro com quebra de linha ou espaços em excesso."""
    return _ESPACOS.sub(" ", str(valor if valor is not None else "")).strip()


def preencher(modelo: Modelo, valores: dict) -> str:
    valores = valores or {}
    faltando = [v for v in modelo.variaveis if not _limpar_valor(valores.get(v))]
    if faltando:
        raise ValoresFaltando(f"O modelo {modelo.nome} precisa de: {', '.join(faltando)}.")
    return _VARIAVEL.sub(lambda m: _limpar_valor(valores[m.group(1)]), modelo.texto)


def parametros_meta(modelo: Modelo, valores: dict) -> list[dict]:
    """Parâmetros nomeados do envio (componente body)."""
    preencher(modelo, valores)      # valida antes
    return [{"type": "text", "parameter_name": v, "text": _limpar_valor(valores[v])}
            for v in modelo.variaveis]


def corpo_de_criacao(modelo: Modelo, exemplos: dict) -> dict:
    """Pedido de criação do modelo na Meta (parâmetros nomeados, com exemplos)."""
    texto = _VARIAVEL.sub(lambda m: "{{" + m.group(1) + "}}", modelo.texto)
    componente = {"type": "body", "text": texto}
    if modelo.variaveis:
        componente["example"] = {"body_text_named_params": [
            {"param_name": v, "example": str(exemplos.get(v, v))} for v in modelo.variaveis]}
    return {
        "name": modelo.nome,
        "language": modelo.idioma,
        "category": CATEGORIA_NA_META[modelo.categoria],
        "parameter_format": "named",
        "components": [componente],
    }


# ------------------------------------------------ status por loja

def registrar_status(loja_id, nome: str, status: str, *, categoria_efetiva: str | None = None,
                     idioma: str = IDIOMA_PADRAO) -> None:
    loja_id = exigir_loja(loja_id)
    if status not in STATUS:
        raise ValueError(f"status '{status}' inválido ({', '.join(STATUS)})")
    if categoria_efetiva is not None and categoria_efetiva not in CATEGORIAS:
        raise ValueError(f"categoria '{categoria_efetiva}' inválida ({', '.join(CATEGORIAS)})")
    if nome not in modelos_da_loja(loja_id):
        raise ModeloInexistente(f"O segmento da loja {loja_id} não tem o modelo '{nome}'.")
    conexao = conectar()
    try:
        conexao.execute(
            """INSERT INTO modelos_loja (loja_id, nome, idioma, status, categoria_efetiva)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (loja_id, nome, idioma) DO UPDATE SET
                   status = excluded.status,
                   categoria_efetiva = COALESCE(excluded.categoria_efetiva,
                                                modelos_loja.categoria_efetiva),
                   atualizado_em = CURRENT_TIMESTAMP""",
            (loja_id, nome, idioma, status, categoria_efetiva),
        )
        conexao.commit()
    finally:
        conexao.close()


def status_do_modelo(loja_id, nome: str, idioma: str = IDIOMA_PADRAO) -> dict | None:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT * FROM modelos_loja WHERE loja_id = ? AND nome = ? AND idioma = ?",
            (loja_id, nome, idioma),
        ).fetchone()
    finally:
        conexao.close()
    return dict(linha) if linha else None


def modelo_aprovado(loja_id, nome: str, idioma: str = IDIOMA_PADRAO) -> bool:
    status = status_do_modelo(loja_id, nome, idioma)
    return bool(status and status["status"] == "aprovado")


def categoria_para_custo(loja_id, modelo: Modelo) -> str:
    """A categoria que a Meta decidiu manda no custo; sem status, a do registro."""
    status = status_do_modelo(loja_id, modelo.nome, modelo.idioma)
    return (status or {}).get("categoria_efetiva") or modelo.categoria


def listar_status(loja_id) -> list[dict]:
    """Todos os modelos do segmento da loja com o status (rascunho se nunca submetido)."""
    loja_id = exigir_loja(loja_id)
    linhas = []
    for modelo in modelos_da_loja(loja_id).values():
        status = status_do_modelo(loja_id, modelo.nome, modelo.idioma) or {}
        linhas.append({
            "nome": modelo.nome, "objetivo": modelo.objetivo, "categoria_pedida": modelo.categoria,
            "status": status.get("status", "rascunho"),
            "categoria_efetiva": status.get("categoria_efetiva"),
        })
    return linhas

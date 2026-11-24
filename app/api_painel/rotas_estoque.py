"""
Rotas do C2d, parte 2: Estoque (GET, POST, PUT).

- Só dono e gerente, e só com o módulo estoque ligado (D2).
- "vendido" nunca entra por aqui (P2): só por Registrar venda, na conversa.
- Carro vendido não se edita pela API (422).
- PUT com "esperado": se o carro mudou desde que a tela abriu, 409 e nada muda.
- Quem age vem da sessão (ator 'cliente', origem 'api'): cadastrar_carro e
  alterar_carro vão para o Registro na mesma transação (S4c).
- Fotos iguais (mesmos links, na mesma ordem) não viram alteração no Registro.
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel

from app import estoque
from app.api_painel.carros import (TAMANHO_PADRAO, fotos_para_o_painel, interessados, montar_carro,
                                   montar_estoque, valores_da_api)
from app.api_painel.erros import ErroApi
from app.api_painel.modulos import ESTOQUE, escrita, leitura
from app.ator import como
from app import fotos as _fotos
from app.estoque import FotosInvalidas

MAX_TEXTO = 60
ANO_MINIMO = 1950
MAX_KM = 2_000_000
MAX_PRECO = 10_000_000
USE_VENDA = "Para marcar como vendido, use Registrar venda na conversa do cliente."
CARRO_NAO_ENCONTRADO = "Não encontramos esse carro."
CARRO_MUDOU = "Outra pessoa mudou este carro enquanto você editava. Recarregue e tente de novo."

router = APIRouter(tags=["Estoque"])


class CarroEntrada(BaseModel):
    marca: str = ""
    modelo: str = ""
    ano: int = 0
    km: int = 0
    cor: str = ""
    cambio: str = ""
    preco: float = 0
    status: str = "disponivel"
    fotos: List[str] = []


class CarroEdicao(BaseModel):
    dados: CarroEntrada
    esperado: Optional[dict] = None


def _como(sessao: dict):
    return como(sessao["nome"], "cliente", "api", sessao["loja_id"])


def _texto(valor) -> str:
    return " ".join(str(valor or "").split())


def validar(entrada: CarroEntrada, loja_id: int) -> dict:
    if entrada.status == estoque.VENDIDO:
        raise ErroApi("invalido", {"status": "Use Registrar venda."}, USE_VENDA)
    campos = {}
    textos = {c: _texto(getattr(entrada, c)) for c in ("marca", "modelo", "cor")}
    for campo, valor in textos.items():
        if not valor:
            campos[campo] = "Preencha este campo."
        elif len(valor) > MAX_TEXTO:
            campos[campo] = f"No máximo {MAX_TEXTO} caracteres."
    ano_maximo = date.today().year + 1
    if not ANO_MINIMO <= entrada.ano <= ano_maximo:
        campos["ano"] = f"Entre {ANO_MINIMO} e {ano_maximo}."
    if not 0 <= entrada.km <= MAX_KM:
        campos["km"] = "Quilometragem inválida."
    if entrada.cambio not in estoque.OPCOES_CAMBIO:
        campos["cambio"] = "Escolha " + " ou ".join(estoque.OPCOES_CAMBIO) + "."
    if not 0 < entrada.preco <= MAX_PRECO:
        campos["preco"] = "Informe o preço."
    if entrada.status not in estoque.OPCOES_STATUS:
        campos["status"] = "Escolha Disponível, Reservado ou Indisponível."
    fotos = [_texto(u) for u in entrada.fotos if _texto(u)]
    if len(fotos) > _fotos.MAX_FOTOS_POR_CARRO:
        campos["fotos"] = _fotos.MSG_DEMAIS
    if any("," in u for u in fotos):
        campos["fotos"] = _fotos.MSG_LINK
    if campos:
        raise ErroApi("invalido", campos)
    # Maratona Fotos: as fotos passam pelo preparo único dentro de app/estoque.py (endereço de
    # foto desta loja vira a referência do depósito; link https de fora é baixado e preparado).
    return {**textos, "ano": entrada.ano, "km": entrada.km, "cambio": entrada.cambio,
            "preco": float(entrada.preco), "status": entrada.status,
            "fotos": _fotos.juntar(fotos)}


def _erro_das_fotos(erro: FotosInvalidas) -> ErroApi:
    return ErroApi("invalido", {"fotos": str(erro)}, str(erro))


def _carro_da_loja(loja_id: int, carro_id: int) -> dict:
    carro = estoque.buscar_carro(carro_id, loja_id)
    if carro is None:
        raise ErroApi("nao_encontrado", mensagem=CARRO_NAO_ENCONTRADO)
    return carro


def _resposta(loja_id: int, carro_id: int) -> dict:
    return montar_carro(_carro_da_loja(loja_id, carro_id), interessados(loja_id))


@router.get("/estoque")
def listar(pagina: int = 1, tamanho: int = TAMANHO_PADRAO,
           sessao: dict = Depends(leitura(ESTOQUE))):
    return montar_estoque(sessao["loja_id"], pagina, tamanho)


@router.post("/estoque", status_code=201)
def cadastrar(entrada: CarroEntrada, sessao: dict = Depends(escrita(ESTOQUE))):
    loja_id = sessao["loja_id"]
    dados = validar(entrada, loja_id)
    with _como(sessao):
        try:
            novo = estoque.adicionar_carro(**dados, loja_id=loja_id)
        except FotosInvalidas as erro:
            raise _erro_das_fotos(erro) from None
        except estoque.StatusInvalido as erro:
            raise ErroApi("invalido", {"status": str(erro)}, str(erro)) from None
    return _resposta(loja_id, novo)


@router.put("/estoque/{id}")
def editar(id: int, entrada: CarroEdicao, sessao: dict = Depends(escrita(ESTOQUE))):
    loja_id = sessao["loja_id"]
    atual = _carro_da_loja(loja_id, id)
    if atual["status"] == estoque.VENDIDO:
        raise ErroApi("invalido", mensagem=estoque.MENSAGEM_JA_VENDIDO)
    dados = validar(entrada.dados, loja_id)
    esperado = None
    if entrada.esperado is not None:
        esperado = {**entrada.esperado}
        if isinstance(esperado.get("fotos"), list):
            esperado["fotos"] = ", ".join(esperado["fotos"])
        if valores_da_api(atual)["fotos"] == [u.strip() for u in
                                              str(esperado.get("fotos", "")).split(",")
                                              if u.strip()]:
            esperado["fotos"] = estoque.valores_do_carro(atual)["fotos"]
    with _como(sessao):
        try:
            estoque.atualizar_carro(id, **dados, loja_id=loja_id, esperado=esperado)
        except FotosInvalidas as erro:
            raise _erro_das_fotos(erro) from None
        except estoque.CarroMudou:
            raise ErroApi("conflito", mensagem=CARRO_MUDOU) from None
        except estoque.StatusInvalido as erro:
            raise ErroApi("invalido", {"status": str(erro)}, str(erro)) from None
    return _resposta(loja_id, id)


# ------------------------------------------------------------ fotos do carro (Maratona Fotos, F2)

class FotoPorLinkEntrada(BaseModel):
    link: str = ""


class OrdemDasFotosEntrada(BaseModel):
    fotos: List[str] = []


def _fotos_do_carro(loja_id: int, refs: list, recusadas: list | None = None) -> dict:
    return {"fotos": fotos_para_o_painel(loja_id, _fotos.juntar(refs)),
            "recusadas": [{"arquivo": n, "mensagem": m} for n, m in (recusadas or [])]}


def _fazer(sessao: dict, campo: str, acao):
    """Roda a operação de foto com o ator da sessão e traduz os erros para o contrato."""
    with _como(sessao):
        try:
            return acao()
        except estoque.CarroNaoEncontrado as erro:
            raise ErroApi("nao_encontrado", mensagem=str(erro)) from None
        except estoque.StatusInvalido as erro:
            raise ErroApi("invalido", mensagem=str(erro)) from None
        except FotosInvalidas as erro:
            raise ErroApi("invalido", {campo: str(erro)}, str(erro)) from None


def _ler_arquivo(arquivo: UploadFile) -> bytes:
    """Lê no máximo o limite + 1 byte (passou do limite, o preparo recusa sem ler o resto)."""
    return arquivo.file.read(_fotos.MAX_BYTES + 1)


@router.post("/estoque/{id}/fotos", status_code=201)
def enviar_fotos(id: int, arquivos: List[UploadFile] = File(...), sessao: dict = Depends(escrita(ESTOQUE))):
    loja_id = sessao["loja_id"]
    if len(arquivos) > _fotos.MAX_FOTOS_POR_CARRO:
        raise ErroApi("invalido", {"arquivos": _fotos.MSG_DEMAIS}, _fotos.MSG_DEMAIS)
    lidos = [(a.filename or "foto", _ler_arquivo(a)) for a in arquivos]
    refs, recusadas = _fazer(sessao, "arquivos", lambda: estoque.adicionar_fotos(id, lidos, loja_id=loja_id))
    return _fotos_do_carro(loja_id, refs, recusadas)


@router.post("/estoque/{id}/fotos/link", status_code=201)
def adicionar_por_link(id: int, entrada: FotoPorLinkEntrada, sessao: dict = Depends(escrita(ESTOQUE))):
    loja_id = sessao["loja_id"]
    refs = _fazer(sessao, "link", lambda: estoque.adicionar_foto_por_link(id, entrada.link, loja_id=loja_id))
    return _fotos_do_carro(loja_id, refs)


@router.put("/estoque/{id}/fotos/ordem")
def mudar_ordem(id: int, entrada: OrdemDasFotosEntrada, sessao: dict = Depends(escrita(ESTOQUE))):
    loja_id = sessao["loja_id"]
    refs = _fazer(sessao, "fotos", lambda: estoque.ordenar_fotos(id, entrada.fotos, loja_id=loja_id))
    return _fotos_do_carro(loja_id, refs)


@router.delete("/estoque/{id}/fotos/{nome}")
def apagar_foto(id: int, nome: str, sessao: dict = Depends(escrita(ESTOQUE))):
    loja_id = sessao["loja_id"]
    refs = _fazer(sessao, "fotos", lambda: estoque.apagar_foto(id, nome, loja_id=loja_id))
    return _fotos_do_carro(loja_id, refs)

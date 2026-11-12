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

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import estoque
from app.api_painel.carros import (TAMANHO_PADRAO, interessados, montar_carro, montar_estoque,
                                   valores_da_api)
from app.api_painel.erros import ErroApi
from app.api_painel.modulos import ESTOQUE, escrita, leitura
from app.ator import como

MAX_TEXTO = 60
MAX_FOTOS = 20
MAX_URL = 500
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


def _foto_ruim(url: str) -> bool:
    return (not url.startswith(("https://", "http://")) or "," in url or " " in url
            or len(url) > MAX_URL)


def validar(entrada: CarroEntrada) -> dict:
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
    if len(fotos) > MAX_FOTOS or any(_foto_ruim(u) for u in fotos):
        campos["fotos"] = f"Até {MAX_FOTOS} links, cada um começando com https://."
    if campos:
        raise ErroApi("invalido", campos)
    return {**textos, "ano": entrada.ano, "km": entrada.km, "cambio": entrada.cambio,
            "preco": float(entrada.preco), "status": entrada.status,
            "fotos": ", ".join(fotos)}


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
    dados = validar(entrada)
    with _como(sessao):
        try:
            novo = estoque.adicionar_carro(**dados, loja_id=loja_id)
        except estoque.StatusInvalido as erro:
            raise ErroApi("invalido", {"status": str(erro)}, str(erro)) from None
    return _resposta(loja_id, novo)


@router.put("/estoque/{id}")
def editar(id: int, entrada: CarroEdicao, sessao: dict = Depends(escrita(ESTOQUE))):
    loja_id = sessao["loja_id"]
    atual = _carro_da_loja(loja_id, id)
    if atual["status"] == estoque.VENDIDO:
        raise ErroApi("invalido", mensagem=estoque.MENSAGEM_JA_VENDIDO)
    dados = validar(entrada.dados)
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
        except estoque.CarroMudou:
            raise ErroApi("conflito", mensagem=CARRO_MUDOU) from None
        except estoque.StatusInvalido as erro:
            raise ErroApi("invalido", {"status": str(erro)}, str(erro)) from None
    return _resposta(loja_id, id)

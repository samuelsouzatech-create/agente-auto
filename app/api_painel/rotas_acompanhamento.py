"""
Rotas do C2d, parte 1: Acompanhamento, pausar, retomar e "Não enviar".

- Só dono e gerente, e só com o módulo de acompanhamento ligado
  (remarketing ou pós-venda). Vendedor: 403. Módulo desligado: 403 modulo_desligado.
- Quem age vem da sessão (ator 'cliente', origem 'api'). pausar/retomar ficam
  no histórico próprio (pausas_envio); bloquear/desfazer no Registro.
- Pausar ou retomar de novo: devolve a situação atual, sem gravar de novo.
- Desfazer: bloqueio de outra loja (ou que não existe) = 404; já desfeito = 204.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from banco import conectar
from app import bloqueios, pausa
from app.api_painel.acompanhamento import montar_acompanhamento, montar_bloqueio, montar_pausa
from app.api_painel.erros import ErroApi
from app.api_painel.modulos import ACOMPANHAMENTO, escrita, leitura
from app.apresentacao import nomes_dos_clientes
from app.ator import como
from app.lojas import carregar_loja
from app.relogio import agora_utc

MAX_MOTIVO = pausa.MAX_MOTIVO
MAX_LEAD = 80
TIPO_INVALIDO = "Escolha o que não enviar."
CLIENTE_NAO_ENCONTRADO = "Não encontramos esse cliente nesta loja."
BLOQUEIO_NAO_ENCONTRADO = "Não encontramos esse bloqueio."

router = APIRouter(tags=["Acompanhamento"])


class PausarEntrada(BaseModel):
    motivo: str = ""


class BloqueioEntrada(BaseModel):
    lead: str = ""
    tipo: str = ""
    passo: Optional[int] = None


def _como(sessao: dict):
    return como(sessao["nome"], "cliente", "api", sessao["loja_id"])


def _cliente_existe(loja_id: int, lead: str) -> bool:
    conexao = conectar()
    conexao.execute("PRAGMA query_only = ON")
    try:
        return conexao.execute(
            "SELECT 1 FROM mensagens WHERE loja_id = ? AND lead_id = ? UNION ALL "
            "SELECT 1 FROM leads WHERE loja_id = ? AND lead_id = ? UNION ALL "
            "SELECT 1 FROM contatos WHERE loja_id = ? AND telefone = ? UNION ALL "
            "SELECT 1 FROM regua_execucoes WHERE loja_id = ? AND lead_id = ? LIMIT 1",
            (loja_id, lead) * 4).fetchone() is not None
    finally:
        conexao.close()


def _bloqueio_da_loja(loja_id: int, bloqueio_id: int) -> bool:
    conexao = conectar()
    try:
        return conexao.execute("SELECT 1 FROM bloqueios_envio WHERE id = ? AND loja_id = ?",
                               (bloqueio_id, loja_id)).fetchone() is not None
    finally:
        conexao.close()


def _pausa_atual(loja_id: int) -> dict:
    return montar_pausa(carregar_loja(loja_id), loja_id, agora_utc())


@router.get("/acompanhamento")
def ver(sessao: dict = Depends(leitura(ACOMPANHAMENTO))):
    return montar_acompanhamento(sessao["loja_id"])


@router.post("/acompanhamento/pausar")
def pausar(entrada: Optional[PausarEntrada] = None,
           sessao: dict = Depends(escrita(ACOMPANHAMENTO))):
    loja_id = sessao["loja_id"]
    motivo = " ".join(str((entrada.motivo if entrada else "") or "").split())
    if len(motivo) > MAX_MOTIVO:
        raise ErroApi("invalido", {"motivo": f"No máximo {MAX_MOTIVO} caracteres."},
                      f"O motivo pode ter no máximo {MAX_MOTIVO} caracteres.")
    if not pausa.pausado(loja_id):
        with _como(sessao):
            try:
                pausa.pausar(loja_id, usuario=sessao["nome"], papel="cliente", motivo=motivo)
            except pausa.PausaInvalida:
                pass                     # outra pessoa pausou no mesmo instante
    return _pausa_atual(loja_id)


@router.post("/acompanhamento/retomar")
def retomar(sessao: dict = Depends(escrita(ACOMPANHAMENTO))):
    loja_id = sessao["loja_id"]
    if pausa.pausado(loja_id):
        with _como(sessao):
            try:
                pausa.retomar(loja_id, usuario=sessao["nome"], papel="cliente")
            except pausa.PausaInvalida:
                pass                     # outra pessoa retomou no mesmo instante
    return _pausa_atual(loja_id)


@router.post("/bloqueios", status_code=201)
def bloquear(entrada: BloqueioEntrada, sessao: dict = Depends(escrita(ACOMPANHAMENTO))):
    loja_id = sessao["loja_id"]
    if entrada.tipo not in bloqueios.TIPOS:
        raise ErroApi("invalido", {"tipo": "Tipo inválido."}, TIPO_INVALIDO)
    lead = " ".join(str(entrada.lead or "").split())
    if not lead or len(lead) > MAX_LEAD or not _cliente_existe(loja_id, lead):
        raise ErroApi("invalido", {"lead": "Cliente não encontrado."}, CLIENTE_NAO_ENCONTRADO)
    passo = None if entrada.tipo == "todos" else entrada.passo
    with _como(sessao):
        try:
            novo = bloqueios.bloquear(loja_id, lead, entrada.tipo, passo, sessao["nome"])
        except bloqueios.BloqueioInvalido as erro:
            texto = str(erro)
            raise ErroApi("invalido", {"tipo": texto}, texto) from None
    marca = next((b for b in bloqueios.listar_ativos(loja_id) if b["id"] == novo), None)
    if marca is None:
        raise ErroApi("erro_interno")
    return montar_bloqueio(carregar_loja(loja_id), marca,
                           nomes_dos_clientes(loja_id, [lead]), agora_utc())


@router.delete("/bloqueios/{id}", status_code=204, response_class=Response)
def desfazer(id: int, sessao: dict = Depends(escrita(ACOMPANHAMENTO))):
    loja_id = sessao["loja_id"]
    if not _bloqueio_da_loja(loja_id, id):
        raise ErroApi("nao_encontrado", mensagem=BLOQUEIO_NAO_ENCONTRADO)
    with _como(sessao):
        bloqueios.desfazer(loja_id, id, sessao["nome"])     # já desfeito: não grava de novo
    return Response(status_code=204)

"""
Rotas do C2c: uma conversa e as ações do vendedor.

- Quem pode: dono, gestor, vendedor e vendedor do link (x-papeis do contrato).
  O vendedor do link só a conversa dele (403 nas outras).
- A loja vem só da sessão. Conversa de outra loja: 404, como se não existisse.
- O escopo é conferido numa dependência, ANTES de ler o corpo do pedido.
- Quem age vem da sessão (ator 'cliente', origem 'api'). As funções de app/
  gravam no Registro, na mesma transação.
- Toda rota que escreve exige X-CSRF-Token. Rotas síncronas (def): o envio
  pelo painel usa asyncio.run e roda numa thread própria.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from banco import conectar
from app import envio_painel, handoff, sessoes, vendas
from app.apresentacao import data_para_tela
from app.ator import como
from app.api_painel.atender import ASSUMIDO, AGUARDANDO, janela_do_cartao
from app.api_painel.conversa import (FORA_DA_JANELA, fatos, lead_valido, montar_conversa,
                                     montar_mensagem, motivo_para_nao_devolver,
                                     motivo_para_nao_responder)
from app.api_painel.dependencias import exigir_csrf, exigir_papel
from app.api_painel.erros import ErroApi
from app.lojas import carregar_loja
from app.relogio import agora_utc

QUEM_ATENDE = sessoes.PAPEIS_DA_SESSAO          # dono, gestor, vendedor, vendedor_link
NAO_ENCONTRADA = "Não encontramos essa conversa."
CARRO_FORA_DO_ESTOQUE = "Este carro não está no estoque desta loja."

router = APIRouter(prefix="/conversas", tags=["Atender"])


class ResponderEntrada(BaseModel):
    texto: str = ""


class VendaEntrada(BaseModel):
    carro_id: int
    data_venda: date
    forma_pagamento: str = ""
    meses_financiamento: Optional[int] = None


# ------------------------------------------------------------ apoio

def _lead_permitido(lead: str, sessao: dict) -> str:
    valido = lead_valido(lead)
    if valido is None:
        raise ErroApi("nao_encontrado", mensagem=NAO_ENCONTRADA)
    if sessao["escopo"] == sessoes.LINK and sessao.get("lead_id") != valido:
        raise ErroApi("sem_permissao")
    return valido


def ler_conversa(lead: str, sessao: dict = Depends(exigir_papel(*QUEM_ATENDE))):
    return sessao, _lead_permitido(lead, sessao)


def escrever_conversa(lead: str, sessao: dict = Depends(exigir_csrf)):
    if sessao["papel"] not in QUEM_ATENDE:
        raise ErroApi("sem_permissao")
    return sessao, _lead_permitido(lead, sessao)


def _fatos_ou_404(loja_id: int, lead: str) -> dict:
    f = fatos(loja_id, lead)
    if not f["existe"]:
        raise ErroApi("nao_encontrado", mensagem=NAO_ENCONTRADA)
    return f


def _conversa(sessao: dict, lead: str) -> dict:
    corpo = montar_conversa(sessao["loja_id"], lead, sessao)
    if corpo is None:
        raise ErroApi("nao_encontrado", mensagem=NAO_ENCONTRADA)
    return corpo


def _como(sessao: dict):
    return como(sessao["nome"], "cliente", "api", sessao["loja_id"])


def _ultima_do_vendedor(loja_id: int, lead: str, nome: str):
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT id, direcao, tipo, conteudo, canal, autor, criado_em FROM mensagens "
            "WHERE loja_id = ? AND lead_id = ? AND direcao = 'vendedor' AND autor = ? "
            "ORDER BY id DESC LIMIT 1", (loja_id, lead, nome)).fetchone()
    finally:
        conexao.close()
    return dict(linha) if linha else None


def _campo_da_venda(texto: str) -> str:
    t = texto.lower()
    if "carro" in t or "venda já" in t:
        return "carro_id"
    if "data" in t:
        return "data_venda"
    if "meses" in t:
        return "meses_financiamento"
    if "forma" in t:
        return "forma_pagamento"
    return "corpo"


def _forma(entrada: VendaEntrada) -> str:
    if entrada.forma_pagamento == "avista":
        return "À vista"
    meses = entrada.meses_financiamento
    if not meses:
        return "Financiado"
    return f"Financiado em {meses} {'mês' if meses == 1 else 'meses'}"


# ------------------------------------------------------------ rotas

@router.get("/{lead}")
def ver(alvo: tuple = Depends(ler_conversa)):
    sessao, lead = alvo
    return _conversa(sessao, lead)


@router.post("/{lead}/assumir")
def assumir(alvo: tuple = Depends(escrever_conversa)):
    sessao, lead = alvo
    loja_id, nome = sessao["loja_id"], sessao["nome"]
    f = _fatos_ou_404(loja_id, lead)
    if f["estado"] == ASSUMIDO and f["assumido_por"] != nome:
        raise ErroApi("conflito", mensagem=f"{f['assumido_por'] or 'Outra pessoa'} já assumiu esta conversa.")
    with _como(sessao):
        handoff.assumir_conversa(lead, nome, loja_id)
    depois = fatos(loja_id, lead)
    if depois["assumido_por"] != nome:              # outra pessoa assumiu no mesmo instante
        raise ErroApi("conflito", mensagem=f"{depois['assumido_por'] or 'Outra pessoa'} já assumiu esta conversa.")
    return _conversa(sessao, lead)


@router.post("/{lead}/responder")
def responder(entrada: ResponderEntrada, alvo: tuple = Depends(escrever_conversa)):
    sessao, lead = alvo
    loja_id, nome = sessao["loja_id"], sessao["nome"]
    texto = (entrada.texto or "").strip()
    if not texto:
        raise ErroApi("invalido", {"texto": "Mensagem vazia."}, "Escreva a mensagem antes de enviar.")
    limite = envio_painel.LIMITE_CARACTERES
    if len(texto) > limite:
        raise ErroApi("invalido", {"texto": f"No máximo {limite} caracteres."},
                      f"Mensagem longa demais (máximo {limite} caracteres).")
    f = _fatos_ou_404(loja_id, lead)
    loja = carregar_loja(loja_id)
    agora = agora_utc()
    motivo = motivo_para_nao_responder(f, janela_do_cartao(loja, loja_id, lead, f["canal"], agora), nome)
    if motivo == FORA_DA_JANELA:
        raise ErroApi("janela_fechada")
    if motivo:
        raise ErroApi("invalido", {"texto": motivo}, motivo)
    with _como(sessao):
        try:
            envio_painel.enviar_pelo_painel(loja_id, f["canal"], lead, texto, nome)
        except envio_painel.EnvioRecusado as erro:
            explicacao = str(erro)[:300]
            raise ErroApi("invalido", {"texto": explicacao}, explicacao) from None
    enviada = _ultima_do_vendedor(loja_id, lead, nome)
    corpo = montar_mensagem(loja, enviada, agora) if enviada else None
    if corpo is None:
        raise ErroApi("erro_interno")
    return corpo


@router.post("/{lead}/devolver")
def devolver(alvo: tuple = Depends(escrever_conversa)):
    sessao, lead = alvo
    f = _fatos_ou_404(sessao["loja_id"], lead)
    if f["estado"] in (ASSUMIDO, AGUARDANDO):
        motivo = motivo_para_nao_devolver(f, sessao)
        if motivo:
            raise ErroApi("sem_permissao", mensagem=motivo)
        with _como(sessao):
            handoff.devolver_ao_agente(lead, sessao["loja_id"])
    return _conversa(sessao, lead)            # já estava com o Léo: nada muda


@router.post("/{lead}/registrar-venda")
def registrar_venda(entrada: VendaEntrada, alvo: tuple = Depends(escrever_conversa)):
    sessao, lead = alvo
    loja_id, nome = sessao["loja_id"], sessao["nome"]
    _fatos_ou_404(loja_id, lead)
    if entrada.forma_pagamento == "financiado" and not entrada.meses_financiamento:
        raise ErroApi("invalido", {"meses_financiamento": "Informe em quantos meses."},
                      "Informe em quantos meses foi financiado.")
    with _como(sessao):
        try:
            feito = vendas.registrar_venda(loja_id, lead, entrada.carro_id, entrada.data_venda,
                                           entrada.forma_pagamento,
                                           meses_financiamento=entrada.meses_financiamento,
                                           vendedor=nome)
        except vendas.VendaInvalida as erro:
            texto = str(erro)
            campo = "Escolha um carro do estoque." if texto == CARRO_FORA_DO_ESTOQUE else texto
            raise ErroApi("invalido", {_campo_da_venda(texto): campo}, texto) from None
    efeitos = [{"codigo": "venda", "texto": "Venda registrada"},
               {"codigo": "resultado", "texto": "Resultado do cliente: comprou"}]
    if feito["carro"]:
        efeitos.append({"codigo": "baixa_no_estoque", "texto": f"{feito['carro']} saiu do estoque"})
    if feito["pos_venda_ligado"] and feito["pos_venda"]:
        efeitos.append({"codigo": "pos_venda", "texto": "Pós-venda agendado"})
    return {"venda_id": feito["venda_id"], "carro": feito["carro"],
            "data": data_para_tela(entrada.data_venda), "forma": _forma(entrada),
            "efeitos": efeitos}

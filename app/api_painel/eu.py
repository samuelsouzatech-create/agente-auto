"""
Monta a resposta 'Eu' (GET /auth/eu e POST /auth/login), no formato do contrato.

- modulos.acompanhamento = remarketing ou pós-venda ligado na loja.
- modulos.estoque = chave modulos.estoque (decisão D2, padrão ligado).
- abas: o que a pessoa vê, já filtrado por papel e módulo (o front só desenha):
    completo    -> atender, leads, resultado (+ acompanhamento, + estoque se ligados)
    atendimento -> atender, leads (vendedor com login, decisão D1)
    link        -> só atender (o vendedor do link vê só a conversa)
"""
from __future__ import annotations

from banco import conectar
from app.autenticacao import rotulo_papel
from app.estado_loja import EM_TESTE, NO_AR, ROTULOS, esta_no_ar
from app.lojas import carregar_loja
from app.relogio import FUSO_PADRAO
from app.sessoes import ATENDIMENTO, LINK, PAPEL_LINK, csrf_da

ATENDER, LEADS, RESULTADO, ACOMPANHAMENTO, ESTOQUE = (
    "atender", "leads", "resultado", "acompanhamento", "estoque")


def modulos_da_loja(loja) -> dict:
    return {
        "acompanhamento": bool(loja.get("modulos.remarketing")) or bool(loja.get("modulos.pos_venda")),
        "estoque": bool(loja.get("modulos.estoque")),
    }


def abas(escopo: str, modulos: dict) -> list:
    if escopo == LINK:
        return [ATENDER]
    if escopo == ATENDIMENTO:
        return [ATENDER, LEADS]
    lista = [ATENDER, LEADS, RESULTADO]
    if modulos["acompanhamento"]:
        lista.append(ACOMPANHAMENTO)
    if modulos["estoque"]:
        lista.append(ESTOQUE)
    return lista


def _nome_da_loja(loja_id: int) -> str:
    conexao = conectar()
    try:
        linha = conexao.execute("SELECT nome FROM lojas WHERE id = ?", (loja_id,)).fetchone()
    finally:
        conexao.close()
    return linha["nome"] if linha else ""


def montar_eu(sessao: dict, token: str) -> dict:
    loja_id = sessao["loja_id"]
    loja = carregar_loja(loja_id)
    modulos = modulos_da_loja(loja)
    estado = NO_AR if esta_no_ar(loja_id) else EM_TESTE
    papel = sessao["papel"]
    return {
        "nome": sessao["nome"],
        "papel": papel,
        "papel_rotulo": rotulo_papel("vendedor" if papel == PAPEL_LINK else papel),
        "escopo": sessao["escopo"],
        "conversa_do_link": sessao["lead_id"],
        "loja": {
            "nome": _nome_da_loja(loja_id),
            "fuso": loja.get("fuso") or FUSO_PADRAO,
            "fuso": loja.get("fuso") or FUSO_PADRAO,
            "estado": {"codigo": estado, "rotulo": ROTULOS[estado]},
        },
        "modulos": modulos,
        "abas": abas(sessao["escopo"], modulos),
        "csrf": csrf_da(token),
    }

"""
Exclusão de dados a pedido da Meta (I6 do plano mestre; IG3 da Maratona 4).

A Meta chama POST /dados/excluir com um `signed_request` (assinatura HMAC-SHA256 com o segredo do
app, o mesmo jeito da página oficial de "Data Deletion Callback", lida no IG0). O Léo apaga TUDO do
cliente do Instagram (ig:<id>) nas tabelas das lojas onde ele existe, e responde
{url, confirmation_code}. A url mostra que o pedido foi feito (sem dado pessoal).

O id que a Meta manda no Instagram é por conta (cada conta de loja vê outro id para a mesma pessoa),
então o pedido só alcança a loja daquela conta. Outra loja nunca é tocada (teste confere).
Nada de dado pessoal no registro: guarda só um resumo (hash) de quem pediu e quantas linhas saíram.

SE0 (Maratona Segurança): os NÚMEROS da loja não podem mudar. Então, nas tabelas que contam
venda, resultado e custo (ANONIMIZAR, abaixo) a linha fica, mas o cliente vira um nome anônimo
("excluido:<código>", o mesmo para todas as linhas dele) e os textos livres somem. O resto é
apagado: mensagens, memória da conversa, ficha (nome, telefone dado no Instagram, interesse),
vínculo com o WhatsApp, chamados e os avisos deles. Por fim, qualquer texto da loja que ainda
cite "ig:<id>" (ex.: o Registro) tem a citação trocada pelo nome anônimo.
A conversa do WhatsApp que estava VINCULADA não é apagada (é outro canal, com outra base legal):
só o vínculo sai. Decisão anotada no docs/seguranca.md para o analista.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.log import logger as _logger
from banco import conectar

_log = _logger("dados")
rotas = APIRouter()

# Tabelas com o cliente (coluna -> tabelas). Achadas no banco na hora (tabela nova entra sozinha).
COLUNAS_DO_CLIENTE = ("lead_id", "lead_principal", "lead_vinculado")


class PedidoInvalido(ValueError):
    pass


def _b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def ler_pedido_assinado(signed_request: str, segredo: str) -> dict:
    """O formato da Meta: <assinatura>.<dados>, os dois em base64url; assinatura = HMAC-SHA256
    dos dados (o texto base64) com o segredo do app. Falha fechada sem segredo."""
    if not segredo:
        raise PedidoInvalido("sem segredo configurado")
    try:
        assinatura, dados = str(signed_request or "").split(".", 1)
        esperado = hmac.new(segredo.encode(), dados.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64(assinatura), esperado):
            raise PedidoInvalido("assinatura não confere")
        conteudo = json.loads(_b64(dados))
    except PedidoInvalido:
        raise
    except Exception as erro:
        raise PedidoInvalido(f"pedido mal formado ({type(erro).__name__})") from None
    if str(conteudo.get("algorithm") or "").upper() != "HMAC-SHA256" or not conteudo.get("user_id"):
        raise PedidoInvalido("pedido sem user_id ou com outro algoritmo")
    return conteudo


def _tabelas_do_cliente(conexao) -> list[tuple[str, str]]:
    linhas = conexao.execute(
        "SELECT c.table_name, c.column_name FROM information_schema.columns c "
        "JOIN information_schema.columns l ON l.table_name = c.table_name AND l.table_schema = c.table_schema "
        "AND l.column_name = 'loja_id' WHERE c.table_schema = current_schema() AND c.column_name IN "
        "('lead_id', 'lead_principal', 'lead_vinculado') ORDER BY c.table_name, c.column_name").fetchall()
    return [(l["table_name"], l["column_name"]) for l in linhas]


def lojas_do_cliente(lead_id: str) -> list[int]:
    conexao = conectar(somente_leitura=True)
    try:
        ids = set()
        for tabela, coluna in _tabelas_do_cliente(conexao):
            ids |= {l["loja_id"] for l in conexao.execute(
                f"SELECT DISTINCT loja_id FROM {tabela} WHERE {coluna} = ?", (lead_id,)).fetchall()}
    finally:
        conexao.close()
    return sorted(i for i in ids if i is not None)


# SE0: tabela -> colunas de texto livre que somem. A linha fica (os números da loja não mudam).
ANONIMIZAR = {"vendas": (), "resultados": ("motivo",), "uso_custos": ()}


def _colunas_de_texto(conexao) -> list[tuple[str, str]]:
    linhas = conexao.execute(
        "SELECT c.table_name, c.column_name FROM information_schema.columns c "
        "JOIN information_schema.columns l ON l.table_name = c.table_name AND l.table_schema = c.table_schema "
        "AND l.column_name = 'loja_id' WHERE c.table_schema = current_schema() "
        "AND c.data_type IN ('text', 'character varying') ORDER BY c.table_name, c.column_name").fetchall()
    return [(l["table_name"], l["column_name"]) for l in linhas]


def apagar_cliente(loja_id: int, lead_id: str) -> int:
    """Apaga o cliente desta loja (SE0: anonimiza venda, resultado e custo). Devolve quantas linhas
    saíram ou foram anonimizadas. Outra loja não é tocada. Tudo numa transação só."""
    from app.chaves import exigir_loja, thread_id
    loja_id = exigir_loja(loja_id)
    anonimo = "excluido:" + secrets.token_hex(6)
    total = 0
    conexao = conectar()
    try:
        canais = {l["canal"] for l in conexao.execute(
            "SELECT DISTINCT canal FROM mensagens WHERE loja_id = ? AND lead_id = ?", (loja_id, lead_id)).fetchall()}
        telefone = conexao.execute("SELECT telefone FROM leads WHERE loja_id = ? AND lead_id = ?",
                                   (loja_id, lead_id)).fetchone()
        telefone = (telefone["telefone"] or "") if telefone else ""
        chamados = [f"handoff:{l['id']}" for l in conexao.execute(
            "SELECT id FROM handoffs WHERE loja_id = ? AND lead_id = ?", (loja_id, lead_id)).fetchall()]
        for referencia in chamados:              # o aviso ao vendedor tem o resumo e o nome do cliente
            cursor = conexao.execute("DELETE FROM avisos WHERE loja_id = ? AND referencia = ?", (loja_id, referencia))
            total += max(cursor.rowcount or 0, 0)
        for tabela, coluna in _tabelas_do_cliente(conexao):
            if tabela in ANONIMIZAR:
                limpar = "".join(f", {c} = NULL" for c in ANONIMIZAR[tabela])
                cursor = conexao.execute(f"UPDATE {tabela} SET {coluna} = ?{limpar} WHERE loja_id = ? AND {coluna} = ?",
                                         (anonimo, loja_id, lead_id))
            else:
                cursor = conexao.execute(f"DELETE FROM {tabela} WHERE loja_id = ? AND {coluna} = ?", (loja_id, lead_id))
            total += max(cursor.rowcount or 0, 0)
        por_tabela: dict[str, list[str]] = {}
        for tabela, coluna in _colunas_de_texto(conexao):
            por_tabela.setdefault(tabela, []).append(coluna)
        for tabela, colunas in por_tabela.items():      # o que ainda cita o cliente (ex.: o Registro)
            cita = " OR ".join(f"strpos({c}, ?) > 0" for c in colunas)
            for velho, novo in ((telefone, "telefone apagado"), (lead_id, anonimo)):
                if not velho:
                    continue
                trocas = ", ".join(f"{c} = replace({c}, ?, ?)" for c in colunas)
                conexao.execute(f"UPDATE {tabela} SET {trocas} WHERE loja_id = ? AND ({cita})",
                                (*[x for _ in colunas for x in (velho, novo)], loja_id, *[lead_id] * len(colunas)))
        conexao.commit()
    finally:
        conexao.close()
    try:
        from app.core.agent import memoria
        for canal in canais | {"instagram"}:
            memoria.delete_thread(thread_id(loja_id, canal or "", lead_id))
    except Exception:
        _log.exception("[Dados] Não consegui apagar a memória da conversa.")
    return total


def registrar_pedido(loja_id, resumo: str, origem: str, linhas: int) -> str:
    codigo = secrets.token_hex(8)
    conexao = conectar()
    try:
        conexao.execute("INSERT INTO pedidos_exclusao (loja_id, codigo, resumo_do_pedido, origem, linhas_apagadas) "
                        "VALUES (?, ?, ?, ?, ?)", (loja_id, codigo, resumo, origem, linhas))
        conexao.commit()
    finally:
        conexao.close()
    return codigo


def excluir_pedido_da_meta(signed_request: str, segredo: str) -> dict:
    conteudo = ler_pedido_assinado(signed_request, segredo)
    lead_id = "ig:" + str(conteudo["user_id"])
    resumo = hashlib.sha256(lead_id.encode()).hexdigest()[:16]
    lojas = lojas_do_cliente(lead_id)
    linhas = sum(apagar_cliente(loja, lead_id) for loja in lojas)
    codigo = registrar_pedido(lojas[0] if len(lojas) == 1 else None, resumo, "meta", linhas)
    return {"codigo": codigo, "lojas": lojas, "linhas": linhas}


def endereco_publico() -> str:
    return (os.getenv("LEO_ENDERECO_PUBLICO") or "https://localhost").rstrip("/")


@rotas.post("/dados/excluir")
async def excluir(request: Request):
    from urllib.parse import parse_qs
    corpo = (await request.body()).decode("utf-8", "replace")
    formulario = {k: v[0] for k, v in parse_qs(corpo).items()}     # a Meta manda como formulário
    try:
        feito = excluir_pedido_da_meta(str(formulario.get("signed_request") or ""),
                                       os.getenv("INSTAGRAM_APP_SECRET", ""))
    except PedidoInvalido as erro:
        _log.warning(f"[Dados] Pedido de exclusão recusado: {erro}.")
        return JSONResponse({"erro": "pedido inválido"}, status_code=400)
    return JSONResponse({"url": f"{endereco_publico()}/dados/excluir/{feito['codigo']}",
                         "confirmation_code": feito["codigo"]})


@rotas.get("/dados/excluir/{codigo}")
def situacao(codigo: str):
    conexao = conectar(somente_leitura=True)
    try:
        linha = conexao.execute("SELECT criado_em FROM pedidos_exclusao WHERE codigo = ?", (codigo,)).fetchone()
    finally:
        conexao.close()
    if not linha:
        return Response("Pedido não encontrado.", status_code=404, media_type="text/plain; charset=utf-8")
    return Response("Pedido de exclusão recebido e concluído: os dados desta conversa foram apagados.",
                    media_type="text/plain; charset=utf-8")

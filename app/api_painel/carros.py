"""
Tela Estoque (C2d): carros da loja no formato do contrato.

- fotos: no banco é um texto com links separados por vírgula; na API, uma lista.
- interessados: pessoas interessadas agora (um carro de interesse por cliente,
  tabela interesse_veiculo; contrato, item 3).
- pode_editar: false no carro vendido (a venda só existe por "Registrar venda").
- Ordem: os à venda primeiro, depois os vendidos; em cada grupo, pelo número.
Só lê: nada aqui grava no banco.
"""
from __future__ import annotations

import math

from banco import conectar
from app import estoque

TAMANHO_PADRAO, TAMANHO_MAXIMO = 50, 100
SITUACOES = ("disponivel", "reservado", "indisponivel", "vendido")
ROTULOS_STATUS = {"disponivel": "Disponível", "reservado": "Reservado",
                  "indisponivel": "Indisponível", "vendido": "Vendido"}


def dinheiro(valor) -> str:
    try:
        texto = f"{float(valor):,.2f}"
    except (TypeError, ValueError):
        return "R$ —"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def fotos_em_lista(texto) -> list:
    return [u.strip() for u in str(texto or "").split(",") if u.strip()]


def valores_da_api(carro: dict) -> dict:
    v = estoque.valores_do_carro(carro)
    return {**v, "ano": int(v["ano"]), "km": int(v["km"]), "preco": float(v["preco"]),
            "fotos": fotos_em_lista(v["fotos"])}


def interessados(loja_id: int) -> dict:
    conexao = conectar()
    conexao.execute("PRAGMA query_only = ON")
    try:
        linhas = conexao.execute(
            "SELECT veiculo_id, COUNT(*) AS n FROM interesse_veiculo WHERE loja_id = ? "
            "GROUP BY veiculo_id", (loja_id,)).fetchall()
    finally:
        conexao.close()
    return {int(l["veiculo_id"]): int(l["n"]) for l in linhas}


def montar_carro(carro: dict, contagem: dict) -> dict:
    v = valores_da_api(carro)
    return {"id": int(carro["id"]), "marca": v["marca"], "modelo": v["modelo"],
            "ano": v["ano"], "km": v["km"], "cor": v["cor"], "cambio": v["cambio"],
            "preco": {"valor": v["preco"], "texto": dinheiro(v["preco"])},
            "status": v["status"], "status_rotulo": ROTULOS_STATUS.get(v["status"], v["status"]),
            "fotos": v["fotos"], "interessados": contagem.get(int(carro["id"]), 0),
            "pode_editar": v["status"] != estoque.VENDIDO}


def _numero(valor, padrao: int, minimo: int, maximo: int) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        n = padrao
    return max(minimo, min(n, maximo))


def montar_estoque(loja_id: int, pagina=1, tamanho=TAMANHO_PADRAO) -> dict:
    tamanho = _numero(tamanho, TAMANHO_PADRAO, 1, TAMANHO_MAXIMO)
    carros = sorted(estoque.listar_estoque(loja_id),
                    key=lambda c: (c["status"] == estoque.VENDIDO, c["id"]))
    total = len(carros)
    paginas = max(1, math.ceil(total / tamanho))
    pagina = _numero(pagina, 1, 1, paginas)
    totais = {s: 0 for s in SITUACOES}
    for c in carros:
        if c["status"] in totais:
            totais[c["status"]] += 1
    contagem = interessados(loja_id)
    inicio = (pagina - 1) * tamanho
    return {"pagina": pagina, "paginas": paginas, "total": total, "tamanho": tamanho,
            "itens": [montar_carro(c, contagem) for c in carros[inicio:inicio + tamanho]],
            "totais": totais}

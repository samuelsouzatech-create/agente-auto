"""
Catálogo do ramo de VEÍCULOS = o estoque da loja (SG2, Maratona 4).

Implementa a interface de app/catalogo.py POR CIMA da tabela estoque, sem mudar a tabela, a API
/estoque nem o painel. As consultas são as MESMAS que o motor fazia direto (enviar_fotos, filtro
de preço do remarketing, carro parecido do remarketing): o comportamento não muda.
"""
from __future__ import annotations

import re
import unicodedata

from app import fotos as _fotos
from app.catalogo import Item
from app.chaves import exigir_loja
from banco import conectar

COLUNAS = "id, marca, modelo, ano, cor, fotos, preco, status"
FAIXA_PRECO_PARECIDO = 0.20     # o mesmo do remarketing (FAIXA_PRECO_ALTERNATIVA)


def _item(linha) -> Item:
    d = dict(linha)
    return Item(id=d["id"], nome=f"{d['marca']} {d['modelo']} {d['ano']}",
                disponivel=d.get("status") == "disponivel",
                preco=float(d["preco"]) if d.get("preco") is not None else None,
                detalhe=d.get("cor") or "", fotos_ref=d.get("fotos") or "",
                situacao=d.get("status") or "", dados=d)


def _sem_acento(texto: str) -> str:
    t = unicodedata.normalize("NFD", str(texto or "")).lower()
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


class CatalogoDeVeiculos:
    def buscar(self, loja_id, *, item_id=0, marca="", modelo="", texto="", so_com_fotos=False,
               so_disponiveis=True) -> list[Item]:
        loja_id = exigir_loja(loja_id)
        sql = f"SELECT {COLUNAS} FROM estoque WHERE loja_id = ?"
        parametros: list = [loja_id]
        if so_disponiveis:
            sql += " AND status = 'disponivel'"
        if item_id:
            sql += " AND id = ?"
            parametros.append(item_id)
        if marca:
            sql += " AND sem_acento(marca) LIKE sem_acento(?)"
            parametros.append(f"%{marca}%")
        if modelo:
            sql += " AND sem_acento(modelo) LIKE sem_acento(?)"
            parametros.append(f"%{modelo}%")
        if so_com_fotos:
            sql += " AND TRIM(COALESCE(fotos, '')) <> ''"
        conexao = conectar()
        try:
            linhas = conexao.execute(sql, parametros).fetchall()
        finally:
            conexao.close()
        itens = [_item(l) for l in linhas]
        if texto:
            itens = [i for i in itens if _sem_acento(texto) in _sem_acento(i.nome)]
        return itens

    def detalhar(self, loja_id, item_id) -> Item | None:
        loja_id = exigir_loja(loja_id)
        conexao = conectar()
        try:
            linha = conexao.execute(f"SELECT {COLUNAS} FROM estoque WHERE id = ? AND loja_id = ?",
                                    (item_id, loja_id)).fetchone()
        finally:
            conexao.close()
        return _item(linha) if linha else None

    def disponivel(self, loja_id, item_id) -> bool:
        item = self.detalhar(loja_id, item_id)
        return bool(item and item.disponivel)

    def fotos(self, loja_id, item_id_ou_item) -> list[str]:
        """Só fotos do depósito desta loja (Maratona Fotos)."""
        item = item_id_ou_item if isinstance(item_id_ou_item, Item) else self.detalhar(loja_id, item_id_ou_item)
        return _fotos.refs_do_carro(exigir_loja(loja_id), item.fotos_ref) if item else []

    def parecido(self, loja_id, item) -> Item | None:
        """Carro disponível parecido: mesma loja, preço até 20% de diferença; mesmo modelo primeiro,
        depois mesma marca, depois o preço mais perto (a regra do remarketing, igual)."""
        loja_id = exigir_loja(loja_id)
        if item is None or item.preco is None:
            return None
        preco = float(item.preco)
        conexao = conectar()
        try:
            linha = conexao.execute(
                f"SELECT {COLUNAS} FROM estoque "
                "WHERE loja_id = ? AND status = 'disponivel' AND id != ? AND preco BETWEEN ? AND ? "
                "ORDER BY (modelo = ?) DESC, (marca = ?) DESC, ABS(preco - ?) LIMIT 1",
                (loja_id, item.id, preco * (1 - FAIXA_PRECO_PARECIDO), preco * (1 + FAIXA_PRECO_PARECIDO),
                 item.dados.get("modelo"), item.dados.get("marca"), preco),
            ).fetchone()
        finally:
            conexao.close()
        return _item(linha) if linha else None

    def precos(self, loja_id, ids) -> set:
        """Preços (em centavos) destes itens, como estão no estoque DESTA loja."""
        ids = [i for i in ids if i]
        if not ids:
            return set()
        loja_id = exigir_loja(loja_id)
        marcas = ",".join("?" * len(ids))
        conexao = conectar()
        try:
            linhas = conexao.execute(
                f"SELECT preco FROM estoque WHERE loja_id = ? AND id IN ({marcas})",
                (loja_id, *ids)).fetchall()
        finally:
            conexao.close()
        return {int(round(float(l["preco"]) * 100)) for l in linhas if l["preco"] is not None}

    def citados_no_texto(self, loja_id, texto) -> list[Item]:
        """Carros desta loja (qualquer situação) cujo MODELO aparece no texto, como palavra
        inteira (ex.: a legenda do post "Corolla 2020 impecável" acha o Corolla). Se o ano também
        aparece no texto, só os desse ano. Mais recente primeiro."""
        normal = _sem_acento(texto)
        if not normal.strip():
            return []
        loja_id = exigir_loja(loja_id)
        conexao = conectar()
        try:
            linhas = conexao.execute(f"SELECT {COLUNAS} FROM estoque WHERE loja_id = ? ORDER BY id DESC",
                                     (loja_id,)).fetchall()
        finally:
            conexao.close()
        achados = [_item(l) for l in linhas
                   if l["modelo"] and re.search(r"(?<!\w)" + re.escape(_sem_acento(l["modelo"])) + r"(?!\w)", normal)]
        com_ano = [i for i in achados if str(i.dados.get("ano") or "") and
                   re.search(r"(?<!\d)" + str(i.dados.get("ano")) + r"(?!\d)", normal)]
        return com_ano or achados


CATALOGO = CatalogoDeVeiculos()

"""
Filtro do texto que a IA escreve no remarketing (Bloco S1, furos 3 e 15).

- Preço: a MESMA guarda do atendimento (app/guarda_politica.py). Valor em
  dinheiro que não está na conversa nem no estoque DESTA loja barra o texto.
- Ação inventada ("falei com o gerente", "consegui um desconto", "reservamos
  o carro", "retorno sobre a sua proposta") barra o texto. O certo é OFERECER:
  "quer que eu veja com o gerente?".
- Texto barrado não deixa o cliente sem nada: o remarketing manda o texto
  reserva, que não tem preço nem promessa.
Só leitura. Sem Streamlit, sem IA.
"""
from __future__ import annotations

import re

from banco import conectar
from app.chaves import exigir_loja
from app.guarda_politica import numeros_do_cliente, valores_em_reais

_ACAO_INVENTADA = re.compile(
    r"(?i)\b(?:falei|conversei|consegui\s+falar|levei|passei|consultei|chamei)\b"
    r"[^.!?\n]{0,30}\b(?:gerente|ger[eê]ncia|dono|diretor|financeiro|chefe|patr[aã]o|respons[aá]vel)"
    r"|\b(?:consegui|conseguimos|liberei|liberamos|liberaram|aprovei|aprovaram)\b[^.!?\n]{0,30}"
    r"\b(?:desconto|abatimento|condi[çc][ãa]o|redu[çc][ãa]o"
    r"|(?:valor|pre[çc]o)\s+(?:especial|menor|melhor))"
    r"|\b(?:retorno|resposta)\s+(?:sobre|da|de|para|pra)\s+(?:a\s+)?(?:sua\s+)?proposta"
    r"|\b(?:reservamos|separamos)\b"
    r"|\b(?:guardei|guardamos|segurei|seguramos)\s+(?:o|ele|esse|aquele|pra|para)\b"
    r"|\b(?:deixamos|deixei|t[aá]|est[aá]|ficou)\s+(?:ele\s+|o\s+carro\s+)?(?:reservad|separad|guardad)"
)


def acao_inventada(texto) -> bool:
    """True se o texto diz que alguém já fez algo que ninguém fez."""
    return bool(_ACAO_INVENTADA.search(texto or ""))


def preco_fora(texto, permitidos) -> bool:
    """True se o texto cita dinheiro fora de permitidos (centavos)."""
    return bool(valores_em_reais(texto) - set(permitidos or ()))


def precos_da_conversa(historico) -> set:
    """Valores já ditos na conversa: do cliente (menos km) e da loja (Léo, vendedor)."""
    permitidos = set()
    for m in historico or ():
        conteudo = str(m.get("conteudo") or "")
        if m.get("direcao") == "cliente":
            permitidos |= numeros_do_cliente(conteudo)
        else:
            permitidos |= valores_em_reais(conteudo)
    return permitidos


def precos_do_estoque(loja_id, dados) -> set:
    """Preço do carro de interesse e da alternativa, como está no estoque DESTA loja."""
    ids = [i for i in (dados.get("veiculo_id"), dados.get("alternativa_id")) if i]
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

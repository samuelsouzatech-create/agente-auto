"""Quem está usando o painel (separação cliente x operador).

Sem Streamlit, para dar para testar. Enquanto não existe login (vem com a
API do painel), a loja do painel do cliente vem da variável LOJA_ID.
"""
import os

from app.lojas import LojaNaoEncontrada, carregar_loja

VARIAVEL_LOJA = "LOJA_ID"


class PainelSemLoja(RuntimeError):
    """O painel do cliente não sabe de qual loja é: ele não abre."""


def loja_do_cliente(ambiente=None) -> int:
    ambiente = os.environ if ambiente is None else ambiente
    bruto = str(ambiente.get(VARIAVEL_LOJA, "")).strip()
    if not bruto:
        raise PainelSemLoja('O painel do cliente precisa saber de qual loja ele é. '
                            'Defina LOJA_ID antes de abrir, ex.: $env:LOJA_ID="1"')
    if not bruto.isdigit() or int(bruto) <= 0:
        raise PainelSemLoja(f"LOJA_ID inválido: '{bruto}'. Use o número da loja, ex.: 1.")
    loja_id = int(bruto)
    try:
        loja = carregar_loja(loja_id)
    except LojaNaoEncontrada:
        raise PainelSemLoja(f"A loja {loja_id} não existe.")
    if not loja.ativo:
        raise PainelSemLoja(f"A loja {loja_id} está desativada.")
    return loja_id

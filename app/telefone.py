"""
Telefone brasileiro normalizado (Etapa 2, Bloco 5B).

UMA função, usada igual para gravar e para buscar. Resultado: só dígitos,
com 55 na frente e celular com 9 dígitos depois do DDD.
O WhatsApp costuma mandar o número SEM o 9 extra (558199998888): aqui vira
5581999998888. O que não parece celular brasileiro volta vazio ("").
"""
from __future__ import annotations

import re

_NAO_DIGITO = re.compile(r"\D")


def normalizar_telefone_br(texto) -> str:
    digitos = _NAO_DIGITO.sub("", str(texto or "")).lstrip("0")
    if digitos.startswith("55") and len(digitos) in (12, 13):
        digitos = digitos[2:]
    if len(digitos) not in (10, 11):
        return ""
    ddd, numero = digitos[:2], digitos[2:]
    if "0" in ddd:
        return ""
    if len(numero) == 9:
        if numero[0] != "9":
            return ""
    elif numero[0] in "6789":          # celular no formato antigo (8 dígitos)
        numero = "9" + numero
    else:                              # fixo: não é WhatsApp de cliente
        return ""
    return "55" + ddd + numero

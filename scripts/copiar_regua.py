"""Copiar a régua-modelo do pós-venda para uma loja (RG2, Maratona 5).

A cópia CANCELA os passos já agendados da régua anterior (motivo regua_trocada). Por isso o script
mostra ANTES quantos serão cancelados e só copia com confirmação: digitando SIM, ou com --confirmar.

Na raiz do projeto:
  python scripts/copiar_regua.py --loja 2                    mostra o que vai acontecer e pergunta
  python scripts/copiar_regua.py --loja 2 --modelo essencial --confirmar
  python scripts/copiar_regua.py --todas --confirmar         todas as lojas, cada uma com a régua que já usa
Sem --modelo: a régua-modelo que a loja já usa (ou a padrão do segmento, se ela ainda não tem).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app import regua  # noqa: E402


def _lojas_existentes() -> list[int]:
    from app.lojas_admin import listar_lojas
    return [l["id"] for l in listar_lojas()]


def copiar(loja_id: int, modelo: str | None, confirmar: bool, entrada=None, saida=print) -> dict | None:
    nome = modelo or regua.modelo_em_uso(loja_id)
    previa = regua.previa_da_copia(loja_id, nome)
    saida(f"Loja {loja_id}: régua '{previa['modelo']}' ({', '.join(previa['passos'])}). "
          f"{previa['agendados']} passo(s) agendado(s) da régua de agora serão cancelados.")
    if not confirmar:
        resposta = (entrada or input)("Digite SIM para copiar: ").strip().upper()
        if resposta != "SIM":
            saida("Nada mudou.")
            return None
    regua.copiar_regua_modelo(loja_id, previa["modelo"], confirmar=True)
    saida(f"Loja {loja_id}: régua copiada; {previa['agendados']} agendado(s) cancelado(s) (regua_trocada).")
    return previa


def main(argv=None, entrada=None, saida=print) -> int:
    parser = argparse.ArgumentParser(description="Copia a régua-modelo do pós-venda para a loja.")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--loja", type=int)
    grupo.add_argument("--todas", action="store_true")
    parser.add_argument("--modelo", help="nome da régua-modelo (ex.: proxima, essencial)")
    parser.add_argument("--confirmar", action="store_true", help="copia sem perguntar")
    args = parser.parse_args(argv)
    from app.ator import como
    with como("Script copiar_regua", "operador", "job", None):
        for loja_id in (_lojas_existentes() if args.todas else [args.loja]):
            try:
                copiar(loja_id, args.modelo, args.confirmar, entrada=entrada, saida=saida)
            except regua.ReguaInexistente as erro:
                saida(f"Loja {loja_id}: {erro}")
    return 0


if __name__ == "__main__":
    import banco as _banco                  # SE3: este programa vê todas as lojas (modo sistema)
    _banco.declarar_sistema("scripts/copiar_regua.py")
    raise SystemExit(main())

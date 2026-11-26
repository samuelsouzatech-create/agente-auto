"""Cofre dos tokens dos canais (SE2, Maratona Segurança). Diário: docs/seguranca.md.

Na raiz do projeto:
  python scripts/cofre.py nova-chave
      mostra uma chave mestra nova. Ponha no .env como LEO_CHAVE_MESTRA=<chave> (e guarde uma
      cópia fora do computador: sem ela, os tokens guardados não abrem).
  python scripts/cofre.py cadastrar --loja 2 --canal whatsapp --conta <phone_number_id>
      pede o token (não aparece na tela enquanto você cola) e guarda CIFRADO. Rodar de novo TROCA.
  python scripts/cofre.py apagar --loja 2 --canal whatsapp --conta <phone_number_id>
  python scripts/cofre.py situacao
      o que está guardado (nunca o token) e se abre com a chave do .env.
  python scripts/cofre.py trocar-chave
      recifra tudo com a chave nova. Antes: ponha a chave nova no .env como LEO_CHAVE_MESTRA_NOVA
      (a atual continua em LEO_CHAVE_MESTRA). Depois: troque LEO_CHAVE_MESTRA pela nova, apague a
      LEO_CHAVE_MESTRA_NOVA e reinicie o Léo (docker compose up -d).

O token e a chave nunca aparecem na tela, no log nem no Registro.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app import cofre  # noqa: E402


def _ler_token(entrada) -> str:
    if entrada is sys.stdin and sys.stdin.isatty():
        return getpass.getpass("Cole o token (não aparece na tela) e aperte Enter: ")
    return entrada.readline()


def main(argv=None, entrada=None) -> int:
    entrada = entrada or sys.stdin
    parser = argparse.ArgumentParser(description="Cofre dos tokens dos canais.")
    sub = parser.add_subparsers(dest="acao", required=True)
    sub.add_parser("nova-chave")
    sub.add_parser("situacao")
    sub.add_parser("trocar-chave")
    for nome in ("cadastrar", "apagar"):
        p = sub.add_parser(nome)
        p.add_argument("--loja", type=int, required=True)
        p.add_argument("--canal", choices=cofre.TIPOS, required=True)
        p.add_argument("--conta", required=True, help="phone_number_id, conta do Instagram ou id do bot")
    args = parser.parse_args(argv)
    try:
        if args.acao == "nova-chave":
            print(cofre.nova_chave())
            print("Ponha no .env como LEO_CHAVE_MESTRA=... e guarde uma cópia fora do computador.", file=sys.stderr)
        elif args.acao == "cadastrar":
            token = _ler_token(entrada).strip()
            cofre.guardar_token(args.loja, args.canal, args.conta, token)
            print(f"Guardado (cifrado): loja {args.loja}, {args.canal}, conta {args.conta}.")
        elif args.acao == "apagar":
            feito = cofre.apagar_token(args.loja, args.canal, args.conta)
            print("Apagado." if feito else "Não havia token guardado para esta conta.")
        elif args.acao == "situacao":
            linhas = cofre.situacao()
            if not linhas:
                print("Nenhum token no cofre (o envio usa o token_ref do .env, se houver).")
            for l in linhas:
                abre = "abre com a chave do .env" if l["abre_com_a_chave_do_env"] else "NÃO abre com a chave do .env"
                print(f"loja {l['loja_id']}: {l['canal']} {l['conta']} ({abre}; atualizado em {l['atualizado_em']} UTC)")
        elif args.acao == "trocar-chave":
            nova = os.environ.get("LEO_CHAVE_MESTRA_NOVA") or ""
            if not nova:
                print("Falta a LEO_CHAVE_MESTRA_NOVA no .env (gere com: python scripts/cofre.py nova-chave).")
                return 1
            n = cofre.trocar_chave_mestra(os.environ.get("LEO_CHAVE_MESTRA") or "", nova)
            print(f"{n} token(s) recifrado(s) com a chave nova. Agora troque a LEO_CHAVE_MESTRA do .env pela "
                  "nova, apague a LEO_CHAVE_MESTRA_NOVA e reinicie o Léo.")
    except (cofre.ErroCofre, ValueError) as erro:
        print(f"Erro: {erro}")
        return 1
    return 0


if __name__ == "__main__":
    import banco as _banco                  # SE3: este programa vê todas as lojas (modo sistema)
    _banco.declarar_sistema("scripts/cofre.py")
    raise SystemExit(main())

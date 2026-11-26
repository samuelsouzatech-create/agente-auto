"""Backup do banco, cifrado (SE2, Maratona Segurança). Diário: docs/seguranca.md.

Na raiz do projeto:
  python scripts/backup.py nova-chave
      mostra uma chave nova. Ponha no .env como LEO_CHAVE_BACKUP=<chave> e GUARDE UMA CÓPIA FORA
      do computador/servidor (sem ela, nenhum backup abre).
  python scripts/backup.py fazer
      faz o backup do banco do .env (BANCO_URL), cifrado, no destino (LEO_BACKUP_DESTINO; padrão:
      a pasta backups/, fora do Git).
  python scripts/backup.py restaurar <arquivo> --banco leo_conferencia
      restaura num banco NOVO e separado (leo_conferencia) no mesmo servidor, e mostra as contagens
      de cada tabela ao lado das do banco de uso. Nunca restaura por cima do banco de uso.
  python scripts/backup.py conferir <arquivo>
      restaura num banco temporário, compara as contagens com as do banco de uso e apaga o temporário.

Onde o pg_dump roda: veja app/backup.py (o do computador, se for 17+, ou o do contêiner do banco).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import banco  # noqa: E402
from app import backup  # noqa: E402


def _comparar(origem: dict, copia: dict) -> bool:
    iguais = True
    for tabela in sorted(set(origem) | set(copia)):
        a, b = origem.get(tabela), copia.get(tabela)
        marca = "ok" if a == b else "DIFERENTE"
        iguais &= a == b
        print(f"  {tabela:32} uso={a!s:>8}  backup={b!s:>8}  {marca}")
    return iguais


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Backup cifrado do banco do Léo.")
    sub = parser.add_subparsers(dest="acao", required=True)
    sub.add_parser("nova-chave")
    sub.add_parser("fazer")
    r = sub.add_parser("restaurar")
    r.add_argument("arquivo")
    r.add_argument("--banco", required=True, help="nome do banco NOVO (ex.: leo_conferencia)")
    c = sub.add_parser("conferir")
    c.add_argument("arquivo")
    args = parser.parse_args(argv)
    url = banco.url_do_dono()            # SE3: o pg_dump lê tudo (o dono passa por cima da tranca)
    try:
        if args.acao == "nova-chave":
            print(backup.nova_chave())
            print("Ponha no .env como LEO_CHAVE_BACKUP=... e guarde uma cópia FORA do servidor.", file=sys.stderr)
        elif args.acao == "fazer":
            print(f"Backup cifrado feito: {backup.fazer_backup(url)}")
        elif args.acao in ("restaurar", "conferir"):
            nome = args.banco if args.acao == "restaurar" else banco.nome_do_banco(url) + "_conferencia_backup"
            destino = banco.trocar_nome_do_banco(url, nome)
            backup.restaurar(args.arquivo, destino)
            print(f"Restaurado no banco {nome}. Contagens:")
            iguais = _comparar(backup.contagens(url), backup.contagens(destino))
            if args.acao == "conferir":
                backup.apagar_banco(destino)
                print("Banco temporário apagado.")
            print("Tudo igual." if iguais else "Há diferenças (normal se o banco de uso mudou depois do backup).")
    except backup.ErroBackup as erro:
        print(f"Erro: {erro}")
        return 1
    return 0


if __name__ == "__main__":
    import banco as _banco                  # SE3: este programa vê todas as lojas (modo sistema)
    _banco.declarar_sistema("scripts/backup.py")
    raise SystemExit(main())

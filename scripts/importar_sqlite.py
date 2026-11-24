"""
PG2 (Maratona Postgres): copia o banco antigo (SQLite, loja.db) para o PostgreSQL.

Uso (na pasta do projeto, com o banco ligado: docker compose up -d):
    python scripts/importar_sqlite.py --ensaio          # só confere e conta; não grava nada
    python scripts/importar_sqlite.py                   # copia de verdade
    python scripts/importar_sqlite.py --origem outro.db

Regras:
- O loja.db é aberto SÓ PARA LEITURA e precisa estar na versão 20 (a última do SQLite).
- Cada linha vai com o MESMO id. Rodar duas vezes não duplica nada: a linha que já existe é
  atualizada com o que está no loja.db.
- Tudo numa transação: no fim, a contagem de cada tabela no PostgreSQL tem de ser igual à do
  loja.db. Se alguma diferir (por exemplo, o PostgreSQL já tinha outros dados), NADA é gravado
  e o script para com erro, mostrando a tabela.
- Este é o ÚNICO arquivo do Léo que usa sqlite3 (só para ler o banco antigo).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import banco  # noqa: E402

VERSAO_ESPERADA = 20


class ImportacaoRecusada(RuntimeError):
    """Algo não confere: nada foi gravado."""


def abrir_origem(caminho: Path) -> sqlite3.Connection:
    if not caminho.exists():
        raise ImportacaoRecusada(f"Não achei o arquivo {caminho}.")
    conexao = sqlite3.connect(f"file:{caminho.as_posix()}?mode=ro", uri=True)
    conexao.row_factory = sqlite3.Row
    versao = conexao.execute("PRAGMA user_version").fetchone()[0]
    if versao != VERSAO_ESPERADA:
        conexao.close()
        raise ImportacaoRecusada(
            f"O {caminho.name} está na versão {versao}; a importação precisa da versão "
            f"{VERSAO_ESPERADA}. Abra-o uma vez com a versão anterior do Léo (antes do PostgreSQL).")
    return conexao


def tabelas_da_origem(origem: sqlite3.Connection) -> dict[str, list[str]]:
    nomes = [r[0] for r in origem.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {t: [c[1] for c in origem.execute(f'PRAGMA table_info("{t}")')] for t in nomes}


def _chave_primaria(conexao, tabela: str) -> list[str]:
    return [r[0] for r in conexao.execute(
        "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid "
        "AND a.attnum = ANY(i.indkey) WHERE i.indrelid = CAST(? AS regclass) AND i.indisprimary "
        "ORDER BY a.attnum", (tabela,)).fetchall()]


def conferir_estrutura(origem_tabelas: dict[str, list[str]]) -> list[str]:
    """Problemas de estrutura (tabela ou coluna que não existe no PostgreSQL)."""
    if banco.versao_schema() < VERSAO_ESPERADA:
        return ["O PostgreSQL ainda não tem as tabelas: rode python banco.py antes."]
    destino = set(banco.tabelas())
    problemas = []
    for tabela, colunas in origem_tabelas.items():
        if tabela not in destino:
            problemas.append(f"{tabela}: não existe no PostgreSQL")
            continue
        faltam = [c for c in colunas if c not in set(banco.colunas(tabela))]
        if faltam:
            problemas.append(f"{tabela}: colunas que não existem no PostgreSQL: {', '.join(faltam)}")
    return problemas


def _contar_destino(conexao, tabela: str) -> int:
    return int(conexao.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0])


def importar(caminho: Path, *, ensaio: bool, saida=print) -> dict[str, tuple[int, int]]:
    """Devolve {tabela: (antes no SQLite, depois no PostgreSQL)}. Levanta ImportacaoRecusada."""
    origem = abrir_origem(caminho)
    try:
        estrutura = tabelas_da_origem(origem)
        problemas = conferir_estrutura(estrutura)
        if problemas:
            raise ImportacaoRecusada("A estrutura não confere:\n  - " + "\n  - ".join(problemas))
        antes = {t: int(origem.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]) for t in estrutura}
        conexao = banco.conectar()
        try:
            if ensaio:
                resultado = {t: (antes[t], _contar_destino(conexao, t)) for t in estrutura}
                _mostrar(resultado, saida, ensaio=True)
                return resultado
            for tabela, colunas in estrutura.items():
                linhas = [tuple(l) for l in origem.execute(
                    f'SELECT {", ".join(chr(34) + c + chr(34) for c in colunas)} FROM "{tabela}"')]
                if not linhas:
                    continue
                chave = _chave_primaria(conexao, tabela)
                if not chave:
                    raise ImportacaoRecusada(f"{tabela}: sem chave primária no PostgreSQL.")
                resto = [c for c in colunas if c not in chave]
                atualizar = (f"DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in resto)}"
                             if resto else "DO NOTHING")
                conexao.executemany(
                    f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES "
                    f"({', '.join(['?'] * len(colunas))}) ON CONFLICT ({', '.join(chave)}) {atualizar}",
                    linhas)
            resultado = {t: (antes[t], _contar_destino(conexao, t)) for t in estrutura}
            diferentes = [t for t, (a, d) in resultado.items() if a != d]
            if diferentes:
                conexao.rollback()
                _mostrar(resultado, saida, ensaio=False)
                raise ImportacaoRecusada(
                    "A contagem não bateu em: " + ", ".join(diferentes) + ". NADA foi gravado. "
                    "O PostgreSQL já tinha outros dados nessas tabelas?")
            conexao.commit()
        finally:
            conexao.close()
        banco.acertar_contadores()            # o próximo id automático vem depois do maior
        _mostrar(resultado, saida, ensaio=False)
        return resultado
    finally:
        origem.close()


def _mostrar(resultado, saida, *, ensaio: bool) -> None:
    cabeca = "no PostgreSQL hoje" if ensaio else "no PostgreSQL depois"
    saida(f"{'tabela':<24} {'no loja.db':>11} {cabeca:>22}")
    for tabela, (antes, depois) in sorted(resultado.items()):
        marca = "" if ensaio or antes == depois else "  <- diferente"
        saida(f"{tabela:<24} {antes:>11} {depois:>22}{marca}")
    total = sum(a for a, _ in resultado.values())
    saida(f"{len(resultado)} tabelas, {total} linhas no loja.db.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Copia o loja.db (SQLite) para o PostgreSQL.")
    parser.add_argument("--origem", default=str(RAIZ / "loja.db"), help="arquivo SQLite (padrão: loja.db)")
    parser.add_argument("--ensaio", action="store_true", help="só confere e conta; não grava nada")
    args = parser.parse_args(argv)
    destino = banco.url_sem_senha(banco.url_do_banco())
    print(f"Origem: {args.origem}\nDestino: {destino}\n"
          + ("ENSAIO: nada será gravado.\n" if args.ensaio else ""))
    try:
        importar(Path(args.origem), ensaio=args.ensaio)
    except ImportacaoRecusada as erro:
        print(f"\nPAROU: {erro}")
        return 1
    print("\nEnsaio conferido: a estrutura bate e as contagens estão acima." if args.ensaio
          else "\nImportação conferida: todas as contagens batem.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

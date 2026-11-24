r"""
Leva para o DEPÓSITO as fotos do estoque já cadastradas (Maratona Fotos, F1).

    .venv-teste\Scripts\python scripts\migrar_fotos.py            (todas as lojas)
    .venv-teste\Scripts\python scripts\migrar_fotos.py --loja 4   (só uma loja)

- Arquivo da demo (ou outro arquivo do computador) e link https: passam pelo preparo único
  (app/fotos.py) e o carro passa a guardar a referência do depósito.
- O que falhar fica listado no terminal e continua no carro como estava: NADA é apagado.
- Rodar de novo é seguro: foto que já está no depósito fica como está.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


def migrar(loja_id: int | None = None, transporte=None) -> dict:
    """Migra as fotos e devolve {'carros', 'migradas', 'falhas': [(loja, carro, modelo, entrada, motivo)]}."""
    from app import fotos
    from banco import conectar
    conexao = conectar()
    try:
        sql = "SELECT id, loja_id, marca, modelo, ano, fotos FROM estoque WHERE TRIM(COALESCE(fotos, '')) <> ''"
        parametros: tuple = ()
        if loja_id is not None:
            sql += " AND loja_id = ?"
            parametros = (loja_id,)
        carros = [dict(l) for l in conexao.execute(sql + " ORDER BY loja_id, id", parametros)]
    finally:
        conexao.close()
    resumo = {"carros": 0, "migradas": 0, "falhas": []}
    for c in carros:
        novo, migradas, falhas = fotos.migrar_texto(c["loja_id"], c["fotos"], transporte=transporte)
        resumo["carros"] += 1
        resumo["migradas"] += migradas
        nome = f"{c['marca']} {c['modelo']} {c['ano']}"
        resumo["falhas"].extend((c["loja_id"], c["id"], nome, e, m) for e, m in falhas)
        if migradas:
            conexao = conectar()
            try:
                conexao.execute("UPDATE estoque SET fotos = ? WHERE id = ? AND loja_id = ?",
                                (novo, c["id"], c["loja_id"]))
                conexao.commit()
            finally:
                conexao.close()
    return resumo


def main(argv=None) -> int:
    import argparse
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Leva as fotos do estoque para o depósito.")
    parser.add_argument("--loja", type=int, help="só esta loja")
    args = parser.parse_args(argv)
    import banco
    banco.criar_tabelas()
    r = migrar(args.loja)
    print(f"Carros com foto: {r['carros']}. Fotos levadas para o depósito: {r['migradas']}.")
    if r["falhas"]:
        print(f"Não deu para levar {len(r['falhas'])} foto(s) (continuam no carro como estavam):")
        for loja, carro, nome, entrada, motivo in r["falhas"]:
            print(f"  loja {loja}, carro {carro} ({nome}): {entrada[:90]} -> {motivo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

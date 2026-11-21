r"""
Reinicia a loja de DEMONSTRAÇÃO (Maratona 2, D3): apaga conversas, leads, chamados, vendas e o
resto SÓ da loja marcada como demo e recria o estado inicial. Recusa qualquer outra loja.

    .venv-teste\Scripts\python scripts\reiniciar_demo.py
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


def main(argv=None) -> int:
    import argparse
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Reinicia a loja de demonstração.")
    parser.add_argument("--sem-indexar", action="store_true", help="não indexa a base de conhecimento")
    args = parser.parse_args(argv)
    from app.ator import como_sistema
    from app.demo import NOME_DEMO, id_da_loja_demo, reiniciar_demo
    loja_id = id_da_loja_demo()
    if loja_id is None:
        print("Não existe loja de demonstração. Crie com: scripts\\criar_loja_demo.py")
        return 1
    with como_sistema("Script reiniciar_demo", "job"):
        reiniciar_demo(loja_id, indexar=not args.sem_indexar)
    print(f"Demo reiniciada: {NOME_DEMO} (número {loja_id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

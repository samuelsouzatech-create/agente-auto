r"""
Cria (ou recria) a loja de DEMONSTRAÇÃO "Recife Seminovos Demo" (Maratona 2, D1).

    .venv-teste\Scripts\python scripts\criar_loja_demo.py

Loja fictícia, No ar, só com o canal simulador e envios "só simulando". Estoque com fotos
ilustrativas geradas aqui (pasta demo_fotos, fora do Git), políticas na base, equipe fictícia
sem contato e 30 dias de histórico. Indexa a base de conhecimento (usa a chave do Gemini do .env
do projeto, custo muito baixo); sem rede, a base fica no banco e pode ser reindexada depois.
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
    parser = argparse.ArgumentParser(description="Cria a loja de demonstração.")
    parser.add_argument("--sem-indexar", action="store_true", help="não indexa a base de conhecimento")
    args = parser.parse_args(argv)
    import banco
    from app.ator import como_sistema
    from app.demo import NOME_DEMO, criar_loja_demo
    banco.criar_tabelas()
    with como_sistema("Script criar_loja_demo", "job"):
        loja_id = criar_loja_demo(indexar=not args.sem_indexar)
    print(f"Loja de demonstração pronta: {NOME_DEMO} (número {loja_id}).")
    return 0


if __name__ == "__main__":
    import banco as _banco                  # SE3: este programa vê todas as lojas (modo sistema)
    _banco.declarar_sistema("scripts/criar_loja_demo.py")
    raise SystemExit(main())

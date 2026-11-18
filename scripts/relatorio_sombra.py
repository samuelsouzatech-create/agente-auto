"""
Relatório do MODO SOMBRA (L9): o que o Léo teria respondido, num dia, numa loja.

Uso (não gasta IA; só lê o banco):
    .venv-teste\\Scripts\\python scripts\\relatorio_sombra.py --loja 1
    .venv-teste\\Scripts\\python scripts\\relatorio_sombra.py --loja 1 --dia 2026-11-18

--loja é obrigatório: uma loja nunca vê a outra. O dia é no fuso da loja.
Saída: logs/sombra/sombra_loja<id>_<dia>.md (o nome do cliente não aparece; o número
aparece só com os 4 últimos dígitos).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

PASTA = RAIZ / "logs" / "sombra"


def _cliente(lead_id: str) -> str:
    digitos = "".join(c for c in str(lead_id) if c.isdigit())
    return f"…{digitos[-4:]}" if len(digitos) >= 4 else "cliente"


def _celula(texto: str) -> str:
    return " ".join(str(texto or "").split()).replace("|", "/") or "—"


def montar(loja_id: int, dia: date) -> str:
    from app.chaves import exigir_loja
    from app.lojas import carregar_loja
    from app.relogio import do_banco, fuso, hora_local, limites_do_dia_em_utc
    from app.sombra import sugestoes_do_dia

    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    inicio, fim = limites_do_dia_em_utc(str(fuso(loja)), dia)
    linhas = sugestoes_do_dia(loja_id, inicio, fim)
    saida = [f"# Modo sombra — {loja.nome} — {dia:%d/%m/%Y}", "",
             f"{len(linhas)} mensagem(ns) de cliente. Nada disto foi enviado: é o que o assistente "
             "teria respondido. A última coluna é a primeira resposta da equipe ao mesmo cliente, se houver.",
             "", "| Hora | Cliente | Mensagem do cliente | Sugestão do Léo | Ferramentas | Vendedor respondeu |",
             "|---|---|---|---|---|---|"]
    for l in linhas:
        hora = hora_local(loja, do_banco(l["criado_em"])).strftime("%H:%M")
        saida.append(f"| {hora} | {_cliente(l['lead_id'])} | {_celula(l['mensagem_cliente'])} | "
                     f"{_celula(l['sugestao'])} | {', '.join(l['ferramentas']) or '—'} | "
                     f"{_celula(l['resposta_vendedor'])} |")
    return "\n".join(saida) + "\n"


def main(argv=None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Relatório do modo sombra (um dia, uma loja).")
    parser.add_argument("--loja", type=int, required=True, help="id da loja (obrigatório)")
    parser.add_argument("--dia", help="AAAA-MM-DD no fuso da loja (padrão: hoje)")
    args = parser.parse_args(argv)
    from app.lojas import carregar_loja
    from app.relogio import agora_utc, dia_local
    dia = date.fromisoformat(args.dia) if args.dia else dia_local(carregar_loja(args.loja), agora_utc())
    PASTA.mkdir(parents=True, exist_ok=True)
    destino = PASTA / f"sombra_loja{args.loja}_{dia.isoformat()}.md"
    destino.write_text(montar(args.loja, dia), encoding="utf-8")
    print(f"Relatório: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

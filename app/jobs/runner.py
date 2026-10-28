"""
O "relógio" do sistema (Etapa 1, Bloco 7B). Processo separado que, a cada
ciclo, confere o que precisa ser avisado. Na Etapa 2, remarketing e
pós-venda entram aqui como tarefas novas.

Rodar num terminal só para ele (com a venv ativa):
    python -m app.jobs.runner             fica rodando (Ctrl+C para parar)
    python -m app.jobs.runner --uma-vez   roda um ciclo e sai

Rode UM runner só por banco.
"""
from __future__ import annotations

import argparse
import time
import traceback
from datetime import datetime

import banco
from app import avisos, config
from app.jobs.alertas import rodar_ciclo

INTERVALO_S = 30


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Relógio do sistema: avisos e alertas.")
    parser.add_argument("--uma-vez", action="store_true", help="roda um ciclo e sai")
    parser.add_argument("--intervalo", type=int, default=INTERVALO_S, help="segundos entre ciclos")
    args = parser.parse_args(argv)

    banco.criar_tabelas()
    if not (config.TELEGRAM_AVISOS_TOKEN or "").strip():
        print("[Runner] AVISO: TELEGRAM_AVISOS_TOKEN vazio no .env. Os avisos vão falhar.")
    if not avisos.chat_do_operador():
        print("[Runner] AVISO: TELEGRAM_AVISOS_OPERADOR_CHAT_ID vazio. Alerta de gasto sem destino.")
    print(f"[Runner] Ligado. Ciclo a cada {args.intervalo}s. Ctrl+C para parar.")

    try:
        while True:
            try:
                r = rodar_ciclo()
                if r["handoffs"] or r["gastos"]:
                    print(f"[Runner] {datetime.now():%H:%M:%S} avisos enviados: "
                          f"handoff={r['handoffs']} gasto={r['gastos']}")
            except Exception:
                traceback.print_exc()
            if args.uma_vez:
                break
            time.sleep(max(5, args.intervalo))
    except KeyboardInterrupt:
        print("\n[Runner] Parado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

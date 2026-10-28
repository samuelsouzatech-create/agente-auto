"""
O "relógio" do sistema (Etapa 1, Bloco 7B; trava na revisão).

Rodar num terminal só para ele (venv ativa e Redis ligado):
    python -m app.jobs.runner             fica rodando (Ctrl+C para parar)
    python -m app.jobs.runner --uma-vez   roda um ciclo e sai

Trava no Redis: se já existir outro runner ligado, este sai na hora.
Sem Redis, o runner NÃO liga (--sem-trava existe só para teste local).
"""
from __future__ import annotations

import argparse
import time
import traceback
from datetime import datetime

import banco
from app import avisos, config
from app.jobs.alertas import rodar_ciclo
from app.jobs.trava import TTL_S, TravaRunner, cliente_redis_sincrono

INTERVALO_S = 30


def _pegar_trava(intervalo: int):
    """Devolve (trava, None) ou (None, motivo)."""
    try:
        trava = TravaRunner(cliente_redis_sincrono(), ttl=max(TTL_S, intervalo * 3))
        if not trava.adquirir():
            return None, "já existe outro runner ligado (trava no Redis). Este vai sair."
        return trava, None
    except Exception as erro:
        return None, (f"Redis indisponível ({type(erro).__name__}). Sem a trava o runner não liga. "
                      "Ligue o Redis (Docker) ou use --sem-trava só para teste.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Relógio do sistema: avisos e alertas.")
    parser.add_argument("--uma-vez", action="store_true", help="roda um ciclo e sai")
    parser.add_argument("--intervalo", type=int, default=INTERVALO_S, help="segundos entre ciclos")
    parser.add_argument("--sem-trava", action="store_true", help="SÓ PARA TESTE: liga sem Redis")
    args = parser.parse_args(argv)
    intervalo = max(5, args.intervalo)

    banco.criar_tabelas()
    trava = None
    if args.sem_trava:
        print("[Runner] AVISO: rodando SEM trava. Não use assim com clientes reais.")
    else:
        trava, motivo = _pegar_trava(intervalo)
        if trava is None:
            print(f"[Runner] {motivo}")
            return 1

    if not (config.TELEGRAM_AVISOS_TOKEN or "").strip():
        print("[Runner] AVISO: TELEGRAM_AVISOS_TOKEN vazio no .env. Os avisos vão falhar.")
    if not avisos.chat_do_operador():
        print("[Runner] AVISO: TELEGRAM_AVISOS_OPERADOR_CHAT_ID vazio. Alerta de gasto sem destino.")
    print(f"[Runner] Ligado. Ciclo a cada {intervalo}s. Ctrl+C para parar.")

    try:
        while True:
            if trava is not None:
                try:
                    if not trava.renovar():
                        print("[Runner] Perdi a trava (outro runner assumiu?). Parando.")
                        break
                except Exception as erro:
                    print(f"[Runner] Redis falhou ao renovar a trava ({type(erro).__name__}). Parando.")
                    break
            try:
                r = rodar_ciclo()
                if r["handoffs"] or r["gastos"]:
                    print(f"[Runner] {datetime.now():%H:%M:%S} avisos enviados: "
                          f"handoff={r['handoffs']} gasto={r['gastos']}")
            except Exception:
                traceback.print_exc()
            if args.uma_vez:
                break
            time.sleep(intervalo)
    except KeyboardInterrupt:
        print("\n[Runner] Parado.")
    finally:
        if trava is not None:
            trava.liberar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

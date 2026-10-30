"""
O "relógio" do sistema (Etapa 1, Bloco 7B; trava na revisão; Etapa 2, Blocos 3, 5A e 6C).

Rodar num terminal só para ele (venv ativa e Redis ligado):
    python -m app.jobs.runner                    fica rodando (Ctrl+C para parar)
    python -m app.jobs.runner --uma-vez          roda um ciclo e sai
    python -m app.jobs.runner --sem-remarketing  sem remarketing
    python -m app.jobs.runner --sem-pos-venda    sem pós-venda
    python -m app.jobs.runner --sem-reativacao   sem reativação

A cada ciclo (30 s): avisos de handoff e alerta de gasto.
A cada 5 min: remarketing, pós-venda e reativação (simulação, a menos que
REMARKETING_ENVIO_REAL=1 / POS_VENDA_ENVIO_REAL=1 / REATIVACAO_ENVIO_REAL=1).

Trava no Redis: se já existir outro runner ligado, este sai na hora.
Sem Redis, o runner NÃO liga (--sem-trava existe só para teste local).
"""
from __future__ import annotations

import argparse
import time
import traceback
from datetime import datetime

import banco
from app import avisos, config, precos
from app.jobs.alertas import rodar_ciclo
from app.jobs.pos_venda import INTERVALO_S as INTERVALO_POS_VENDA_S
from app.jobs.pos_venda import envio_real_ligado as pos_venda_real_ligado
from app.jobs.pos_venda import rodar_pos_venda
from app.jobs.reativacao import INTERVALO_S as INTERVALO_REATIVACAO_S
from app.jobs.reativacao import envio_real_ligado as reativacao_real_ligado
from app.jobs.reativacao import rodar_reativacao
from app.jobs.remarketing import INTERVALO_S as INTERVALO_REMARKETING_S
from app.jobs.remarketing import envio_real_ligado, rodar_remarketing
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


def _na_vez(ultimo, intervalo) -> bool:
    return ultimo is None or time.monotonic() - ultimo >= intervalo


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Relógio do sistema: avisos, alertas, remarketing, pós-venda e reativação.")
    parser.add_argument("--uma-vez", action="store_true", help="roda um ciclo e sai")
    parser.add_argument("--intervalo", type=int, default=INTERVALO_S, help="segundos entre ciclos")
    parser.add_argument("--sem-trava", action="store_true", help="SÓ PARA TESTE: liga sem Redis")
    parser.add_argument("--sem-remarketing", action="store_true", help="não roda o remarketing")
    parser.add_argument("--sem-pos-venda", action="store_true", help="não roda o pós-venda")
    parser.add_argument("--sem-reativacao", action="store_true", help="não roda a reativação")
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
    faltam_precos = precos.faltando()
    if faltam_precos:
        print(f"[Runner] AVISO: preço da IA não cadastrado ({', '.join(faltam_precos)}). "
              "O custo fica zero e o alerta de gasto não dispara. Cadastre na tela Custos.")
    if args.sem_remarketing:
        print("[Runner] Remarketing desligado nesta execução.")
    elif envio_real_ligado():
        print("[Runner] Remarketing: ENVIO REAL ligado (REMARKETING_ENVIO_REAL=1).")
    else:
        print("[Runner] Remarketing: SIMULAÇÃO (nada é enviado ao cliente).")
    if args.sem_pos_venda:
        print("[Runner] Pós-venda desligado nesta execução.")
    elif pos_venda_real_ligado():
        print("[Runner] Pós-venda: ENVIO REAL ligado (POS_VENDA_ENVIO_REAL=1).")
    else:
        print("[Runner] Pós-venda: SIMULAÇÃO (nada é enviado ao cliente).")
    if args.sem_reativacao:
        print("[Runner] Reativação desligada nesta execução.")
    elif reativacao_real_ligado():
        print("[Runner] Reativação: ENVIO REAL ligado (REATIVACAO_ENVIO_REAL=1).")
    else:
        print("[Runner] Reativação: SIMULAÇÃO (nada é enviado ao cliente).")
    print(f"[Runner] Ligado. Ciclo a cada {intervalo}s. Ctrl+C para parar.")

    ultimo_remarketing = None
    ultimo_pos_venda = None
    ultimo_reativacao = None
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

            if not args.sem_remarketing and _na_vez(ultimo_remarketing, INTERVALO_REMARKETING_S):
                ultimo_remarketing = time.monotonic()
                try:
                    t = rodar_remarketing()
                    feitos = {k: v for k, v in t.items() if v and k != "pulado"}
                    if feitos:
                        print(f"[Runner] {datetime.now():%H:%M:%S} remarketing: {feitos}")
                except Exception:
                    traceback.print_exc()

            if not args.sem_pos_venda and _na_vez(ultimo_pos_venda, INTERVALO_POS_VENDA_S):
                ultimo_pos_venda = time.monotonic()
                try:
                    t = rodar_pos_venda()
                    feitos = {k: v for k, v in t.items() if v and k != "adiado"}
                    if feitos:
                        print(f"[Runner] {datetime.now():%H:%M:%S} pós-venda: {feitos}")
                except Exception:
                    traceback.print_exc()

            if not args.sem_reativacao and _na_vez(ultimo_reativacao, INTERVALO_REATIVACAO_S):
                ultimo_reativacao = time.monotonic()
                try:
                    t = rodar_reativacao()
                    feitos = {k: v for k, v in t.items() if v and k != "adiado"}
                    if feitos:
                        print(f"[Runner] {datetime.now():%H:%M:%S} reativação: {feitos}")
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

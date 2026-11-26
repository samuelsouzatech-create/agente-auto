"""
Vigia (SE1, Maratona Segurança): confere a saúde do Léo a cada minuto e avisa o OPERADOR pelo bot de
avisos que já existe (Telegram, app/avisos.py) quando algo quebra.

Roda como peça própria do Docker (serviço "vigia"), separada do relógio: se o relógio parar, quem
avisa é o vigia. Rodar à mão: python -m app.vigia (fica rodando) ou python -m app.vigia --uma-vez.

O que ele confere (as regras são as MESMAS da Visão geral do operador, app/visao_geral.py):
- banco: o PostgreSQL responde a uma consulta;
- redis: o Redis responde ao ping;
- relógio: o sinal de vida no Redis está vermelho (parado ou sem girar há 2 min);
- webhook: canal de uma loja No ar sem mensagem de cliente há muito mais tempo que o normal DELA
  (5 vezes o intervalo médio, no mínimo 18 h: a regra do "canal parado" da Visão geral);
- IA: 3 erros ou mais da IA na última hora (o vermelho da Visão geral);
- peças do Docker: cada peça responde no endereço de saúde dela, pela rede interna (VIGIA_PECAS).
  O vigia NÃO usa o docker.sock (dar o socket a um contêiner é dar a máquina inteira).

Avisos: no máximo UM por problema a cada 30 minutos (enquanto continuar, um lembrete a cada 30
min), e um "voltou ao normal" quando o problema some. Nunca derruba nada: erro ao conferir vira
problema; erro ao avisar fica só no terminal. O estado fica na memória (o banco e o Redis podem
ser justamente o que caiu): se o vigia reiniciar, o problema que continua é avisado de novo uma vez.

O vigia não avisa se o SERVIDOR INTEIRO cair (ele cai junto). Para isso: monitor de fora
(docs/seguranca.md, SE1).
"""
from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

REPETIR_S = 30 * 60
INTERVALO_S = 60
PECAS_PADRAO = ("webhook=http://webhook:8000/,api-painel=http://api-painel:8001/api/v1/saude,"
                "operador=http://operador:8502/_stcore/health,porteiro=http://porteiro:80/")
NOMES = {"banco": "Banco de dados", "redis": "Redis (memória rápida)", "relogio": "Relógio",
         "ia": "IA"}


def pecas_do_ambiente() -> dict[str, str]:
    """VIGIA_PECAS="nome=endereço,nome=endereço" (vazio = as peças de sempre do docker-compose)."""
    texto = os.environ.get("VIGIA_PECAS", PECAS_PADRAO)
    pecas = {}
    for par in texto.split(","):
        nome, _, endereco = par.strip().partition("=")
        if nome.strip() and endereco.strip():
            pecas[nome.strip()] = endereco.strip()
    return pecas


def sonda_http(endereco: str) -> bool:
    """A peça respondeu (qualquer código < 500), como o docker/saude.py."""
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(endereco, timeout=5) as resposta:
            return resposta.status < 500
    except urllib.error.HTTPError as erro:
        return erro.code < 500
    except Exception:
        return False


def _banco_responde() -> bool:
    from banco import conectar
    try:
        conexao = conectar(somente_leitura=True)
        try:
            conexao.execute("SELECT 1").fetchone()
        finally:
            conexao.close()
        return True
    except Exception:
        return False


def conferir(agora: datetime | None = None, *, cliente_redis=None, banco_ok: Callable[[], bool] | None = None,
             sonda: Callable[[str], bool] | None = None, pecas: dict[str, str] | None = None) -> dict[str, str]:
    """Os problemas de AGORA: chave -> texto. Vazio = tudo certo."""
    from app import alertas_config as cfg
    from app import visao_geral as vg
    agora = agora or datetime.now(timezone.utc)
    problemas: dict[str, str] = {}

    banco = (banco_ok or _banco_responde)()
    if not banco:
        problemas["banco"] = "O banco de dados não responde. O Léo não consegue atender."

    if cliente_redis is None:
        try:
            cliente_redis = vg.cliente_redis()
        except Exception:
            cliente_redis = None
    redis_ok = cliente_redis is not None and vg._redis_responde(cliente_redis)
    if not redis_ok:
        problemas["redis"] = "O Redis não responde. O relógio e a fila de mensagens param."
    else:
        relogio = vg._item_relogio(cliente_redis, agora)
        if relogio["nivel"] == vg.VERMELHO:
            problemas["relogio"] = (f"Relógio parado ({relogio['texto']}). Avisos de chamado, alerta de "
                                    "gasto e retomadas não estão rodando.")

    if banco:
        try:
            conexao = vg._ler()
            try:
                ia = vg._ia_ultima_hora(conexao, agora)
            finally:
                conexao.close()
            if ia["erros"] >= cfg.IA_ERROS_VERMELHO:
                problemas["ia"] = f"A IA errou {ia['erros']} vez(es) na última hora."
            for d in vg.dados_das_lojas(agora):
                if not d["ativo"] or d["estado"] != vg.NO_AR:
                    continue
                for c in d["canais"]:
                    if c["situacao"] == vg.CANAL_SILENCIO:
                        problemas[f"webhook:{d['loja_id']}:{c['canal']}"] = (
                            f"{d['nome']}: {vg.nome_do_canal(c['canal'])} sem mensagem de cliente "
                            f"{vg._ha_quanto(c['silencio_s'])} (o normal desta loja é uma a cada "
                            f"{vg._duracao(c['media_s'])}). Confira se o webhook está recebendo.")
        except Exception as erro:
            problemas["conferencia"] = f"Não consegui conferir as lojas ({type(erro).__name__})."

    sonda = sonda or sonda_http
    for nome, endereco in (pecas if pecas is not None else pecas_do_ambiente()).items():
        if not sonda(endereco):
            problemas[f"peca:{nome}"] = f"A peça {nome} do Docker não responde (sem saúde)."
    return problemas


def _enviar_ao_operador(texto: str) -> bool:
    from app import avisos
    chat = avisos.chat_do_operador()
    if not chat:
        print(f"[Vigia] Sem TELEGRAM_AVISOS_OPERADOR_CHAT_ID: {texto}")
        return False
    ok, erro = avisos._enviar(chat, texto)
    if not ok:
        print(f"[Vigia] Não consegui avisar o operador ({erro}): {texto}")
    return ok


@dataclass
class Vigia:
    """Decide QUANDO avisar. 'enviar' recebe o texto (nos testes, um envio falso)."""
    enviar: Callable[[str], object] = _enviar_ao_operador
    repetir_s: int = REPETIR_S
    abertos: dict = field(default_factory=dict)        # chave -> texto do problema avisado
    ultimo_aviso: dict = field(default_factory=dict)   # chave -> quando (segundos) avisou por último

    def rodada(self, problemas: dict[str, str], agora_s: float | None = None) -> list[str]:
        """Recebe os problemas de agora e manda o que precisa. Devolve os textos enviados."""
        agora_s = time.monotonic() if agora_s is None else agora_s
        enviados = []
        for chave, texto in problemas.items():
            ultimo = self.ultimo_aviso.get(chave)
            if ultimo is not None and agora_s - ultimo < self.repetir_s:
                if chave not in self.abertos:          # voltou a quebrar logo depois de voltar:
                    self.abertos[chave] = None         # espera os 30 min (no máximo 1 aviso)
                continue
            prefixo = "Continua" if self.abertos.get(chave) else "Problema"
            enviados.append(f"[Léo] {prefixo}: {texto}")
            self.abertos[chave] = texto
            self.ultimo_aviso[chave] = agora_s
        for chave in [c for c in self.abertos if c not in problemas]:
            if self.abertos[chave]:                   # só avisa "voltou" do que foi avisado
                nome = NOMES.get(chave) or chave.split(":", 1)[0]
                enviados.append(f"[Léo] Voltou ao normal: {self._rotulo(chave, nome)}")
                self.ultimo_aviso[chave] = agora_s
            del self.abertos[chave]
        for texto in enviados:
            try:
                self.enviar(texto)
            except Exception as erro:
                print(f"[Vigia] Erro ao avisar: {type(erro).__name__}")
        return enviados

    def _rotulo(self, chave: str, nome: str) -> str:
        if chave.startswith("peca:"):
            return f"a peça {chave[5:]} do Docker responde de novo."
        if chave.startswith("webhook:"):
            return "o canal voltou a receber mensagens de cliente."
        return f"{nome} de volta."


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Vigia: avisa o operador quando algo do Léo quebra.")
    parser.add_argument("--uma-vez", action="store_true", help="confere uma vez e sai")
    parser.add_argument("--intervalo", type=int, default=INTERVALO_S, help="segundos entre conferências")
    args = parser.parse_args(argv)
    vigia = Vigia()
    print(f"[Vigia] Ligado. Confere a cada {max(15, args.intervalo)}s.")
    try:
        while True:
            try:
                vigia.rodada(conferir())
            except Exception as erro:
                print(f"[Vigia] Erro na conferência: {type(erro).__name__}")
            if args.uma_vez:
                break
            time.sleep(max(15, args.intervalo))
    except KeyboardInterrupt:
        print("\n[Vigia] Parado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

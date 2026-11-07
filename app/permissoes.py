"""
Quem pode agir por uma loja (S5 do Plano Mestre, Fase 3; decisão D7).

Loja Em teste: o operador age por ela (assumir, responder, registrar venda,
"Não enviar"). Loja No ar: o operador só vê; quem age é a equipe da loja.

A regra fica aqui, em app/, e não só na tela: as funções que fazem a ação
chamam exigir_pode_agir() antes de mudar qualquer coisa. Chamar a função
direto também é recusado.

Chamam exigir_pode_agir:
  app.handoff.assumir_conversa, app.handoff.assumir_handoff (o "Assumir" da
  fila antiga chama esta direto; sem ela a trava teria uma porta lateral),
  app.envio_painel.enviar_pelo_painel, app.vendas.registrar_venda,
  app.bloqueios.bloquear.

Ficam LIVRES em qualquer estado, de propósito:
  - pausar e retomar os envios (app/pausa.py): é o freio de emergência;
  - devolver ao assistente (app.handoff.devolver_ao_agente): sem isso, uma
    conversa assumida em teste ficaria muda depois de a loja ir ao ar;
  - os robôs (papel 'sistema') e a equipe da loja (papel 'cliente').
"""
from __future__ import annotations

from app.chaves import exigir_loja
from app.registro import conferir_ator

MENSAGEM = ("Esta loja está No ar: pelo painel do operador dá só para ver. "
            "Quem age é a equipe da loja. Pausar os envios continua liberado.")


class AcaoNaoPermitida(PermissionError):
    """O motivo vem pronto para mostrar na tela."""


def _loja_no_ar(loja_id) -> bool:
    from app.estado_loja import esta_no_ar   # aqui dentro: evita import circular
    return esta_no_ar(loja_id)


def operador_pode_agir(loja_id) -> bool:
    """Para a tela decidir se mostra os botões. A trava de verdade é a de baixo."""
    return not _loja_no_ar(exigir_loja(loja_id))


def exigir_pode_agir(loja_id):
    """Sem ator: SemAtor. Ator de outra loja: AtorInvalido.
    Operador com a loja No ar: AcaoNaoPermitida. Devolve o ator conferido."""
    loja_id = exigir_loja(loja_id)
    ator = conferir_ator(loja_id)
    if ator.papel == "operador" and _loja_no_ar(loja_id):
        raise AcaoNaoPermitida(MENSAGEM)
    return ator

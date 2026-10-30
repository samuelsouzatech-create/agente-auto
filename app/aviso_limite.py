"""
Aviso de limite mensal atingido (Etapa 2, item 2.5 passo 6).

Quando o limite do mês (remarketing + reativação) acaba e ainda tem gente
esperando contato, o gestor e o operador recebem UM aviso no Telegram por
mês, por loja. Os envios param sozinhos (a elegibilidade já barra);
aqui só garantimos que alguém fique sabendo.
"""
from __future__ import annotations

from datetime import datetime

from app import avisos
from app.elegibilidade import candidatos, vagas_no_mes
from app.lojas import Loja
from app.relogio import dia_local
from app.usuarios import contatos_para_aviso

TIPO = "limite_mensal"


def barrados_pelo_limite(loja_id: int, agora: datetime) -> int:
    """Quantos leads só não recebem por causa do limite (0 = nada a avisar)."""
    if vagas_no_mes(loja_id, agora) > 0:
        return 0
    return sum(1 for d in candidatos(loja_id, agora) if d.motivo == "limite_mensal")


def texto_do_aviso(loja: Loja, barrados: int) -> str:
    limite = loja.get("remarketing.limite_mensal")
    return (f"📵 {loja.nome}: o limite de {limite} mensagens de retomada deste mês acabou.\n\n"
            f"{barrados} cliente(s) estão prontos para receber contato e vão esperar o próximo mês.\n"
            "O assistente continua respondendo normalmente quem escrever.\n"
            "Para aumentar o limite: painel do operador > Plano e limites.")


def avisar_limite(loja: Loja, agora: datetime, *, real: bool) -> bool:
    """Devolve True se havia o que avisar."""
    barrados = barrados_pelo_limite(loja.id, agora)
    if not barrados:
        return False
    texto = texto_do_aviso(loja, barrados)
    if not real:
        print(f"[Remarketing][loja {loja.id}] SIMULADO: aviso de limite do mês ({barrados} esperando).")
        return True
    destinos = [u["contato_telegram"] for u in contatos_para_aviso(loja.id, "gestor")]
    operador = avisos.chat_do_operador()
    if operador:
        destinos.append(operador)
    mes = dia_local(loja, agora).strftime("%Y-%m")
    avisos.avisar_uma_vez(loja.id, TIPO, f"loja:{loja.id}:{mes}", destinos, texto)
    return True

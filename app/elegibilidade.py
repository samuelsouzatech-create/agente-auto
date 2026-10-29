"""
Quem a loja pode procurar AGORA (Etapa 2, Bloco 2).

Uma função decide: avaliar(loja_id, lead_id, canal, agora) -> Decisao.
Não envia nem grava nada: o job (Bloco 3) e a tela (Bloco 6) perguntam aqui.
Horas sempre em UTC; o horário de envio é o do fuso da loja.

Ordem das conferências (a primeira que barrar decide o motivo):
  loja : desativada, módulo desligado, limite do contrato não definido,
         canal sem envio por iniciativa da loja
  lead : não quer contato / sem interesse, já comprou, teto de toques,
         conversa com vendedor, pediu um tempo
  tempo: nunca conversou, respondeu depois do último toque, intervalo
         ainda não passou, limite do mês, fora do horário de envio

Toques: só os ENVIADOS contam (simulado, falhou e bloqueado não gastam
o teto nem o limite). Teto vale por lead e canal (UNIQUE da migração 5).
Intervalos: o 1º toque usa remarketing.primeiro_toque_h, contado da última
mensagem da conversa (de qualquer lado); o toque N usa intervalos_h[N-1],
contado do toque anterior. Nunca antes de 24 h da última fala do cliente.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from banco import conectar
from app.chaves import exigir_loja
from app.interesse import pode_contatar, situacao_do_lead
from app.janela import janela_aberta, ultima_mensagem_do_cliente
from app.lojas import (
    MIN_HORAS_SEM_RESPOSTA, TETO_TOQUES_REMARKETING, carregar_loja, modulo_ativo,
)
from app.relogio import dia_local, do_banco, fuso, hora_local, para_banco

CANAIS_COM_REMARKETING = ("whatsapp", "telegram")   # telegram: modo de testes
HORARIO_ENVIO_PADRAO = "09:00-19:00"
DIAS_ENVIO_PADRAO = (0, 1, 2, 3, 4, 5)
PRIMEIRO_TOQUE_PADRAO_H = 48
INTERVALOS_PADRAO_H = (48, 120, 288)

ROTULOS = {
    "elegivel": "Pode receber agora",
    "loja_inativa": "Loja desativada",
    "modulo_desligado": "Remarketing desligado nesta loja",
    "limite_nao_definido": "Limite mensal do contrato ainda não definido",
    "canal_sem_envio": "Este canal não recebe mensagem por iniciativa da loja",
    "nao_contatar": "Pediu para não ser procurado",
    "sem_interesse": "Disse que não tem interesse",
    "pediu_tempo": "Pediu um tempo",
    "ja_comprou": "Já comprou",
    "teto_atingido": "Já recebeu o número máximo de contatos",
    "com_vendedor": "Conversa com vendedor",
    "sem_conversa": "Nunca conversou com a loja neste canal",
    "respondeu": "Respondeu depois do último contato",
    "aguardando_intervalo": "Ainda não deu o tempo do próximo contato",
    "limite_mensal": "Limite de contatos do mês atingido",
    "fora_do_horario": "Fora do horário de envio",
}


@dataclass(frozen=True)
class Decisao:
    loja_id: int
    lead_id: str
    canal: str
    elegivel: bool
    motivo: str
    toque: int | None = None             # número do PRÓXIMO toque
    proximo_em: datetime | None = None   # quando pode (UTC), se der para saber
    janela_aberta: bool | None = None    # só calculada quando elegível

    @property
    def rotulo(self) -> str:
        return ROTULOS.get(self.motivo, self.motivo)


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


# ------------------------------------------------------------ horário

def _faixa_envio(loja) -> tuple[time, time]:
    faixa = loja.get("remarketing.horario_envio") or HORARIO_ENVIO_PADRAO
    inicio, fim = faixa.split("-")
    return time.fromisoformat(inicio), time.fromisoformat(fim)


def _dias_envio(loja) -> set[int]:
    return set(loja.get("remarketing.dias_envio") or DIAS_ENVIO_PADRAO)


def no_horario_de_envio(loja, quando: datetime) -> bool:
    local = hora_local(loja, _utc(quando))
    inicio, fim = _faixa_envio(loja)
    return local.weekday() in _dias_envio(loja) and inicio <= local.time() < fim


def proxima_abertura(loja, quando: datetime) -> datetime:
    """'quando', se já estiver no horário; senão, a próxima abertura (UTC)."""
    quando = _utc(quando)
    if no_horario_de_envio(loja, quando):
        return quando
    inicio, _ = _faixa_envio(loja)
    dias = _dias_envio(loja)
    local = hora_local(loja, quando)
    for d in range(8):
        dia = local.date() + timedelta(days=d)
        if dia.weekday() not in dias:
            continue
        abertura = datetime.combine(dia, inicio, tzinfo=fuso(loja))
        if abertura > local:
            return abertura.astimezone(timezone.utc)
    return quando   # não acontece: o validador exige ao menos um dia


def _inicio_do_dia_utc(loja, dia: date) -> datetime:
    return datetime.combine(dia, time(0), tzinfo=fuso(loja)).astimezone(timezone.utc)


def _inicio_do_mes(loja, agora: datetime) -> datetime:
    local = hora_local(loja, agora)
    return datetime(local.year, local.month, 1, tzinfo=fuso(loja))


def _inicio_do_proximo_mes(loja, agora: datetime) -> datetime:
    local = hora_local(loja, agora)
    ano, mes = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return datetime(ano, mes, 1, tzinfo=fuso(loja)).astimezone(timezone.utc)


# ------------------------------------------------------------ consultas

def _consulta(sql: str, parametros: tuple):
    conexao = conectar()
    try:
        return conexao.execute(sql, parametros).fetchall()
    finally:
        conexao.close()


def _toques_enviados(loja_id: int, lead_id: str, canal: str) -> list[datetime]:
    linhas = _consulta(
        "SELECT COALESCE(enviado_em, criado_em) AS quando FROM remarketing_envios "
        "WHERE loja_id = ? AND lead_id = ? AND canal = ? AND estado = 'enviado' "
        "ORDER BY toque",
        (loja_id, lead_id, canal),
    )
    return [do_banco(l["quando"]) for l in linhas]


def _ja_comprou(loja_id: int, lead_id: str) -> bool:
    return bool(_consulta(
        "SELECT 1 FROM resultados WHERE loja_id = ? AND lead_id = ? AND resultado = 'comprou' "
        "UNION SELECT 1 FROM vendas WHERE loja_id = ? AND lead_id = ? LIMIT 1",
        (loja_id, lead_id, loja_id, lead_id),
    ))


def _com_vendedor(loja_id: int, lead_id: str) -> bool:
    return bool(_consulta(
        "SELECT 1 FROM handoffs WHERE loja_id = ? AND lead_id = ? "
        "AND estado IN ('aguardando_humano', 'humano_assumiu') LIMIT 1",
        (loja_id, lead_id),
    ))


def _ultima_atividade(loja_id: int, lead_id: str, canal: str) -> datetime | None:
    linha = _consulta(
        "SELECT MAX(criado_em) AS quando FROM mensagens "
        "WHERE loja_id = ? AND lead_id = ? AND canal = ?",
        (loja_id, lead_id, canal),
    )
    return do_banco(linha[0]["quando"]) if linha and linha[0]["quando"] else None


def enviados_no_mes(loja_id, agora: datetime) -> int:
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    inicio = para_banco(_inicio_do_mes(loja, _utc(agora)))
    linha = _consulta(
        "SELECT COUNT(*) AS n FROM remarketing_envios WHERE loja_id = ? "
        "AND estado = 'enviado' AND COALESCE(enviado_em, criado_em) >= ?",
        (loja_id, inicio),
    )
    return int(linha[0]["n"])


def vagas_no_mes(loja_id, agora: datetime) -> int:
    loja_id = exigir_loja(loja_id)
    limite = carregar_loja(loja_id).get("remarketing.limite_mensal")
    if limite is None:
        return 0
    return max(0, int(limite) - enviados_no_mes(loja_id, agora))


# ------------------------------------------------------------ regras de tempo

def _max_toques(loja) -> int:
    return min(int(loja.get("remarketing.max_toques") or TETO_TOQUES_REMARKETING),
               TETO_TOQUES_REMARKETING)


def _horas_ate_o_toque(loja, toque: int) -> int:
    if toque == 1:
        return int(loja.get("remarketing.primeiro_toque_h") or PRIMEIRO_TOQUE_PADRAO_H)
    intervalos = list(loja.get("remarketing.intervalos_h") or INTERVALOS_PADRAO_H)
    return int(intervalos[min(toque - 1, len(intervalos) - 1)])


# ------------------------------------------------------------ decisão

def avaliar(loja_id, lead_id, canal: str, agora: datetime) -> Decisao:
    loja_id = exigir_loja(loja_id)
    lead_id = str(lead_id)
    agora = _utc(agora)
    loja = carregar_loja(loja_id)

    def nao(motivo, proximo_em=None, toque=None) -> Decisao:
        return Decisao(loja_id, lead_id, canal, False, motivo, toque, proximo_em)

    # --- loja
    if not loja.ativo:
        return nao("loja_inativa")
    if not modulo_ativo(loja, "remarketing"):
        return nao("modulo_desligado")
    limite = loja.get("remarketing.limite_mensal")
    if limite is None:
        return nao("limite_nao_definido")
    if canal not in CANAIS_COM_REMARKETING:
        return nao("canal_sem_envio")

    # --- lead
    if not pode_contatar(loja_id, lead_id, dia_local(loja, agora)):
        situacao = situacao_do_lead(loja_id, lead_id)
        if situacao and situacao["situacao"] == "pediu_tempo" and situacao.get("retomar_em"):
            volta = _inicio_do_dia_utc(loja, date.fromisoformat(situacao["retomar_em"]))
            return nao("pediu_tempo", proxima_abertura(loja, volta))
        if situacao and situacao["situacao"] == "sem_interesse":
            return nao("sem_interesse")
        return nao("nao_contatar")
    if _ja_comprou(loja_id, lead_id):
        return nao("ja_comprou")
    toques = _toques_enviados(loja_id, lead_id, canal)
    if len(toques) >= _max_toques(loja):
        return nao("teto_atingido")
    toque = len(toques) + 1
    if _com_vendedor(loja_id, lead_id):
        return nao("com_vendedor", toque=toque)

    # --- tempo
    ultima_cliente = ultima_mensagem_do_cliente(loja_id, lead_id, canal)
    if ultima_cliente is None:
        return nao("sem_conversa", toque=toque)
    if toques:
        if ultima_cliente > toques[-1]:
            return nao("respondeu", toque=toque)
        alvo = toques[-1] + timedelta(hours=_horas_ate_o_toque(loja, toque))
    else:
        base = _ultima_atividade(loja_id, lead_id, canal) or ultima_cliente
        alvo = base + timedelta(hours=_horas_ate_o_toque(loja, 1))
    alvo = max(alvo, ultima_cliente + timedelta(hours=MIN_HORAS_SEM_RESPOSTA))
    if agora < alvo:
        return nao("aguardando_intervalo", proxima_abertura(loja, alvo), toque)
    if enviados_no_mes(loja_id, agora) >= int(limite):
        return nao("limite_mensal",
                   proxima_abertura(loja, _inicio_do_proximo_mes(loja, agora)), toque)
    if not no_horario_de_envio(loja, agora):
        return nao("fora_do_horario", proxima_abertura(loja, agora), toque)

    return Decisao(loja_id, lead_id, canal, True, "elegivel", toque, agora,
                   janela_aberta(loja_id, lead_id, canal, agora))


def candidatos(loja_id, agora: datetime) -> list[Decisao]:
    """Todos os leads que já falaram com a loja, com a decisão de cada um
    (para a tela). Mais antigo primeiro: quem espera há mais tempo vem antes."""
    loja_id = exigir_loja(loja_id)
    marcas = ",".join("?" for _ in CANAIS_COM_REMARKETING)
    linhas = _consulta(
        f"SELECT lead_id, canal, MAX(criado_em) AS ultima FROM mensagens "
        f"WHERE loja_id = ? AND direcao = 'cliente' AND canal IN ({marcas}) "
        f"GROUP BY lead_id, canal ORDER BY ultima, lead_id",
        (loja_id, *CANAIS_COM_REMARKETING),
    )
    return [avaliar(loja_id, l["lead_id"], l["canal"], agora) for l in linhas]


def elegiveis(loja_id, agora: datetime) -> list[Decisao]:
    """Só quem pode receber agora, cortado nas vagas que sobram no mês."""
    loja_id = exigir_loja(loja_id)
    prontos = [d for d in candidatos(loja_id, agora) if d.elegivel]
    return prontos[:vagas_no_mes(loja_id, agora)]

"""
Quem a loja pode procurar AGORA (Etapa 2, Bloco 2; P5 e S6 do Plano Mestre).

Uma regra só decide (a função de decisão deste arquivo). Duas formas de
buscar os dados para ela:
  avaliar(loja_id, lead_id, canal, agora): UM cliente, consultando o banco
      na hora. É o que o robô usa na reconferência logo antes de enviar.
  fotografia(loja_id, agora) + decidir(foto, lead_id, canal): a loja
      inteira lida de uma vez (S6): poucas consultas por loja, nenhuma por
      cliente. É o que a lista (candidatos, elegiveis e as telas) usa.
Um teste (tests/test_s6_mensagens.py) prova que as duas dão o mesmo
resultado para todos os motivos.

Não envia nem grava nada. Horas sempre em UTC; o horário de envio é o do
fuso da loja.

Ordem das conferências (a primeira que barrar decide o motivo):
  loja : desativada, módulo desligado, limite do contrato não definido,
         canal sem envio por iniciativa da loja
  lead : não quer contato / sem interesse, já comprou, teto de toques,
         a loja marcou "não enviar" (P5), conversa com vendedor,
         carência depois do atendimento (P5)
  tempo: nunca conversou, respondeu depois do último toque, intervalo
         ainda não passou, limite do mês, fora do horário de envio

Toques: só os ENVIADOS contam (simulado, falhou e bloqueado não gastam
o teto nem o limite). Teto vale por lead e canal (UNIQUE da migração 5).
Intervalos: o 1º toque usa remarketing.primeiro_toque_h, contado da última
mensagem da conversa (de qualquer lado); o toque N usa intervalos_h[N-1],
contado do toque anterior. Nunca antes de 24 h da última fala do cliente.

Carência (P5): sem retomada por remarketing.carencia_dias depois que um
vendedor atendeu ou uma visita foi marcada (a visita conta do dia em que
foi marcada: a data combinada é texto livre; decisão A7). 0 = desligada.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from banco import conectar
from app.bloqueios import bloqueado
from app.chaves import exigir_loja
from app.interesse import pode_contatar, situacao_do_lead
from app.janela import (
    CANAIS_COM_JANELA, CANAIS_SEM_JANELA, DURACAO_JANELA, MARGEM_SEGURANCA,
    janela_aberta, ultima_mensagem_do_cliente,
)
from app.lojas import (
    MIN_HORAS_SEM_RESPOSTA, TETO_TOQUES_REMARKETING, carregar_loja, modulo_ativo,
)
from app.relogio import dia_local, do_banco, fuso, hora_local, para_banco

CANAIS_COM_REMARKETING = ("whatsapp", "telegram")   # telegram: modo de testes
HORARIO_ENVIO_PADRAO = "09:00-19:00"
DIAS_ENVIO_PADRAO = (0, 1, 2, 3, 4, 5)
PRIMEIRO_TOQUE_PADRAO_H = 48
INTERVALOS_PADRAO_H = (48, 120, 288)
CARENCIA_PADRAO_DIAS = 7

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
    "bloqueado_pela_loja": "A loja marcou para não enviar",
    "com_vendedor": "Conversa com vendedor",
    "carencia": "Pausa depois do atendimento com vendedor ou da visita marcada",
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


def _limpo(texto) -> str:
    return " ".join(str(texto or "").split())


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


# ------------------------------------------------------------ consultas de UM cliente

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


def _dias_de_carencia(loja) -> int:
    dias = loja.get("remarketing.carencia_dias", CARENCIA_PADRAO_DIAS)
    return CARENCIA_PADRAO_DIAS if dias is None else int(dias)


def _marco_da_carencia(loja_id: int, lead_id: str) -> datetime | None:
    """Último atendimento de vendedor ou visita marcada (UTC), ou None."""
    linha = _consulta(
        "SELECT MAX(quando) AS quando FROM ("
        " SELECT COALESCE(encerrado_em, assumido_em) AS quando FROM handoffs"
        " WHERE loja_id = ? AND lead_id = ? AND assumido_em IS NOT NULL"
        " UNION ALL"
        " SELECT criado_em AS quando FROM agendamentos WHERE loja_id = ? AND lead_id = ?)",
        (loja_id, lead_id, loja_id, lead_id),
    )
    if not linha or not linha[0]["quando"]:
        return None
    return do_banco(linha[0]["quando"])


def _fim_da_carencia(loja, loja_id: int, lead_id: str) -> datetime | None:
    """P5: quando acaba a pausa depois do atendimento. None = sem pausa."""
    dias = _dias_de_carencia(loja)
    if dias <= 0:
        return None
    marco = _marco_da_carencia(loja_id, lead_id)
    return marco + timedelta(days=dias) if marco else None


def _ultima_atividade(loja_id: int, lead_id: str, canal: str) -> datetime | None:
    linha = _consulta(
        "SELECT MAX(criado_em) AS quando FROM mensagens "
        "WHERE loja_id = ? AND lead_id = ? AND canal = ?",
        (loja_id, lead_id, canal),
    )
    return do_banco(linha[0]["quando"]) if linha and linha[0]["quando"] else None


def enviados_no_mes(loja_id, agora: datetime) -> int:
    """Remarketing + reativação (Bloco 6C) dividem o mesmo limite mensal."""
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    inicio = para_banco(_inicio_do_mes(loja, _utc(agora)))
    linha = _consulta(
        "SELECT (SELECT COUNT(*) FROM remarketing_envios WHERE loja_id = ? "
        "        AND estado = 'enviado' AND COALESCE(enviado_em, criado_em) >= ?) "
        "     + (SELECT COUNT(*) FROM reativacao WHERE loja_id = ? "
        "        AND estado = 'enviado' AND enviado_em >= ?) AS n",
        (loja_id, inicio, loja_id, inicio),
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


# ------------------------------------------------------------ as duas formas de buscar

class _FonteBanco:
    """UM cliente, consultando o banco na hora (as mesmas consultas de antes do S6)."""

    def __init__(self, loja_id: int, lead_id: str, canal: str, agora: datetime):
        self.loja_id, self.lead_id, self.canal, self.agora = loja_id, lead_id, canal, agora

    def pode_contatar(self, hoje: date) -> bool:
        return pode_contatar(self.loja_id, self.lead_id, hoje)

    def situacao(self):
        return situacao_do_lead(self.loja_id, self.lead_id)

    def ja_comprou(self) -> bool:
        return _ja_comprou(self.loja_id, self.lead_id)

    def toques(self) -> list[datetime]:
        return _toques_enviados(self.loja_id, self.lead_id, self.canal)

    def bloqueado(self, toque: int) -> bool:
        return bloqueado(self.loja_id, self.lead_id, "remarketing", toque)

    def com_vendedor(self) -> bool:
        return _com_vendedor(self.loja_id, self.lead_id)

    def marco_carencia(self):
        return _marco_da_carencia(self.loja_id, self.lead_id)

    def ultima_cliente(self):
        return ultima_mensagem_do_cliente(self.loja_id, self.lead_id, self.canal)

    def ultima_atividade(self):
        return _ultima_atividade(self.loja_id, self.lead_id, self.canal)

    def enviados_no_mes(self) -> int:
        return enviados_no_mes(self.loja_id, self.agora)

    def janela_aberta(self) -> bool:
        return janela_aberta(self.loja_id, self.lead_id, self.canal, self.agora)


@dataclass
class Fotografia:
    """A loja inteira lida de uma vez (S6). Chaves: lead_id, ou (lead_id, canal)."""
    loja: object
    loja_id: int
    agora: datetime
    enviados_no_mes: int
    conversas: list = field(default_factory=list)          # [(lead_id, canal)], na ordem da fila
    ultima_cliente: dict = field(default_factory=dict)     # (lead, canal) -> datetime
    ultima_atividade: dict = field(default_factory=dict)   # (lead, canal) -> datetime
    optouts: set = field(default_factory=set)
    situacoes: dict = field(default_factory=dict)          # lead -> linha de situacao_lead
    compraram: set = field(default_factory=set)
    toques: dict = field(default_factory=dict)             # (lead, canal) -> [datetime]
    bloqueios: dict = field(default_factory=dict)          # lead -> [(tipo, passo)]
    com_vendedor: set = field(default_factory=set)
    marco_carencia: dict = field(default_factory=dict)     # lead -> datetime


def fotografia(loja_id, agora: datetime) -> Fotografia:
    """Lê tudo que a decisão precisa, para todos os clientes, com consultas
    agrupadas por loja (nenhuma consulta por cliente)."""
    loja_id = exigir_loja(loja_id)
    agora = _utc(agora)
    loja = carregar_loja(loja_id)
    foto = Fotografia(loja=loja, loja_id=loja_id, agora=agora,
                      enviados_no_mes=enviados_no_mes(loja_id, agora))
    canais = tuple(CANAIS_COM_REMARKETING)
    marcas = ",".join("?" for _ in canais)
    conexao = conectar()
    try:
        def ler(sql, parametros):
            return conexao.execute(sql, parametros).fetchall()

        for l in ler(f"SELECT lead_id, canal, MAX(criado_em) AS ultima FROM mensagens "
                     f"WHERE loja_id = ? AND direcao = 'cliente' AND canal IN ({marcas}) "
                     f"GROUP BY lead_id, canal ORDER BY ultima, lead_id", (loja_id, *canais)):
            chave = (str(l["lead_id"]), l["canal"])
            foto.conversas.append(chave)
            if l["ultima"]:
                foto.ultima_cliente[chave] = do_banco(l["ultima"])
        for l in ler(f"SELECT lead_id, canal, MAX(criado_em) AS ultima FROM mensagens "
                     f"WHERE loja_id = ? AND canal IN ({marcas}) GROUP BY lead_id, canal",
                     (loja_id, *canais)):
            if l["ultima"]:
                foto.ultima_atividade[(str(l["lead_id"]), l["canal"])] = do_banco(l["ultima"])
        foto.optouts = {str(l["lead_id"]) for l in ler(
            "SELECT DISTINCT lead_id FROM optouts WHERE loja_id = ?", (loja_id,))}
        foto.situacoes = {str(l["lead_id"]): dict(l) for l in ler(
            "SELECT * FROM situacao_lead WHERE loja_id = ?", (loja_id,))}
        foto.compraram = {str(l["lead_id"]) for l in ler(
            "SELECT lead_id FROM resultados WHERE loja_id = ? AND resultado = 'comprou' "
            "UNION SELECT lead_id FROM vendas WHERE loja_id = ?", (loja_id, loja_id))}
        for l in ler("SELECT lead_id, canal, COALESCE(enviado_em, criado_em) AS quando "
                     "FROM remarketing_envios WHERE loja_id = ? AND estado = 'enviado' "
                     "ORDER BY lead_id, canal, toque", (loja_id,)):
            foto.toques.setdefault((str(l["lead_id"]), l["canal"]), []).append(do_banco(l["quando"]))
        for l in ler("SELECT lead_id, tipo, passo FROM bloqueios_envio WHERE loja_id = ? "
                     "AND desfeito_em IS NULL AND tipo IN ('todos', 'remarketing')", (loja_id,)):
            foto.bloqueios.setdefault(_limpo(l["lead_id"]), []).append((l["tipo"], l["passo"]))
        foto.com_vendedor = {str(l["lead_id"]) for l in ler(
            "SELECT DISTINCT lead_id FROM handoffs WHERE loja_id = ? "
            "AND estado IN ('aguardando_humano', 'humano_assumiu')", (loja_id,))}
        for l in ler("SELECT lead_id, MAX(quando) AS quando FROM ("
                     " SELECT lead_id, COALESCE(encerrado_em, assumido_em) AS quando FROM handoffs"
                     " WHERE loja_id = ? AND assumido_em IS NOT NULL"
                     " UNION ALL"
                     " SELECT lead_id, criado_em AS quando FROM agendamentos WHERE loja_id = ?)"
                     " GROUP BY lead_id", (loja_id, loja_id)):
            if l["quando"]:
                foto.marco_carencia[str(l["lead_id"])] = do_banco(l["quando"])
    finally:
        conexao.close()
    return foto


class _FonteFoto:
    """Os dados de um cliente, tirados da fotografia (sem ir ao banco)."""

    def __init__(self, foto: Fotografia, lead_id: str, canal: str):
        self.f, self.lead_id, self.canal = foto, lead_id, canal
        self.chave = (lead_id, canal)

    def pode_contatar(self, hoje: date) -> bool:
        # Mesma regra de app/interesse.py (pode_contatar), lida de uma vez.
        if self.lead_id in self.f.optouts:
            return False
        situacao = self.f.situacoes.get(self.lead_id)
        if situacao is None:
            return True
        if situacao["situacao"] == "pediu_tempo" and situacao.get("retomar_em"):
            return hoje >= date.fromisoformat(situacao["retomar_em"])
        return False

    def situacao(self):
        return self.f.situacoes.get(self.lead_id)

    def ja_comprou(self) -> bool:
        return self.lead_id in self.f.compraram

    def toques(self) -> list[datetime]:
        return list(self.f.toques.get(self.chave, []))

    def bloqueado(self, toque: int) -> bool:
        # Mesma regra de app/bloqueios.py (bloqueio_ativo).
        for tipo, passo in self.f.bloqueios.get(_limpo(self.lead_id), ()):
            if tipo == "todos" or passo is None or int(passo) == int(toque):
                return True
        return False

    def com_vendedor(self) -> bool:
        return self.lead_id in self.f.com_vendedor

    def marco_carencia(self):
        return self.f.marco_carencia.get(self.lead_id)

    def ultima_cliente(self):
        return self.f.ultima_cliente.get(self.chave)

    def ultima_atividade(self):
        return self.f.ultima_atividade.get(self.chave)

    def enviados_no_mes(self) -> int:
        return self.f.enviados_no_mes

    def janela_aberta(self) -> bool:
        # Mesma regra de app/janela.py (janela_aberta).
        if self.canal in CANAIS_SEM_JANELA:
            return True
        if self.canal not in CANAIS_COM_JANELA:
            return False
        ultima = self.ultima_cliente()
        return ultima is not None and self.f.agora < ultima + DURACAO_JANELA - MARGEM_SEGURANCA


# ------------------------------------------------------------ decisão (a regra única)

def _decidir(loja, loja_id: int, lead_id: str, canal: str, agora: datetime, fonte) -> Decisao:
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
    if not fonte.pode_contatar(dia_local(loja, agora)):
        situacao = fonte.situacao()
        if situacao and situacao["situacao"] == "pediu_tempo" and situacao.get("retomar_em"):
            volta = _inicio_do_dia_utc(loja, date.fromisoformat(situacao["retomar_em"]))
            return nao("pediu_tempo", proxima_abertura(loja, volta))
        if situacao and situacao["situacao"] == "sem_interesse":
            return nao("sem_interesse")
        return nao("nao_contatar")
    if fonte.ja_comprou():
        return nao("ja_comprou")
    toques = fonte.toques()
    if len(toques) >= _max_toques(loja):
        return nao("teto_atingido")
    toque = len(toques) + 1
    if fonte.bloqueado(toque):
        return nao("bloqueado_pela_loja", toque=toque)
    if fonte.com_vendedor():
        return nao("com_vendedor", toque=toque)
    dias = _dias_de_carencia(loja)
    marco = fonte.marco_carencia() if dias > 0 else None
    if marco is not None:
        fim_carencia = marco + timedelta(days=dias)
        if agora < fim_carencia:
            return nao("carencia", proxima_abertura(loja, fim_carencia), toque)

    # --- tempo
    ultima_cliente = fonte.ultima_cliente()
    if ultima_cliente is None:
        return nao("sem_conversa", toque=toque)
    if toques:
        if ultima_cliente > toques[-1]:
            return nao("respondeu", toque=toque)
        alvo = toques[-1] + timedelta(hours=_horas_ate_o_toque(loja, toque))
    else:
        base = fonte.ultima_atividade() or ultima_cliente
        alvo = base + timedelta(hours=_horas_ate_o_toque(loja, 1))
    alvo = max(alvo, ultima_cliente + timedelta(hours=MIN_HORAS_SEM_RESPOSTA))
    if agora < alvo:
        return nao("aguardando_intervalo", proxima_abertura(loja, alvo), toque)
    if fonte.enviados_no_mes() >= int(limite):
        return nao("limite_mensal",
                   proxima_abertura(loja, _inicio_do_proximo_mes(loja, agora)), toque)
    if not no_horario_de_envio(loja, agora):
        return nao("fora_do_horario", proxima_abertura(loja, agora), toque)

    return Decisao(loja_id, lead_id, canal, True, "elegivel", toque, agora, fonte.janela_aberta())


def avaliar(loja_id, lead_id, canal: str, agora: datetime) -> Decisao:
    """UM cliente, direto do banco. É a reconferência do robô antes de enviar."""
    loja_id = exigir_loja(loja_id)
    lead_id = str(lead_id)
    agora = _utc(agora)
    loja = carregar_loja(loja_id)
    return _decidir(loja, loja_id, lead_id, canal, agora,
                    _FonteBanco(loja_id, lead_id, canal, agora))


def decidir(foto: Fotografia, lead_id, canal: str) -> Decisao:
    """Um cliente, com os dados da fotografia da loja (sem ir ao banco)."""
    lead_id = str(lead_id)
    return _decidir(foto.loja, foto.loja_id, lead_id, canal, foto.agora,
                    _FonteFoto(foto, lead_id, canal))


def candidatos(loja_id, agora: datetime) -> list[Decisao]:
    """Todos os leads que já falaram com a loja, com a decisão de cada um.
    Mais antigo primeiro: quem espera há mais tempo vem antes. S6: lê a
    loja de uma vez (fotografia), sem consulta por cliente."""
    foto = fotografia(loja_id, agora)
    return [decidir(foto, lead_id, canal) for lead_id, canal in foto.conversas]


def elegiveis(loja_id, agora: datetime) -> list[Decisao]:
    """Só quem pode receber agora, cortado nas vagas que sobram no mês."""
    loja_id = exigir_loja(loja_id)
    prontos = [d for d in candidatos(loja_id, agora) if d.elegivel]
    return prontos[:vagas_no_mes(loja_id, agora)]

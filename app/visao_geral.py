"""
Visão geral (S9 da Fase 3): o que a tela inicial do nível Geral mostra.
Só LÊ (o banco abre em modo somente leitura); sem Streamlit. A tela
(paginas/operador/visao_geral.py) só mostra o que vem pronto daqui.

1. Saúde do sistema, lida NA HORA em toda atualização (nunca vem do cache):
   - Redis: responde ou não;
   - relógio: sinal gravado pelo runner (app/jobs/batimento.py; decisão 1A);
   - receber mensagens: hora da última mensagem de cliente por canal, tirada
     da tabela mensagens (decisão 2A: nada muda no webhook nem no Telegram);
   - IA: tempo médio e erros na última hora, de uso_custos (decisão 4A).
     As falhas da IA já eram gravadas: o turno grava uma linha tipo 'erro'
     em uso_custos (app/core/turno.py). Por isso o S9 não tem migração.
   Redis fora (7A): o Redis fica vermelho e o resto "desconhecido", nunca
   verde, com a última hora conhecida só como informação.
2. Precisa de atenção: só os alertas que existem agora. Os valores ficam em
   app/alertas_config.py.
3. Tabela de lojas com consultas agrupadas: o número de consultas não cresce
   com o número de lojas (um teste confere). Cache curto por loja (10A): a
   chave do cache é o número da loja, então uma loja nunca recebe o dado de outra.

Regras dos alertas:
- cliente esperando: handoff aguardando vendedor há handoff.gestor_min ou
  mais, contando só minutos DENTRO do expediente, e só no horário de
  atendimento (6A: mesma regra do aviso ao gerente, app/jobs/alertas.py);
- limite do mês (3A): envios (retomada + reativação) sobre
  remarketing.limite_mensal, mês no fuso da loja (mesma conta de
  app/elegibilidade.enviados_no_mes); 80% amarelo, 100% vermelho;
- canal parado (5A): só loja No ar; canal com 10+ mensagens de cliente em 14
  dias; silêncio maior que 5x o intervalo médio, com mínimo de 18 h. Com
  menos de 10 mensagens, a tabela mostra "poucos dados";
- relógio parado: o relógio vermelho vira alerta;
- mensagem recusada: loja Em teste que recusou mensagem de cliente real nas
  últimas 24 h (evento do Registro gravado pelo turno, P7);
- sem venda: loja No ar sem venda há 14 dias (mesma regra do Resumo,
  app/resumo_loja.alertas_da_loja; um teste confere).
"""
from __future__ import annotations

import copy
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from banco import conectar
from app import alertas_config as cfg
from app.apresentacao import nome_do_canal
from app.custos_precos import dinheiro, hoje_brasilia, intervalo_do_mes
from app.estado_loja import ACAO_NO_AR, EM_TESTE, NO_AR
from app.estado_loja import ROTULOS as ROTULOS_ESTADO
from app.jobs import batimento
from app.lojas import PADROES, Loja, _ler_json, _mesclar
from app.registro_leitura import FUSO_GERAL
from app.relogio import (
    agora_utc, do_banco, fuso, hora_local, limites_do_dia_em_utc,
    minutos_no_expediente, no_horario, para_banco,
)

VERDE, AMARELO, VERMELHO = "verde", "amarelo", "vermelho"
DESCONHECIDO, SEM_DADOS = "desconhecido", "sem_dados"
EMOJI = {VERDE: "🟢", AMARELO: "🟡", VERMELHO: "🔴", DESCONHECIDO: "⚪", SEM_DADOS: "⚪"}
NOMES = {"redis": "Redis (memória rápida)", "relogio": "Relógio (avisos e retomadas)",
         "webhook": "Receber mensagens", "ia": "IA (última hora)"}
COMANDO_RELOGIO = "python -m app.jobs.runner"

# P7: o evento que o turno grava quando a loja em teste recusa uma mensagem.
# Cópia de app/core/turno.EVENTO_RECUSADA (importar o turno aqui puxaria a IA);
# um teste confere que os dois são iguais.
EVENTO_RECUSADA = "mensagem_recusada_loja_em_teste"

# Tipos de alerta
CLIENTE_ESPERANDO = "cliente_esperando"
LIMITE = "limite_do_mes"
CANAL_PARADO = "canal_parado"
RELOGIO_PARADO = "relogio_parado"
RECUSADA = "mensagem_recusada"
SEM_VENDA = "sem_venda"

# Situação de cada canal na tabela (5A)
CANAL_OK, CANAL_POUCOS, CANAL_SILENCIO = "ok", "poucos dados", "parado"
DESATIVADA = "Desativada"

# Cache das lojas (10A): (tipo, loja_id) -> (expira_em, valor).
_cache: dict = {}
_relogio_do_cache = time.monotonic      # os testes trocam para adiantar o tempo


# ------------------------------------------------------------ apoio

def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _ler():
    """Conexão que só lê: qualquer escrita por engano dá erro."""
    conexao = conectar()
    conexao.execute("PRAGMA query_only = ON")
    return conexao


def _brasilia(dt: datetime, formato: str = "%d/%m %H:%M") -> str:
    return _utc(dt).astimezone(ZoneInfo(FUSO_GERAL)).strftime(formato)


def _duracao(segundos) -> str:
    s = max(0, int(segundos or 0))
    if s < 60:
        return f"{s} s"
    minutos = s // 60
    if minutos < 60:
        return f"{minutos} min"
    horas = minutos // 60
    if horas < 48:
        resto = minutos % 60
        return f"{horas} h {resto:02d} min" if resto else f"{horas} h"
    return f"{horas // 24} dias"


def _ha_quanto(segundos) -> str:
    return f"há {_duracao(segundos)}"


def _segundos_texto(ms) -> str:
    return f"{(ms or 0) / 1000:.1f} s".replace(".", ",")


def _valores(linhas) -> tuple[str, list]:
    """Monta o VALUES de uma consulta agrupada: uma linha por loja."""
    marcas = ", ".join("(" + ", ".join(["?"] * len(l)) + ")" for l in linhas)
    return marcas, [v for l in linhas for v in l]


def _alerta(nivel: str, tipo: str, loja_id, texto: str) -> dict:
    return {"nivel": nivel, "tipo": tipo, "loja_id": loja_id, "texto": texto}


# ------------------------------------------------------------ 1. saúde (sempre na hora)

def cliente_redis():
    """Cliente do Redis com tempo curto: Redis fora não pode travar a tela."""
    import redis
    from app.redis_cliente import REDIS_URL
    return redis.Redis.from_url(REDIS_URL, decode_responses=True,
                                socket_connect_timeout=1, socket_timeout=1)


def _item(chave: str, nivel: str, texto: str, detalhes=()) -> dict:
    return {"chave": chave, "nome": NOMES[chave], "nivel": nivel, "emoji": EMOJI[nivel],
            "texto": texto, "detalhes": list(detalhes)}


def _redis_responde(cliente) -> bool:
    try:
        return bool(cliente.ping())
    except Exception:
        return False


def _item_relogio(cliente, agora: datetime) -> dict:
    try:
        sinal = batimento.ler(cliente)
    except Exception:
        return _item("relogio", DESCONHECIDO, "Não deu para ler o sinal do relógio no Redis.")
    ligar = f"Para ligar: {COMANDO_RELOGIO}"
    if sinal is None:
        return _item("relogio", VERMELHO, "Sem sinal: o relógio não está ligado.", [ligar])
    quando = sinal["quando"]
    idade = max(0.0, (agora - quando).total_seconds())
    if sinal["estado"] == batimento.PARADO:
        return _item("relogio", VERMELHO, f"Parado desde {_brasilia(quando)}.", [ligar])
    detalhe = f"Último giro: {_brasilia(quando)} ({_ha_quanto(idade)})."
    if idade >= cfg.RELOGIO_VERMELHO_S:
        return _item("relogio", VERMELHO, f"Sem girar {_ha_quanto(idade)}.", [detalhe, ligar])
    if idade >= cfg.RELOGIO_AMARELO_S:
        return _item("relogio", AMARELO, "Atrasado.", [detalhe])
    return _item("relogio", VERDE, "Girando.", [detalhe])


def _ultimas_por_canal(conexao) -> dict:
    linhas = conexao.execute(
        "SELECT canal, MAX(criado_em) AS ultima FROM mensagens "
        "WHERE direcao = 'cliente' AND COALESCE(canal, '') NOT IN ('', 'simulador') "
        "GROUP BY canal").fetchall()
    return {l["canal"]: do_banco(l["ultima"]) for l in linhas if l["ultima"]}


def _ia_ultima_hora(conexao, agora: datetime) -> dict:
    desde = para_banco(agora - timedelta(minutes=cfg.IA_JANELA_MIN))
    l = conexao.execute(
        "SELECT COALESCE(SUM(CASE WHEN tipo = 'turno' THEN 1 ELSE 0 END), 0) AS turnos, "
        "AVG(CASE WHEN tipo = 'turno' THEN latencia_ms END) AS media_ms, "
        "COALESCE(SUM(CASE WHEN tipo = 'erro' THEN 1 ELSE 0 END), 0) AS erros "
        "FROM uso_custos WHERE criado_em >= ? AND criado_em <= ?",
        (desde, para_banco(agora))).fetchone()
    return {"turnos": int(l["turnos"]), "media_ms": l["media_ms"], "erros": int(l["erros"])}


def _item_ia(ia: dict) -> dict:
    media, erros, turnos = ia["media_ms"] or 0, ia["erros"], ia["turnos"]
    if not turnos and not erros:
        return _item("ia", SEM_DADOS, "Nenhuma resposta na última hora.")
    partes = []
    if turnos:
        partes.append(f"{turnos} resposta(s), tempo médio {_segundos_texto(media)}.")
    if erros:
        partes.append(f"{erros} erro(s) da IA.")
    texto = " ".join(partes)
    if erros >= cfg.IA_ERROS_VERMELHO or media >= cfg.IA_LENTA_VERMELHO_MS:
        return _item("ia", VERMELHO, texto)
    if erros >= cfg.IA_ERROS_AMARELO or media >= cfg.IA_LENTA_AMARELO_MS:
        return _item("ia", AMARELO, texto)
    return _item("ia", VERDE, texto)


def _detalhes_canais(ultimas: dict, agora: datetime) -> list[str]:
    return [f"{nome_do_canal(c)}: última mensagem de cliente {_brasilia(q)} "
            f"({_ha_quanto((agora - q).total_seconds())})."
            for c, q in sorted(ultimas.items())]


def _item_webhook(ultimas: dict, agora: datetime, canais_parados: int) -> dict:
    if not ultimas:
        return _item("webhook", SEM_DADOS, "Nenhuma mensagem de cliente recebida ainda.")
    detalhes = _detalhes_canais(ultimas, agora)
    if canais_parados:
        return _item("webhook", AMARELO,
                     f"{canais_parados} canal(is) em silêncio fora do normal (veja abaixo).",
                     detalhes)
    return _item("webhook", VERDE, "Recebendo.", detalhes)


def saude(agora=None, cliente=None, canais_parados: int = 0) -> dict:
    """Lida NA HORA, sempre (nunca vem do cache)."""
    agora = _utc(agora or agora_utc())
    if cliente is None:
        try:
            cliente = cliente_redis()
        except Exception:
            cliente = None
    redis_ok = cliente is not None and _redis_responde(cliente)
    conexao = _ler()
    try:
        ultimas = _ultimas_por_canal(conexao)
        ia = _ia_ultima_hora(conexao, agora)
    finally:
        conexao.close()
    if not redis_ok:
        aviso = "Desconhecido: sem o Redis, não dá para confiar neste item."
        itens = [
            _item("redis", VERMELHO, "Não responde. Ligue o Redis (Docker).",
                  ["O relógio não roda sem o Redis e não volta sozinho: depois de ligar "
                   f"o Redis, ligue o relógio de novo com {COMANDO_RELOGIO}."]),
            _item("relogio", DESCONHECIDO, aviso),
            _item("webhook", DESCONHECIDO, aviso,
                  ["Só para informação: " + d for d in _detalhes_canais(ultimas, agora)]),
            _item("ia", DESCONHECIDO, aviso, ["Só para informação: " + _item_ia(ia)["texto"]]),
        ]
    else:
        itens = [_item("redis", VERDE, "Respondendo."), _item_relogio(cliente, agora),
                 _item_webhook(ultimas, agora, canais_parados), _item_ia(ia)]
    return {"itens": itens, "redis_ok": redis_ok,
            "relogio": next(i for i in itens if i["chave"] == "relogio")}


# ------------------------------------------------------------ 2 e 3. lojas (com cache)

def limpar_cache() -> None:
    _cache.clear()


def _lojas(conexao) -> list[dict]:
    """Todas as lojas, com a configuração e o estado, numa consulta."""
    linhas = conexao.execute(
        "SELECT l.id, l.nome, l.segmento, l.config, l.versao_config, l.ativo, "
        "e.estado, e.no_ar_em, EXISTS (SELECT 1 FROM registro_acoes r "
        "WHERE r.loja_id = l.id AND r.acao = ?) AS pelo_botao "
        "FROM lojas l LEFT JOIN estado_lojas e ON e.loja_id = l.id ORDER BY l.id",
        (ACAO_NO_AR,)).fetchall()
    saida = []
    for l in linhas:
        loja = Loja(id=l["id"], nome=l["nome"], segmento=l["segmento"],
                    config=_mesclar(PADROES, _ler_json(l["config"], l["id"])),
                    versao_config=l["versao_config"], ativo=bool(l["ativo"]))
        estado = l["estado"] or EM_TESTE
        # P7c: mesma regra de estado_loja.inicio_da_contagem.
        desde = (str(l["no_ar_em"])[:19]
                 if estado == NO_AR and l["no_ar_em"] and l["pelo_botao"] else None)
        saida.append({"loja": loja, "estado": estado, "no_ar_em": l["no_ar_em"], "desde": desde})
    return saida


def _canal(l, agora: datetime) -> dict:
    ultima = do_banco(l["ultima"])
    silencio = max(0.0, (agora - ultima).total_seconds())
    n = int(l["n"] or 0)
    item = {"canal": l["canal"], "ultima": ultima, "silencio_s": silencio, "n": n,
            "media_s": None, "situacao": CANAL_POUCOS}
    if n >= cfg.CANAL_MIN_MENSAGENS and l["primeira"]:
        media = (ultima - do_banco(l["primeira"])).total_seconds() / (n - 1)
        item["media_s"] = media
        limite = max(cfg.CANAL_VEZES_A_MEDIA * media, cfg.CANAL_MINIMO_H * 3600)
        item["situacao"] = CANAL_SILENCIO if silencio > limite else CANAL_OK
    return item


def _calcular(conexao, lojas: list[dict], agora: datetime) -> dict:
    """Os números de várias lojas com consultas agrupadas (nenhuma por loja)."""
    ids = [i["loja"].id for i in lojas]
    marcas = ",".join("?" * len(ids))
    por_loja = {i["loja"].id: i["loja"] for i in lojas}
    hoje, inicio_mes = [], []
    for i in lojas:
        loja = i["loja"]
        local = hora_local(loja, agora)
        de, ate = limites_do_dia_em_utc(loja.get("fuso"), local.date())
        hoje.append((loja.id, de, ate))
        inicio_mes.append((loja.id, para_banco(
            datetime(local.year, local.month, 1, tzinfo=fuso(loja)))))
    saida = {i: {"conversas_hoje": 0, "esperando": 0, "esperando_vermelho": 0, "envios": 0,
                 "gasto_ia": 0.0, "canais": [], "recusadas": 0, "ultima_venda": None}
             for i in ids}

    valores, params = _valores(hoje)
    for l in conexao.execute(
            f"WITH j(loja_id, de, ate) AS (VALUES {valores}) "
            "SELECT j.loja_id, COUNT(DISTINCT m.lead_id) AS n FROM j "
            "LEFT JOIN mensagens m ON m.loja_id = j.loja_id AND m.direcao = 'cliente' "
            "AND m.criado_em >= j.de AND m.criado_em < j.ate GROUP BY j.loja_id", params):
        saida[l["loja_id"]]["conversas_hoje"] = int(l["n"])

    # 6A: só minutos dentro do expediente, e só no horário de atendimento.
    for l in conexao.execute(
            "SELECT loja_id, criado_em FROM handoffs WHERE estado = 'aguardando_humano' "
            f"AND loja_id IN ({marcas})", ids):
        d, loja = saida[l["loja_id"]], por_loja[l["loja_id"]]
        d["esperando"] += 1
        if l["criado_em"] and no_horario(loja, agora):
            minutos = minutos_no_expediente(loja, do_banco(l["criado_em"]), agora)
            if minutos >= int(loja.get("handoff.gestor_min", 10)):
                d["esperando_vermelho"] += 1

    # Mesma conta de app/elegibilidade.enviados_no_mes (retomada + reativação).
    valores, params = _valores(inicio_mes)
    for l in conexao.execute(
            f"WITH j(loja_id, desde) AS (VALUES {valores}) SELECT j.loja_id, "
            "(SELECT COUNT(*) FROM remarketing_envios r WHERE r.loja_id = j.loja_id "
            " AND r.estado = 'enviado' AND COALESCE(r.enviado_em, r.criado_em) >= j.desde) "
            "+ (SELECT COUNT(*) FROM reativacao a WHERE a.loja_id = j.loja_id "
            " AND a.estado = 'enviado' AND a.enviado_em >= j.desde) AS n FROM j", params):
        saida[l["loja_id"]]["envios"] = int(l["n"])

    # 8A: gasto de IA do mês de Brasília, como na tela Custos e preços.
    hoje_br = hoje_brasilia(agora)
    de, ate = intervalo_do_mes(hoje_br.year, hoje_br.month)
    for l in conexao.execute(
            "SELECT loja_id, COALESCE(SUM(custo_llm), 0) AS ia FROM uso_custos "
            f"WHERE loja_id IN ({marcas}) AND criado_em >= ? AND criado_em < ? "
            "GROUP BY loja_id", (*ids, de, ate)):
        saida[l["loja_id"]]["gasto_ia"] = float(l["ia"])

    janela = para_banco(agora - timedelta(days=cfg.CANAL_JANELA_DIAS))
    for l in conexao.execute(
            "SELECT loja_id, canal, MAX(criado_em) AS ultima, "
            "SUM(CASE WHEN criado_em >= ? THEN 1 ELSE 0 END) AS n, "
            "MIN(CASE WHEN criado_em >= ? THEN criado_em END) AS primeira "
            f"FROM mensagens WHERE direcao = 'cliente' AND loja_id IN ({marcas}) "
            "AND COALESCE(canal, '') NOT IN ('', 'simulador') "
            "GROUP BY loja_id, canal ORDER BY loja_id, canal", (janela, janela, *ids)):
        saida[l["loja_id"]]["canais"].append(_canal(l, agora))

    desde_recusa = para_banco(agora - timedelta(hours=cfg.RECUSA_JANELA_H))
    for l in conexao.execute(
            "SELECT loja_id, COUNT(*) AS n FROM registro_acoes WHERE acao = ? "
            f"AND quando >= ? AND loja_id IN ({marcas}) GROUP BY loja_id",
            (EVENTO_RECUSADA, desde_recusa, *ids)):
        saida[l["loja_id"]]["recusadas"] = int(l["n"])

    # Mesma regra de app/resumo_loja.alertas_da_loja (P7c: venda do teste não conta).
    valores, params = _valores([(i["loja"].id, i["desde"]) for i in lojas])
    for l in conexao.execute(
            f"WITH j(loja_id, desde) AS (VALUES {valores}) "
            "SELECT j.loja_id, MAX(v.data_venda) AS ultima FROM j LEFT JOIN vendas v "
            "ON v.loja_id = j.loja_id AND (j.desde IS NULL OR v.criado_em >= j.desde) "
            "GROUP BY j.loja_id", params):
        saida[l["loja_id"]]["ultima_venda"] = l["ultima"]
    return saida


def _dias_sem_venda(i: dict, ultima, agora: datetime):
    loja = i["loja"]
    if i["estado"] != NO_AR:
        return None
    if ultima:
        referencia = date.fromisoformat(str(ultima)[:10])
    elif i["no_ar_em"]:
        referencia = hora_local(loja, do_banco(str(i["no_ar_em"])[:19])).date()
    else:
        return None
    return (hora_local(loja, agora).date() - referencia).days


def dados_das_lojas(agora=None) -> list[dict]:
    """Uma linha por loja. Cache curto POR LOJA (10A): a chave é (loja,
    versão da configuração, estado); uma loja nunca recebe o dado de outra."""
    agora = _utc(agora or agora_utc())
    agora_cache = _relogio_do_cache()
    conexao = _ler()
    try:
        lojas = _lojas(conexao)
        chaves = {i["loja"].id: (i["loja"].id, i["loja"].versao_config, i["estado"])
                  for i in lojas}
        faltam = [i for i in lojas if chaves[i["loja"].id] not in _cache
                  or _cache[chaves[i["loja"].id]][0] <= agora_cache]
        calculados = _calcular(conexao, faltam, agora) if faltam else {}
    finally:
        conexao.close()
    saida = []
    for i in lojas:
        loja, chave = i["loja"], chaves[i["loja"].id]
        if loja.id in calculados:
            c = calculados[loja.id]
            d = {"loja_id": loja.id, "nome": loja.nome, "ativo": loja.ativo,
                 "estado": i["estado"],
                 "estado_rotulo": (ROTULOS_ESTADO.get(i["estado"], i["estado"])
                                   if loja.ativo else DESATIVADA),
                 "limite": loja.get("remarketing.limite_mensal"),
                 "gestor_min": int(loja.get("handoff.gestor_min", 10)),
                 **{k: v for k, v in c.items() if k != "ultima_venda"},
                 "dias_sem_venda": _dias_sem_venda(i, c["ultima_venda"], agora)}
            _cache[chave] = (agora_cache + cfg.CACHE_S, d)
        saida.append(copy.deepcopy(_cache[chave][1]))
    return saida


def alertas(lojas: list[dict], saude_atual: dict | None = None) -> list[dict]:
    """Só o que existe agora. Vermelho primeiro."""
    lista = []
    if saude_atual and saude_atual["relogio"]["nivel"] == VERMELHO:
        lista.append(_alerta(VERMELHO, RELOGIO_PARADO, None,
                             "Relógio parado: avisos de handoff, alerta de gasto e retomadas "
                             f"não estão rodando. Ligue com: {COMANDO_RELOGIO}"))
    for d in lojas:
        if not d["ativo"]:
            continue
        nome, loja_id = d["nome"], d["loja_id"]
        if d["esperando_vermelho"]:
            lista.append(_alerta(VERMELHO, CLIENTE_ESPERANDO, loja_id,
                                 f"{nome}: {d['esperando_vermelho']} cliente(s) esperando vendedor "
                                 f"há {d['gestor_min']} min ou mais (contando só o expediente)."))
        limite = d["limite"]
        if limite and limite > 0:
            uso = d["envios"] / limite
            if uso >= cfg.LIMITE_VERMELHO:
                lista.append(_alerta(VERMELHO, LIMITE, loja_id,
                                     f"{nome}: limite de envios do mês atingido "
                                     f"({d['envios']} de {limite})."))
            elif uso >= cfg.LIMITE_AMARELO:
                lista.append(_alerta(AMARELO, LIMITE, loja_id,
                                     f"{nome}: {round(uso * 100)}% do limite de envios do mês "
                                     f"({d['envios']} de {limite})."))
        if d["estado"] == NO_AR:
            for c in d["canais"]:
                if c["situacao"] == CANAL_SILENCIO:
                    lista.append(_alerta(AMARELO, CANAL_PARADO, loja_id,
                                         f"{nome}: {nome_do_canal(c['canal'])} sem mensagens de "
                                         f"cliente {_ha_quanto(c['silencio_s'])} (o normal desta "
                                         f"loja é uma a cada {_duracao(c['media_s'])})."))
            if d["dias_sem_venda"] is not None and d["dias_sem_venda"] >= cfg.DIAS_SEM_VENDA:
                lista.append(_alerta(AMARELO, SEM_VENDA, loja_id,
                                     f"{nome}: nenhuma venda registrada há "
                                     f"{d['dias_sem_venda']} dias."))
        elif d["recusadas"]:
            lista.append(_alerta(AMARELO, RECUSADA, loja_id,
                                 f"{nome} (em teste): {d['recusadas']} mensagem(ns) de cliente real "
                                 f"recusada(s) nas últimas {cfg.RECUSA_JANELA_H} h. Confira se falta "
                                 "cadastrar um número de teste ou se a loja já devia estar no ar."))
    ordem = {VERMELHO: 0, AMARELO: 1}
    return sorted(lista, key=lambda a: ordem.get(a["nivel"], 2))


def _texto_envios(d: dict) -> str:
    if d["limite"] is None:
        return f"{d['envios']} / sem limite"
    if not d["limite"]:
        return f"{d['envios']} / 0"
    return f"{d['envios']} / {d['limite']} ({round(d['envios'] / d['limite'] * 100)}%)"


def linhas_da_tabela(lojas: list[dict]) -> list[dict]:
    return [{"Loja": d["nome"], "Estado": d["estado_rotulo"],
             "Conversas hoje": d["conversas_hoje"], "Esperando vendedor": d["esperando"],
             "Envios do mês / limite": _texto_envios(d),
             "Gasto de IA no mês": dinheiro(d["gasto_ia"], 2),
             "Canais": " · ".join(f"{nome_do_canal(c['canal'])}: {c['situacao']}"
                                  for c in d["canais"]) or "—"}
            for d in lojas]


def visao_geral(agora=None, cliente=None) -> dict:
    """Tudo o que a tela mostra. Lojas com cache; saúde sempre na hora."""
    agora = _utc(agora or agora_utc())
    lojas = dados_das_lojas(agora)
    parados = sum(1 for a in alertas(lojas) if a["tipo"] == CANAL_PARADO)
    s = saude(agora, cliente, parados)
    return {"saude": s, "alertas": alertas(lojas, s), "lojas": lojas,
            "linhas": linhas_da_tabela(lojas)}

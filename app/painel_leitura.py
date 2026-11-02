"""
Leitura para os painéis (P4 do Plano Mestre): etapas dos leads, resultado do
período e o cartão "O que o Léo já sabe".

Só consulta: a conexão abre em modo somente leitura (PRAGMA query_only),
então qualquer escrita por engano dá erro. loja_id sempre obrigatório.
Horários já convertidos para o fuso da loja (app/apresentacao.py).

Etapa do lead (calculada, ninguém edita). A primeira regra que valer decide:
  1. Venda registrada  existe venda (tabela vendas)
  2. Não seguiu        o Léo percebeu "sem interesse" ou "não quer contato",
                       ou as retomadas acabaram sem resposta
  3. Visita marcada    agendamento 'agendado' marcado há até 7 dias
  4. Com vendedor      handoff aberto (aguardando ou assumido)
  5. Pediu tempo       o Léo percebeu "agora não"
  6. Novo              primeira mensagem do cliente nas últimas 24 h
  7. Em conversa       o cliente escreveu nos últimos 7 dias
  8. Não seguiu        nada acima e o cliente sumiu há mais de 7 dias
Decisões do Samuel (A7, 02/11/2026): a visita conta 7 dias desde que foi
marcada (a data combinada é texto livre, ex.: "sábado 10h"); quem some há
mais de 7 dias vai para "Não seguiu"; uma frase de "próximo passo" por etapa.
"Novo" fica antes de "Em conversa" (senão nunca apareceria).

P7c: o Resultado de uma loja que entrou no ar pelo botão conta só a partir
desse momento (app/estado_loja.inicio_da_contagem). Nada é apagado.
"""
from __future__ import annotations

import unicodedata
from datetime import date, datetime, timedelta, timezone

from banco import conectar
from app.apresentacao import (
    CANAIS_COM_TELEFONE, data_para_tela, horario_iso_local, horario_para_tela,
    nome_do_canal, nomes_dos_clientes,
)
from app.chaves import exigir_loja
from app.estado_loja import esta_no_ar, inicio_da_contagem
from app.interesse import ROTULOS as ROTULOS_SITUACAO
from app.lojas import carregar_loja, modulo_ativo
from app.relogio import (
    agora_utc, do_banco, hora_local, limites_do_dia_em_utc, no_horario, para_banco,
)
from app.telefone import formatar_telefone_br

JANELA_NOVO = timedelta(hours=24)
JANELA_CONVERSA = timedelta(days=7)
JANELA_VISITA = timedelta(days=7)
MAX_DIAS_PERIODO = 400
_LOTE = 400

# Ordem em que as etapas aparecem na tela (da esquerda para a direita).
ORDEM_DAS_ETAPAS = ("novo", "em_conversa", "pediu_tempo", "com_vendedor",
                    "visita_marcada", "venda_registrada", "nao_seguiu")
ROTULOS_ETAPA = {
    "novo": "Novo",
    "em_conversa": "Em conversa",
    "pediu_tempo": "Pediu tempo",
    "com_vendedor": "Com vendedor",
    "visita_marcada": "Visita marcada",
    "venda_registrada": "Venda registrada",
    "nao_seguiu": "Não seguiu",
}
TIPOS_DE_AGENDAMENTO = {"visita": "Visita", "test-drive": "Test-drive", "ligacao": "Ligação"}
ROTULOS_FUNIL = {
    "conversas": "Conversas",
    "qualificados": "Qualificados",
    "com_vendedor": "Passados ao vendedor",
    "visitas": "Visitas marcadas",
    "vendas": "Vendas registradas",
}


# ------------------------------------------------------------ apoio

def _ler():
    """Conexão que só lê: qualquer INSERT/UPDATE/DELETE dá erro."""
    conexao = conectar()
    conexao.execute("PRAGMA query_only = ON")
    return conexao


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _dt(valor) -> datetime | None:
    if not valor:
        return None
    try:
        return do_banco(str(valor).strip().replace("T", " "))
    except (TypeError, ValueError):
        return None


def _dia(valor) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor).strip()[:10])


def _normalizar(texto) -> str:
    sem = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in sem if unicodedata.category(c) != "Mn").lower()


def _partes(lista):
    for i in range(0, len(lista), _LOTE):
        yield lista[i:i + _LOTE]


def _por_lead(conexao, sql, loja_id, ids):
    """Roda o SQL (que tem {marcas}) em lotes de leads; devolve as linhas."""
    linhas = []
    for parte in _partes(list(ids)):
        marcas = ",".join("?" * len(parte))
        linhas += conexao.execute(sql.format(marcas=marcas), (loja_id, *parte)).fetchall()
    return linhas


def _texto_carro(marca, modelo, ano) -> str:
    return " ".join(str(p) for p in (marca, modelo, ano) if p not in (None, ""))


def _segundos(inicio, fim) -> int | None:
    a, b = _dt(inicio), _dt(fim)
    if a is None or b is None or b < a:
        return None
    return int((b - a).total_seconds())


def _media(valores) -> int | None:
    return round(sum(valores) / len(valores)) if valores else None


def _duracao(segundos) -> str:
    if segundos is None:
        return "—"
    if segundos < 60:
        return f"{segundos} s"
    minutos = round(segundos / 60)
    if minutos < 60:
        return f"{minutos} min"
    horas, resto = divmod(minutos, 60)
    return f"{horas} h {resto:02d} min"


# ------------------------------------------------------------ fatos de cada lead

def _vazio(lead_id):
    return {"lead_id": lead_id, "canal": "", "primeira_cliente": None, "ultima_cliente": None,
            "ultima_mensagem": None, "venda": False, "carro_venda": "", "situacao": None,
            "retomar_em": None, "agendamento": None, "handoff": None, "toques": 0,
            "ultimo_toque": None, "lead": {}, "carro_interesse": ""}


def _fatos(conexao, loja_id, ids) -> dict:
    """Tudo o que as regras precisam saber de cada lead, com poucas consultas."""
    fatos = {l: _vazio(l) for l in ids}
    if not ids:
        return fatos

    def cada(sql):
        for linha in _por_lead(conexao, sql, loja_id, ids):
            f = fatos.get(linha["lead_id"])
            if f is not None:
                yield f, linha

    for f, l in cada(
            "SELECT lead_id, "
            "MIN(CASE WHEN direcao = 'cliente' THEN criado_em END) AS primeira_cliente, "
            "MAX(CASE WHEN direcao = 'cliente' THEN criado_em END) AS ultima_cliente, "
            "MAX(criado_em) AS ultima_mensagem "
            "FROM mensagens WHERE loja_id = ? AND lead_id IN ({marcas}) GROUP BY lead_id"):
        f["primeira_cliente"] = l["primeira_cliente"]
        f["ultima_cliente"] = l["ultima_cliente"]
        f["ultima_mensagem"] = l["ultima_mensagem"]

    for f, l in cada(
            "SELECT m.lead_id, m.canal FROM mensagens m "
            "WHERE m.loja_id = ? AND m.lead_id IN ({marcas}) "
            "AND m.id = (SELECT MAX(y.id) FROM mensagens y "
            "WHERE y.loja_id = m.loja_id AND y.lead_id = m.lead_id)"):
        f["canal"] = l["canal"] or ""

    for f, l in cada(
            "SELECT v.lead_id, e.marca, e.modelo, e.ano FROM vendas v "
            "LEFT JOIN estoque e ON e.id = v.veiculo_id AND e.loja_id = v.loja_id "
            "WHERE v.loja_id = ? AND v.lead_id IN ({marcas}) ORDER BY v.data_venda, v.id"):
        f["venda"] = True
        f["carro_venda"] = _texto_carro(l["marca"], l["modelo"], l["ano"])

    for f, l in cada(
            "SELECT lead_id, situacao, retomar_em FROM situacao_lead "
            "WHERE loja_id = ? AND lead_id IN ({marcas})"):
        f["situacao"] = l["situacao"]
        f["retomar_em"] = l["retomar_em"]

    for f, l in cada(
            "SELECT lead_id, tipo, data_hora, criado_em FROM agendamentos "
            "WHERE loja_id = ? AND status = 'agendado' AND lead_id IN ({marcas}) "
            "ORDER BY criado_em, id"):
        f["agendamento"] = dict(l)

    for f, l in cada(
            "SELECT lead_id, motivo, estado, vendedor FROM handoffs "
            "WHERE loja_id = ? AND estado != 'encerrado' AND lead_id IN ({marcas}) ORDER BY id"):
        f["handoff"] = dict(l)

    for f, l in cada(
            "SELECT lead_id, COUNT(*) AS toques, MAX(COALESCE(enviado_em, criado_em)) AS ultimo "
            "FROM remarketing_envios WHERE loja_id = ? AND estado = 'enviado' "
            "AND lead_id IN ({marcas}) GROUP BY lead_id"):
        f["toques"] = l["toques"]
        f["ultimo_toque"] = l["ultimo"]

    for f, l in cada(
            "SELECT lead_id, nome, interesse, forma_pagamento, tem_troca, prazo FROM leads "
            "WHERE loja_id = ? AND lead_id IN ({marcas})"):
        f["lead"] = dict(l)

    for f, l in cada(
            "SELECT i.lead_id, e.marca, e.modelo, e.ano FROM interesse_veiculo i "
            "JOIN estoque e ON e.id = i.veiculo_id AND e.loja_id = i.loja_id "
            "WHERE i.loja_id = ? AND i.lead_id IN ({marcas})"):
        f["carro_interesse"] = _texto_carro(l["marca"], l["modelo"], l["ano"])

    return fatos


def _carro_do_lead(f) -> str:
    return (f["carro_venda"] or f["carro_interesse"]
            or (f["lead"].get("interesse") or "").strip())


def _etapa(f, loja, agora) -> tuple[str, str]:
    """(etapa, próximo passo do Léo). A primeira regra que valer decide."""
    if f["venda"]:
        passo = "Pós-venda agendado" if modulo_ativo(loja, "pos_venda") else "Venda concluída"
        return "venda_registrada", passo

    ultima = _dt(f["ultima_cliente"])
    ultimo_toque = _dt(f["ultimo_toque"])
    max_toques = int(loja.get("remarketing.max_toques") or 3)
    esgotou = (f["toques"] >= max_toques
               and (ultima is None or ultimo_toque is None or ultima <= ultimo_toque))
    if f["situacao"] in ("sem_interesse", "nao_contatar") or esgotou:
        return "nao_seguiu", "Não procura mais"

    agendamento = f["agendamento"]
    marcado = _dt(agendamento["criado_em"]) if agendamento else None
    if marcado and agora - marcado <= JANELA_VISITA:
        return "visita_marcada", "Aguardando a visita"

    if f["handoff"]:
        return "com_vendedor", "Em silêncio, com o vendedor"

    if f["situacao"] == "pediu_tempo":
        if f["retomar_em"]:
            return "pediu_tempo", f"Volta a procurar em {data_para_tela(f['retomar_em'])}"
        return "pediu_tempo", "Aguardando o cliente"

    primeira = _dt(f["primeira_cliente"])
    if primeira and agora - primeira <= JANELA_NOVO:
        return "novo", "Atendendo"
    if ultima and agora - ultima <= JANELA_CONVERSA:
        return "em_conversa", "Atendendo"
    return "nao_seguiu", "Não procura mais"


# ------------------------------------------------------------ 1. etapas dos leads

def etapas_dos_leads(loja_id, desde_dias, busca=None, *, agora: datetime | None = None) -> list[dict]:
    """Uma linha por lead com conversa (ou venda) nos últimos 'desde_dias' dias:
    nome, carro, origem, último contato, etapa e próximo passo do Léo.
    Mais recente primeiro. 'busca' procura no nome e no carro, sem acento."""
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    agora = _utc(agora or agora_utc())
    dias = int(desde_dias)
    if dias < 1:
        raise ValueError("desde_dias precisa ser 1 ou mais.")
    corte = para_banco(agora - timedelta(days=dias))

    conexao = _ler()
    try:
        ids = [l["lead_id"] for l in conexao.execute(
            "SELECT lead_id FROM mensagens WHERE loja_id = ? "
            "GROUP BY lead_id HAVING MAX(criado_em) >= ? "
            "UNION SELECT lead_id FROM vendas WHERE loja_id = ? AND data_venda >= ?",
            (loja_id, corte, loja_id, corte[:10]))]
        fatos = _fatos(conexao, loja_id, ids)
    finally:
        conexao.close()

    nomes = nomes_dos_clientes(loja_id, ids)
    termo = _normalizar(busca).strip() if busca else ""
    saida = []
    for lead_id in ids:
        f = fatos[lead_id]
        nome = nomes.get(str(lead_id), "Cliente sem nome")
        carro = _carro_do_lead(f)
        if termo and termo not in _normalizar(f"{nome} {carro} {lead_id}"):
            continue
        etapa, passo = _etapa(f, loja, agora)
        saida.append({
            "lead_id": lead_id,
            "nome": nome,
            "carro": carro,
            "origem": nome_do_canal(f["canal"]),
            "ultimo_contato": horario_para_tela(loja, f["ultima_mensagem"], agora=agora),
            "ultimo_contato_iso": horario_iso_local(loja, f["ultima_mensagem"]),
            "etapa": etapa,
            "etapa_rotulo": ROTULOS_ETAPA[etapa],
            "proximo_passo": passo,
        })
    saida.sort(key=lambda l: fatos[l["lead_id"]]["ultima_mensagem"] or "", reverse=True)
    return saida


# ------------------------------------------------------------ 2. resultado do período

def resultado_do_periodo(loja_id, inicio, fim) -> dict:
    """Números da tela Resultado entre dois dias (inclusive), no fuso da loja.
    Venda conta pela data da venda, não pela data do registro.

    P7c: loja que entrou no ar pelo botão conta só a partir de no_ar_em (o
    período de teste fica de fora; nada é apagado). Venda: registrada depois
    de entrar no ar E com data da venda desse dia em diante. Loja ainda em
    teste mostra os números com dados_de_teste=True. Loja que já existia
    antes do P7 conta tudo, como antes."""
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    inicio, fim = _dia(inicio), _dia(fim)
    if fim < inicio:
        raise ValueError("O fim do período precisa ser depois do início.")
    total_dias = (fim - inicio).days + 1
    if total_dias > MAX_DIAS_PERIODO:
        raise ValueError(f"Período muito longo (máximo {MAX_DIAS_PERIODO} dias).")
    de, _ = limites_do_dia_em_utc(loja.get("fuso"), inicio)
    _, ate = limites_do_dia_em_utc(loja.get("fuso"), fim)

    contando_desde = inicio_da_contagem(loja_id)
    inicio_vendas = inicio
    if contando_desde:
        de = max(de, contando_desde)
        inicio_vendas = max(inicio, hora_local(loja, _dt(contando_desde)).date())

    conexao = _ler()
    try:
        do_cliente = conexao.execute(
            "SELECT lead_id, criado_em FROM mensagens WHERE loja_id = ? AND direcao = 'cliente' "
            "AND criado_em >= ? AND criado_em < ? ORDER BY criado_em, id",
            (loja_id, de, ate)).fetchall()
        primeiras = conexao.execute(
            "SELECT p.lead_id, p.em AS pergunta, "
            "(SELECT MIN(r.criado_em) FROM mensagens r "
            " WHERE r.loja_id = p.loja_id AND r.lead_id = p.lead_id "
            " AND r.direcao IN ('leo', 'vendedor') AND r.id > p.id) AS resposta "
            "FROM (SELECT loja_id, lead_id, MIN(id) AS id, MIN(criado_em) AS em "
            "      FROM mensagens WHERE loja_id = ? AND direcao = 'cliente' "
            "      GROUP BY loja_id, lead_id) p "
            "WHERE p.em >= ? AND p.em < ?",
            (loja_id, de, ate)).fetchall()
        chamados = conexao.execute(
            "SELECT lead_id, criado_em, assumido_em FROM handoffs WHERE loja_id = ? "
            "AND origem = 'leo' AND criado_em >= ? AND criado_em < ?",
            (loja_id, de, ate)).fetchall()
        visitas = conexao.execute(
            "SELECT lead_id FROM agendamentos WHERE loja_id = ? AND criado_em >= ? AND criado_em < ?",
            (loja_id, de, ate)).fetchall()
        vendas = conexao.execute(
            "SELECT lead_id FROM vendas WHERE loja_id = ? AND data_venda >= ? AND data_venda <= ? "
            "AND (? IS NULL OR criado_em >= ?)",
            (loja_id, inicio_vendas.isoformat(), fim.isoformat(),
             contando_desde, contando_desde)).fetchall()
        conversas = list(dict.fromkeys(l["lead_id"] for l in do_cliente))
        qualificados = {l["lead_id"] for l in _por_lead(
            conexao,
            "SELECT lead_id FROM leads WHERE loja_id = ? AND lead_id IN ({marcas}) "
            "AND TRIM(COALESCE(interesse, '')) != '' "
            "AND (TRIM(COALESCE(forma_pagamento, '')) != '' OR TRIM(COALESCE(prazo, '')) != '')",
            loja_id, conversas)}
    finally:
        conexao.close()

    por_dia = {inicio + timedelta(days=i): {"no_horario": 0, "fora_do_horario": 0}
               for i in range(total_dias)}
    primeira_no_periodo, vistos = {}, set()
    for l in do_cliente:
        quando = _dt(l["criado_em"])
        if quando is None:
            continue
        dentro = no_horario(loja, quando)
        primeira_no_periodo.setdefault(l["lead_id"], dentro)
        dia = hora_local(loja, quando).date()
        if dia in por_dia and (l["lead_id"], dia) not in vistos:
            vistos.add((l["lead_id"], dia))
            por_dia[dia]["no_horario" if dentro else "fora_do_horario"] += 1

    respostas = [s for s in (_segundos(l["pergunta"], l["resposta"]) for l in primeiras) if s is not None]
    assumidos = [s for s in (_segundos(l["criado_em"], l["assumido_em"]) for l in chamados) if s is not None]
    media_resposta, media_assumir = _media(respostas), _media(assumidos)

    funil = {
        "conversas": len(conversas),
        "qualificados": len(qualificados),
        "com_vendedor": len({l["lead_id"] for l in chamados}),
        "visitas": len({l["lead_id"] for l in visitas}),
        "vendas": len(vendas),
    }
    return {
        "inicio": inicio.isoformat(),
        "fim": fim.isoformat(),
        "conversas_atendidas": len(conversas),
        "fora_do_horario": sum(1 for dentro in primeira_no_periodo.values() if not dentro),
        "primeira_resposta_s": media_resposta,
        "primeira_resposta_texto": _duracao(media_resposta),
        "ate_vendedor_assumir_s": media_assumir,
        "ate_vendedor_assumir_texto": _duracao(media_assumir),
        "passados_ao_vendedor": funil["com_vendedor"],
        "visitas_marcadas": funil["visitas"],
        "vendas_registradas": funil["vendas"],
        "funil": [{"etapa": k, "rotulo": ROTULOS_FUNIL[k], "total": v} for k, v in funil.items()],
        "por_dia": [{"dia": d.isoformat(), "dia_texto": d.strftime("%d/%m"), **v}
                    for d, v in por_dia.items()],
        # P7c: a tela avisa quando os números são do período de teste e
        # mostra (no fuso da loja) desde quando está contando.
        "dados_de_teste": not esta_no_ar(loja_id),
        "contando_desde": contando_desde,
    }


# ------------------------------------------------------------ 3. cartão do lead

def cartao_do_lead(loja_id, lead_id, *, agora: datetime | None = None) -> dict:
    """'O que o Léo já sabe' sobre um cliente desta loja."""
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    agora = _utc(agora or agora_utc())
    lead_id = str(lead_id or "").strip()
    if not lead_id:
        raise ValueError("Cartão sem cliente.")

    conexao = _ler()
    try:
        f = _fatos(conexao, loja_id, [lead_id])[lead_id]
        troca = conexao.execute(
            "SELECT modelo, ano, km FROM trocas WHERE loja_id = ? AND lead_id = ? "
            "ORDER BY id DESC LIMIT 1", (loja_id, lead_id)).fetchone()
    finally:
        conexao.close()

    lead = f["lead"]
    etapa, passo = _etapa(f, loja, agora)
    telefone = formatar_telefone_br(lead_id) if f["canal"] in CANAIS_COM_TELEFONE else ""

    etiqueta = ROTULOS_SITUACAO.get(f["situacao"] or "", "")
    if f["situacao"] == "pediu_tempo" and f["retomar_em"]:
        etiqueta += f" (até {data_para_tela(f['retomar_em'])})"

    visita = ""
    if f["agendamento"]:
        ag = f["agendamento"]
        visita = " · ".join(p for p in (TIPOS_DE_AGENDAMENTO.get(ag["tipo"], ag["tipo"] or ""),
                                        ag["data_hora"] or "") if p)

    if troca and (troca["modelo"] or "").strip():
        modelo_troca = troca["modelo"].strip()
        ano_troca = troca["ano"] if str(troca["ano"] or "") not in modelo_troca else None
        texto_troca = _texto_carro(None, modelo_troca, ano_troca)
        if troca["km"]:
            texto_troca += f" · {int(troca['km']):,} km".replace(",", ".")
    else:
        texto_troca = (lead.get("tem_troca") or "").strip()

    return {
        "lead_id": lead_id,
        "nome": nomes_dos_clientes(loja_id, [lead_id]).get(lead_id, "Cliente sem nome"),
        "telefone": telefone,
        "origem": nome_do_canal(f["canal"]),
        "carro": _carro_do_lead(f),
        "pagamento": (lead.get("forma_pagamento") or "").strip(),
        "troca": texto_troca,
        "prazo": (lead.get("prazo") or "").strip(),
        "visita": visita,
        "motivo_do_chamado": ((f["handoff"] or {}).get("motivo") or "").strip(),
        "etiqueta": etiqueta,
        "etapa": etapa,
        "etapa_rotulo": ROTULOS_ETAPA[etapa],
        "proximo_passo": passo,
        "ultimo_contato": horario_para_tela(loja, f["ultima_mensagem"], agora=agora),
    }

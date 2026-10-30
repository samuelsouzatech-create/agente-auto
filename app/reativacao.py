"""
Reativação de contatos antigos da base (Etapa 2, Bloco 6C).

A loja já tem anos de contatos (Bloco 6A). Aqui o operador monta uma FILA
de quem está parado há meses; o job (app/jobs/reativacao.py) manda UMA
mensagem para cada um, sempre por modelo aprovado pela Meta, no WhatsApp.

Fica de fora (na montagem E de novo logo antes de enviar):
  sem autorização, pediu para não ser procurado, conversa com vendedor,
  conversou ou comprou dentro do prazo escolhido, já está no pós-venda,
  já foi reativado nos últimos 6 meses.
Conta no MESMO limite mensal do remarketing e exige o módulo remarketing ligado.
Não há segundo toque: se o cliente responder, segue a conversa normal.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from banco import conectar
from app.chaves import exigir_loja
from app.lojas import carregar_loja, modulo_ativo
from app.relogio import agora_utc, dia_local, do_banco, para_banco
from app.telefone import normalizar_telefone_br

OPCOES_MESES = (3, 6, 12, 24)
MESES_PADRAO = 6
DIAS_POR_MES = 30.4375
INTERVALO_ENTRE_REATIVACOES = timedelta(days=180)
MAX_POR_LOTE = 500
JANELA_CONTEXTO = timedelta(hours=72)
MODELO_CLIENTE = "reativacao_cliente"
MODELO_CONTATO = "reativacao_contato"
ESTADOS = ("na_fila", "simulado", "enviado", "falhou", "bloqueado", "cancelado")
ESTADOS_NA_FILA = ("na_fila", "simulado", "falhou")

PUBLICOS = {
    "todos": "Todos os contatos",
    "nunca_compraram": "Só quem nunca comprou",
    "ja_compraram": "Só quem já comprou",
}
ROTULOS_ESTADO = {
    "na_fila": "Na fila",
    "simulado": "Simulado (nada saiu)",
    "enviado": "Enviado",
    "falhou": "Falhou (vai tentar de novo)",
    "bloqueado": "Bloqueado",
    "cancelado": "Cancelado",
}
MOTIVOS = {
    "sem_contato": "O contato não está mais na base",
    "sem_consentimento": "Sem autorização para receber mensagens",
    "nao_contatar": "Pediu para não ser procurado",
    "com_vendedor": "Conversa com vendedor agora",
    "conversou_recente": "Conversou com a loja há pouco tempo",
    "comprou_recente": "Comprou há pouco tempo",
    "tem_pos_venda": "Já está no pós-venda",
    "reativado_recente": "Já foi reativado nos últimos 6 meses",
    "ja_na_fila": "Já está na fila",
    "fora_do_publico": "Fora do público escolhido",
    "faltam_dados": "Falta o nome do cliente para o modelo",
    "sem_modelo": "O segmento não tem modelo de reativação",
    "modelo_nao_aprovado": "Modelo ainda não aprovado pela Meta nesta loja",
    "erro_no_envio": "O canal recusou o envio",
    "falhas_repetidas": "Falhou 3 vezes; precisa de alguém olhar",
    "fila_cancelada": "Fila cancelada no painel",
}


class ReativacaoInvalida(ValueError):
    pass


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _conectar():
    conexao = conectar()
    conexao.create_function("fone_br", 1, normalizar_telefone_br)
    return conexao


# ------------------------------------------------------------ fotografia da loja

@dataclass
class Fotografia:
    """Tudo que a decisão precisa, lido UMA vez (rápido mesmo com base grande)."""
    hoje: date
    falas: dict = field(default_factory=dict)        # telefone -> última fala do cliente (texto do banco)
    compras: dict = field(default_factory=dict)      # telefone -> dia da última compra (AAAA-MM-DD)
    com_vendedor: set = field(default_factory=set)
    pos_venda: set = field(default_factory=set)
    reativados: set = field(default_factory=set)
    na_fila: set = field(default_factory=set)
    bloqueados: set = field(default_factory=set)


def fotografia(loja_id, agora: datetime) -> Fotografia:
    loja_id = exigir_loja(loja_id)
    agora = _utc(agora)
    loja = carregar_loja(loja_id)
    foto = Fotografia(hoje=dia_local(loja, agora))
    desde = para_banco(agora - INTERVALO_ENTRE_REATIVACOES)
    conexao = _conectar()
    try:
        def mapa(sql):
            return {l[0]: l[1] for l in conexao.execute(sql, (loja_id,)).fetchall() if l[0]}

        def conjunto(sql, parametros=None):
            return {l[0] for l in conexao.execute(sql, parametros or (loja_id,)).fetchall() if l[0]}

        foto.falas = mapa(
            "SELECT fone_br(lead_id), MAX(criado_em) FROM mensagens WHERE loja_id = ? "
            "AND canal = 'whatsapp' AND direcao = 'cliente' GROUP BY fone_br(lead_id)")
        foto.compras = mapa(
            "SELECT telefone, MAX(data_compra) FROM compras_anteriores WHERE loja_id = ? GROUP BY telefone")
        vendas = mapa(
            "SELECT fone_br(lead_id), MAX(substr(data_venda, 1, 10)) FROM vendas WHERE loja_id = ? "
            "GROUP BY fone_br(lead_id)")
        for fone, dia in vendas.items():
            if str(dia) > str(foto.compras.get(fone) or ""):
                foto.compras[fone] = dia
        foto.com_vendedor = conjunto(
            "SELECT fone_br(lead_id) FROM handoffs WHERE loja_id = ? "
            "AND estado IN ('aguardando_humano', 'humano_assumiu')")
        foto.pos_venda = conjunto(
            "SELECT fone_br(lead_id) FROM regua_execucoes WHERE loja_id = ? AND estado = 'agendado'")
        foto.reativados = conjunto(
            "SELECT telefone FROM reativacao WHERE loja_id = ? AND estado = 'enviado' AND enviado_em >= ?",
            (loja_id, desde))
        foto.na_fila = conjunto(
            "SELECT telefone FROM reativacao WHERE loja_id = ? "
            "AND estado IN ('na_fila', 'simulado', 'falhou')")
        foto.bloqueados = conjunto("SELECT fone_br(lead_id) FROM optouts WHERE loja_id = ?")
        # Mesma regra de app/interesse.py (pode_contatar), lida de uma vez.
        for l in conexao.execute(
                "SELECT lead_id, situacao, retomar_em FROM situacao_lead WHERE loja_id = ?", (loja_id,)):
            fone = normalizar_telefone_br(l["lead_id"])
            if not fone:
                continue
            if (l["situacao"] == "pediu_tempo" and l["retomar_em"]
                    and foto.hoje >= date.fromisoformat(l["retomar_em"])):
                continue
            foto.bloqueados.add(fone)
    finally:
        conexao.close()
    return foto


def motivo_para_nao_reativar(foto: Fotografia, contato: dict, agora: datetime, meses: int,
                             publico: str = "todos") -> str | None:
    """A MESMA regra na montagem da fila e logo antes de enviar. None = pode."""
    fone = contato["telefone"]
    if not contato.get("consentimento"):
        return "sem_consentimento"
    if fone in foto.bloqueados:
        return "nao_contatar"
    if fone in foto.com_vendedor:
        return "com_vendedor"
    limite = _utc(agora) - timedelta(days=round(meses * DIAS_POR_MES))
    fala = foto.falas.get(fone)
    if fala and do_banco(fala) >= limite:
        return "conversou_recente"
    compra = foto.compras.get(fone)
    if compra and date.fromisoformat(str(compra)[:10]) >= limite.date():
        return "comprou_recente"
    if fone in foto.pos_venda:
        return "tem_pos_venda"
    if fone in foto.reativados:
        return "reativado_recente"
    if publico == "nunca_compraram" and compra:
        return "fora_do_publico"
    if publico == "ja_compraram" and not compra:
        return "fora_do_publico"
    return None


# ------------------------------------------------------------ fila

def montar_fila(loja_id, *, meses: int = MESES_PADRAO, publico: str = "todos", maximo: int = 100,
                usuario: str, agora: datetime | None = None) -> dict:
    loja_id = exigir_loja(loja_id)
    loja = carregar_loja(loja_id)
    if not modulo_ativo(loja, "remarketing"):
        raise ReativacaoInvalida("O remarketing desta loja está desligado. Ligue em Plano e limites.")
    if loja.get("remarketing.limite_mensal") is None:
        raise ReativacaoInvalida("Defina o limite mensal de contatos (Plano e limites) antes.")
    if meses not in OPCOES_MESES:
        raise ReativacaoInvalida(f"Escolha um destes prazos: {', '.join(map(str, OPCOES_MESES))} meses.")
    if publico not in PUBLICOS:
        raise ReativacaoInvalida("Público inválido.")
    if not 1 <= int(maximo) <= MAX_POR_LOTE:
        raise ReativacaoInvalida(f"O máximo por fila é de 1 a {MAX_POR_LOTE} contatos.")
    usuario = " ".join(str(usuario or "").split())
    if not usuario:
        raise ReativacaoInvalida("Informe quem está montando a fila.")

    agora = _utc(agora or agora_utc())
    foto = fotografia(loja_id, agora)
    conexao = conectar()
    try:
        contatos = [dict(l) for l in conexao.execute(
            "SELECT id, telefone, nome, consentimento FROM contatos WHERE loja_id = ? ORDER BY id",
            (loja_id,)).fetchall()]
    finally:
        conexao.close()

    ignorados, escolhidos = Counter(), []
    for c in contatos:
        if len(escolhidos) >= int(maximo):
            break
        if c["telefone"] in foto.na_fila:
            ignorados["ja_na_fila"] += 1
            continue
        motivo = motivo_para_nao_reativar(foto, c, agora, meses, publico)
        if motivo:
            ignorados[motivo] += 1
            continue
        escolhidos.append(c)

    lote = para_banco(agora)
    conexao = conectar()
    try:
        conexao.executemany(
            "INSERT OR IGNORE INTO reativacao (loja_id, contato_id, telefone, lote, meses_inativo, "
            "criado_por, estado, criado_em, atualizado_em) VALUES (?, ?, ?, ?, ?, ?, 'na_fila', ?, ?)",
            [(loja_id, c["id"], c["telefone"], lote, meses, usuario, lote, lote) for c in escolhidos])
        conexao.commit()
    finally:
        conexao.close()
    return {"lote": lote, "na_fila": len(escolhidos), "ignorados": dict(ignorados)}


def cancelar_fila(loja_id, *, agora: datetime | None = None) -> int:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        n = conexao.execute(
            "UPDATE reativacao SET estado = 'cancelado', motivo = 'fila_cancelada', atualizado_em = ? "
            "WHERE loja_id = ? AND estado IN ('na_fila', 'simulado', 'falhou')",
            (para_banco(_utc(agora or agora_utc())), loja_id)).rowcount
        conexao.commit()
    finally:
        conexao.close()
    return n


def resumo(loja_id) -> dict:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT estado, COUNT(*) AS n FROM reativacao WHERE loja_id = ? GROUP BY estado",
            (loja_id,)).fetchall()
    finally:
        conexao.close()
    saida = dict.fromkeys(ESTADOS, 0)
    saida.update({l["estado"]: l["n"] for l in linhas})
    return saida


def listar(loja_id, limite: int = 50) -> list[dict]:
    loja_id = exigir_loja(loja_id)
    conexao = conectar()
    try:
        linhas = conexao.execute("SELECT * FROM reativacao WHERE loja_id = ? ORDER BY id DESC LIMIT ?",
                                 (loja_id, limite)).fetchall()
    finally:
        conexao.close()
    return [dict(l) for l in linhas]


def ultima_compra(loja_id, telefone: str) -> dict | None:
    """O que a pessoa comprou por último (base importada ou botão Vendido)."""
    loja_id = exigir_loja(loja_id)
    conexao = _conectar()
    try:
        a = conexao.execute(
            "SELECT descricao, data_compra AS dia FROM compras_anteriores WHERE loja_id = ? "
            "AND telefone = ? ORDER BY data_compra DESC LIMIT 1", (loja_id, telefone)).fetchone()
        v = conexao.execute(
            "SELECT e.marca || ' ' || e.modelo || ' ' || e.ano AS descricao, "
            "substr(v.data_venda, 1, 10) AS dia FROM vendas v "
            "LEFT JOIN estoque e ON e.id = v.veiculo_id AND e.loja_id = v.loja_id "
            "WHERE v.loja_id = ? AND fone_br(v.lead_id) = ? ORDER BY v.data_venda DESC LIMIT 1",
            (loja_id, telefone)).fetchone()
    finally:
        conexao.close()
    opcoes = [dict(x) for x in (a, v) if x and x["dia"]]
    if not opcoes:
        return None
    melhor = max(opcoes, key=lambda x: str(x["dia"])[:10])
    return {"descricao": (melhor["descricao"] or "").strip(),
            "data": date.fromisoformat(str(melhor["dia"])[:10])}


def reativacao_recente(loja_id, lead_id: str, agora: datetime) -> dict | None:
    """A reativação ENVIADA a este número nas últimas 72 h (para o assistente ter contexto)."""
    loja_id = exigir_loja(loja_id)
    fone = normalizar_telefone_br(lead_id)
    if not fone:
        return None
    agora = _utc(agora)
    conexao = conectar()
    try:
        linha = conexao.execute(
            "SELECT texto, enviado_em FROM reativacao WHERE loja_id = ? AND telefone = ? "
            "AND estado = 'enviado' AND enviado_em >= ? AND enviado_em <= ? "
            "ORDER BY enviado_em DESC LIMIT 1",
            (loja_id, fone, para_banco(agora - JANELA_CONTEXTO), para_banco(agora))).fetchone()
    finally:
        conexao.close()
    if not linha or not (linha["texto"] or "").strip():
        return None
    return {"toque": 1, "texto": linha["texto"].strip(), "enviado_em": do_banco(linha["enviado_em"])}

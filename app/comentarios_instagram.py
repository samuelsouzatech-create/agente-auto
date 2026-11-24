"""
Comentários do Instagram viram conversa (IG2, Maratona 4).

Comentário novo num post ou anúncio da loja -> UMA mensagem privada (a "resposta privada" da Meta:
uma por comentário, até 7 dias depois do comentário; confirmado no IG0) -> a pessoa responde no
direct -> o Léo continua a conversa sabendo de que item ela falou.

Chaves (Configuração > Instagram), todas por loja:
- modulos.instagram (operador) e instagram.responder_comentarios: as DUAS ligadas, senão nada sai
  (padrão: desligadas; é o ponto de maior risco de spam).
- instagram.resposta_publica: a resposta curta e fixa no comentário ("Te chamei no direct."),
  no máximo uma por comentário, nunca com preço nem condição (padrão: desligada).
- instagram.palavras_comentario (vazio = qualquer comentário), instagram.limite_private_replies_h,
  instagram.comentarios_prazo_dias (7).

A mensagem sabe do item (decisão do Samuel: Opção B). O Léo lê a legenda do post (guardada por
post) e procura no CATÁLOGO da loja (SG2) com a busca que já existe:
- exatamente 1 item citado e disponível: cita o item (modelo e ano), sem preço, e oferece fotos;
- 1 item citado e vendido: diz que esse já saiu e oferece parecidos;
- nenhum ou mais de um: o texto genérico.
Os textos são da loja, sem emoji, passam pelas guardas e NUNCA levam preço (se sobrar preço, vai o
genérico). O item achado fica gravado como interesse do lead e a mensagem privada fica na conversa:
quando a pessoa responder, o Léo já sabe do item e não pergunta de novo.

Comentário da própria conta da loja: ignorado. Loja em teste (P7): só números de teste.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone

from app.canais import resolver_loja
from app.channels.instagram import CANAL, CanalInstagram, Comentario
from app.chaves import exigir_loja
from app.log import logger as _logger
from app.logs import registrar_canal_desconhecido
from banco import conectar

_log = _logger("comentarios_instagram")

TEXTO_ITEM_PADRAO = ("Oi! Vi seu comentário no post do {item}. Ele está disponível. "
                     "Quer que eu te mande mais fotos?")
TEXTO_VENDIDO_PADRAO = ("Oi! Vi seu comentário. Esse {item} já saiu, mas tenho opções parecidas. "
                        "Quer que eu te mostre?")
TEXTO_GENERICO_PADRAO = "Oi! Vi seu comentário, te chamei por aqui para te ajudar."
TEXTO_PUBLICO_PADRAO = "Te chamei no direct."
PRAZO_PADRAO_DIAS = 7                   # confirmado no IG0 ("within 7 days")
LEGENDA_VALE_HORAS = 24
FABRICA_DO_CANAL = CanalInstagram       # os testes trocam por um servidor falso da Meta

ITEM, VENDIDO, GENERICO = "item", "vendido", "generico"


def _sem_acento(texto: str) -> str:
    t = unicodedata.normalize("NFD", str(texto or "")).lower()
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _agora() -> datetime:
    from app.relogio import agora_utc
    return agora_utc()


# ------------------------------------------------------------------ registro do comentário (dedup)
def reservar(loja_id: int, c: Comentario) -> bool:
    """Grava o comentário (uma vez). False = já tinha (repetido: não manda nada de novo)."""
    conexao = conectar()
    try:
        linha = conexao.execute(
            "INSERT INTO instagram_comentarios (loja_id, comment_id, media_id, ad_id, lead_id, origem, estado) "
            "VALUES (?, ?, ?, ?, ?, ?, 'recebido') ON CONFLICT (loja_id, comment_id) DO NOTHING RETURNING id",
            (loja_id, c.comment_id, c.media_id or None, c.ad_id or None, c.lead_id, c.origem)).fetchone()
        conexao.commit()
    finally:
        conexao.close()
    return linha is not None


def _marcar(loja_id: int, comment_id: str, **campos) -> None:
    if not campos:
        return
    conexao = conectar()
    try:
        conexao.execute(f"UPDATE instagram_comentarios SET {', '.join(f'{k} = ?' for k in campos)} "
                        "WHERE loja_id = ? AND comment_id = ?", (*campos.values(), loja_id, comment_id))
        conexao.commit()
    finally:
        conexao.close()


def _respondidos_na_ultima_hora(loja_id: int, agora: datetime) -> int:
    from app.relogio import para_banco
    conexao = conectar()
    try:
        return int(conexao.execute(
            "SELECT COUNT(*) FROM instagram_comentarios WHERE loja_id = ? AND estado = 'respondido' "
            "AND criado_em >= ?", (loja_id, para_banco(agora - timedelta(hours=1)))).fetchone()[0])
    finally:
        conexao.close()


# ------------------------------------------------------------------ legenda (guardada por post)
async def legenda_do_post(loja_id: int, media_id: str, canal, agora: datetime) -> str:
    from app.relogio import do_banco, para_banco
    if not media_id:
        return ""
    conexao = conectar()
    try:
        linha = conexao.execute("SELECT legenda, lida_em FROM instagram_legendas WHERE loja_id = ? AND media_id = ?",
                                (loja_id, media_id)).fetchone()
    finally:
        conexao.close()
    if linha and linha["lida_em"] and do_banco(linha["lida_em"]) > agora - timedelta(hours=LEGENDA_VALE_HORAS):
        return linha["legenda"] or ""
    legenda = await canal.ler_legenda(media_id)
    if legenda is None:
        return (linha["legenda"] or "") if linha else ""
    conexao = conectar()
    try:
        conexao.execute(
            "INSERT INTO instagram_legendas (loja_id, media_id, legenda, lida_em) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (loja_id, media_id) DO UPDATE SET legenda = EXCLUDED.legenda, lida_em = EXCLUDED.lida_em",
            (loja_id, media_id, legenda, para_banco(agora)))
        conexao.commit()
    finally:
        conexao.close()
    return legenda


# ------------------------------------------------------------------ a mensagem (Opção B)
def _sem_preco_e_pelas_guardas(texto: str) -> str | None:
    """Os textos do comentário passam pelas guardas do motor. Preço nunca: None (usa o genérico)."""
    from app.guarda_politica import (limitar_emojis, tirar_palavra_de_tempo, trocar_frases_proibidas,
                                     valores_em_reais)
    texto = limitar_emojis(texto, 0)[0]
    texto = trocar_frases_proibidas(texto)[0]
    texto = tirar_palavra_de_tempo(texto)[0]
    if valores_em_reais(texto) or re.search(r"r\$", texto, re.I):
        return None
    return texto.strip() or None


def montar_mensagem(loja, legenda: str) -> tuple[str, str, object]:
    """(texto, caminho, item). caminho: item | vendido | generico."""
    from app.catalogo import catalogo_da_loja
    generico = _sem_preco_e_pelas_guardas(
        str(loja.get("instagram.texto_private_reply") or TEXTO_GENERICO_PADRAO)) or TEXTO_GENERICO_PADRAO
    if not legenda.strip():
        return generico, GENERICO, None
    itens = catalogo_da_loja(loja.id).citados_no_texto(loja.id, legenda)
    if len(itens) != 1:
        return generico, GENERICO, None
    item = itens[0]
    modelo = (loja.get("instagram.texto_comentario_item") or TEXTO_ITEM_PADRAO) if item.disponivel \
        else (loja.get("instagram.texto_comentario_vendido") or TEXTO_VENDIDO_PADRAO)
    try:
        texto = str(modelo).format(item=item.nome)
    except (KeyError, IndexError, ValueError):
        return generico, GENERICO, None
    texto = _sem_preco_e_pelas_guardas(texto)
    if texto is None:
        return generico, GENERICO, None
    return texto, (ITEM if item.disponivel else VENDIDO), item


def registrar_interesse_no_item(loja_id: int, lead_id: str, item_id: int) -> None:
    """O item do post vira o interesse do lead (a tabela é a de antes: interesse_veiculo)."""
    conexao = conectar()
    try:
        conexao.execute(
            "INSERT INTO interesse_veiculo (loja_id, lead_id, veiculo_id) VALUES (?, ?, ?) "
            "ON CONFLICT (loja_id, lead_id) DO UPDATE SET veiculo_id = EXCLUDED.veiculo_id, "
            "atualizado_em = agora_texto()", (loja_id, lead_id, item_id))
        conexao.commit()
    finally:
        conexao.close()


# ------------------------------------------------------------------ o fluxo
def _palavra_combina(loja, texto: str) -> bool:
    palavras = [p for p in (loja.get("instagram.palavras_comentario") or []) if str(p).strip()]
    if not palavras:
        return True
    normal = _sem_acento(texto)
    return any(_sem_acento(p) in normal for p in palavras)


def _dentro_do_prazo(loja, c: Comentario, agora: datetime) -> bool:
    dias = int(loja.get("instagram.comentarios_prazo_dias") or PRAZO_PADRAO_DIAS)
    if not c.hora:
        return True
    quando = datetime.fromtimestamp(c.hora, tz=timezone.utc)
    return agora - quando < timedelta(days=dias)


async def tratar_comentario(loja_id, c: Comentario, *, agora: datetime | None = None) -> str:
    """Decide e (se for o caso) manda a mensagem privada. Devolve o estado gravado."""
    from app.estado_loja import pode_responder
    from app.instagram import anotar_origem, gravar_ids_do_leo
    from app.lojas import carregar_loja
    from app.mensagens import salvar_mensagem
    loja_id = exigir_loja(loja_id)
    agora = agora or _agora()
    if not reservar(loja_id, c):
        return "repetido"
    loja = carregar_loja(loja_id)

    def fim(estado: str, **extra) -> str:
        _marcar(loja_id, c.comment_id, estado=estado, **extra)
        return estado

    if c.da_propria_loja:
        return fim("propria_loja")
    if not (loja.get("modulos.instagram") and loja.get("instagram.responder_comentarios")):
        return fim("desligado")
    if not pode_responder(loja_id, CANAL, c.lead_id):            # P7: loja em teste
        return fim("loja_em_teste")
    if not _dentro_do_prazo(loja, c, agora):
        return fim("fora_do_prazo")
    if not _palavra_combina(loja, c.texto):
        return fim("sem_palavra")
    from app.elegibilidade import pode_contatar
    from app.relogio import dia_local
    if not pode_contatar(loja_id, c.lead_id, dia_local(loja, agora)):
        return fim("nao_contatar")
    limite = int(loja.get("instagram.limite_private_replies_h") or 0)
    if limite and _respondidos_na_ultima_hora(loja_id, agora) >= limite:
        return fim("limite")

    canal = FABRICA_DO_CANAL(loja_id)
    legenda = await legenda_do_post(loja_id, c.media_id, canal, agora)
    texto, caminho, item = montar_mensagem(loja, legenda)
    resultado = await canal.responder_comentario_no_privado(c.comment_id, texto)
    if not resultado.ok:
        return fim("falhou", caminho=caminho)
    salvar_mensagem(c.lead_id, "leo", texto, canal=CANAL, loja_id=loja_id)
    gravar_ids_do_leo(loja_id, c.lead_id, canal.ids_enviados)
    anotar_origem(loja_id, c.lead_id, c.origem, c.ad_id or c.media_id)
    if item is not None:
        registrar_interesse_no_item(loja_id, c.lead_id, item.id)
    publica = None
    if loja.get("instagram.resposta_publica"):
        texto_publico = _sem_preco_e_pelas_guardas(
            str(loja.get("instagram.texto_resposta_publica") or TEXTO_PUBLICO_PADRAO)) or TEXTO_PUBLICO_PADRAO
        publica = "respondida" if (await canal.responder_comentario_em_publico(c.comment_id, texto_publico)).ok \
            else "falhou"
    return fim("respondido", caminho=caminho, item_id=item.id if item is not None else None,
               resposta_publica=publica)


async def receber_comentarios(dados, tarefas) -> int:
    """Chamado pela porta (POST /webhook/instagram). Conta desconhecida: ignora e anota."""
    n = 0
    for c in CanalInstagram().ler_comentarios(dados):
        loja_id = resolver_loja(CANAL, c.id_conta)
        if loja_id is None:
            registrar_canal_desconhecido(CANAL, c.id_conta)
            continue
        tarefas.add_task(tratar_comentario, loja_id, c)
        n += 1
    return n

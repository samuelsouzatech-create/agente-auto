"""
Porta do Instagram (IG1, Maratona 4): GET e POST /webhook/instagram, no MESMO servidor do webhook
do WhatsApp (app/api/webhook.py inclui estas rotas). Só a porta: valida, lê, descobre a loja,
deduplica, responde 200 rápido e agenda o processamento. O atendimento é o executar_turno() de
sempre (debounce, trava por cliente, opt-out, guardas, loja em teste P7).

- Assinatura X-Hub-Signature-256 (sha256 do corpo com o App Secret do .env, INSTAGRAM_APP_SECRET).
  Sem segredo configurado: recusa (falha fechada), como o WhatsApp.
- Conta desconhecida (id que não está em canais): 200, ignora e grava no Registro.
- Eco: da resposta do próprio Léo, descartado pelo id; de vendedor pelo app, o Léo fica quieto.
- O que o Léo não entende (anexo, compartilhamento): resposta curta, sem IA.
- IG2: comentários entram por aqui também (app/comentarios_instagram.py).
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response

from app.canais import resolver_loja
from app.channels.base import enviar_resultado
from app.channels.instagram import CANAL, MENSAGEM_NAO_ENTENDI, CanalInstagram
from app.console import id_no_console
from app.dedup import ja_processada
from app.instagram import anotar_origem, e_eco_do_leo, gravar_ids_do_leo, vendedor_respondeu_pelo_app
from app.log import logger as _logger
from app.logs import registrar_canal_desconhecido
from app.recebidas import anotar as anotar_recebida

_log = _logger("webhook_instagram")
rotas = APIRouter()

# I3: espera antes de decidir um eco (a resposta da Meta com o id da bolha pode chegar DEPOIS do eco).
ESPERA_DO_ECO_S = 3.0
# Os testes trocam isto por um "servidor falso da Meta".
FABRICA_DO_CANAL = CanalInstagram


def verify_token() -> str:
    return os.getenv("INSTAGRAM_VERIFY_TOKEN", "")


def app_secret() -> str:
    return os.getenv("INSTAGRAM_APP_SECRET", "")


def grafo_do_turno():
    from app.core.agent import agente_grafo          # import tardio (cria a IA)
    return agente_grafo


@rotas.get("/webhook/instagram")
def verificar(hub_mode: str = Query(default="", alias="hub.mode"),
              hub_verify_token: str = Query(default="", alias="hub.verify_token"),
              hub_challenge: str = Query(default="", alias="hub.challenge")):
    token = verify_token()
    if hub_mode == "subscribe" and token and hmac.compare_digest(hub_verify_token, token):
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(content="Token de verificação inválido", status_code=403)


async def processar_texto(loja_id: int, lead_id: str, texto: str) -> None:
    """Segundo plano: debounce + trava -> executar_turno -> envio pela conta DESTA loja."""
    from app.core.turno import aguardar_vez, executar_turno
    from app.redis_lock import liberar_lock
    texto_juntado, token = await aguardar_vez(loja_id, lead_id, texto)
    if texto_juntado is None:
        return
    try:
        resultado = await executar_turno(loja_id, CANAL, lead_id, texto_juntado, grafo=grafo_do_turno())
        if resultado.silenciado or not resultado.texto:
            return
        canal = FABRICA_DO_CANAL(loja_id)
        await enviar_resultado(canal, lead_id, resultado, loja_id=loja_id)
        gravar_ids_do_leo(loja_id, lead_id, canal.ids_enviados)
    finally:
        await liberar_lock(lead_id, token, loja_id=loja_id)


async def processar_nao_entendido(loja_id: int, lead_id: str, tipo_original: str) -> None:
    from app.core.turno import turno_resposta_fixa
    resultado = turno_resposta_fixa(loja_id, CANAL, lead_id, f"[{tipo_original or 'anexo'}]",
                                    MENSAGEM_NAO_ENTENDI, tipo=tipo_original or "anexo")
    if resultado.texto:
        canal = FABRICA_DO_CANAL(loja_id)
        await canal.enviar_texto(lead_id, resultado.texto)
        gravar_ids_do_leo(loja_id, lead_id, canal.ids_enviados)


async def processar_eco(loja_id: int, lead_id: str, id_externo: str, texto: str) -> None:
    if ESPERA_DO_ECO_S:
        await asyncio.sleep(ESPERA_DO_ECO_S)
    if e_eco_do_leo(loja_id, lead_id, id_externo):
        _log.info(f"[Instagram][loja {loja_id}] Eco da própria resposta do Léo: descartado.")
        return
    _log.info(f"[Instagram][loja {loja_id}] Vendedor respondeu {id_no_console(lead_id, CANAL)} pelo app: "
              "o Léo fica em silêncio.")
    vendedor_respondeu_pelo_app(loja_id, lead_id, texto)


def assinatura_valida(corpo: bytes, cabecalho: str | None) -> bool:
    from app.api.webhook import assinatura_valida as _valida     # a MESMA conta do WhatsApp
    return _valida(corpo, cabecalho or "", app_secret())


@rotas.post("/webhook/instagram")
async def receber(request: Request, tarefas: BackgroundTasks):
    corpo = await request.body()
    if not assinatura_valida(corpo, request.headers.get("X-Hub-Signature-256")):
        _log.warning("[Instagram] Assinatura inválida no POST. Rejeitado (403).")
        return Response(status_code=403)
    try:
        dados = json.loads(corpo)
    except Exception:
        return Response(status_code=200)
    leitor = CanalInstagram()
    for entrada in leitor.ler_direct(dados):
        m = entrada.mensagem
        loja_id = resolver_loja(CANAL, m.id_canal)
        if loja_id is None:
            registrar_canal_desconhecido(CANAL, m.id_canal)
            continue
        if await ja_processada(CANAL, m.id_externo):
            continue
        if entrada.eco:
            tarefas.add_task(processar_eco, loja_id, m.lead_id, m.id_externo, m.texto)
            continue
        anotar_recebida(loja_id, CANAL, m.lead_id, m.id_externo)
        anotar_origem(loja_id, m.lead_id, entrada.origem, entrada.origem_detalhe)
        if m.tipo == "texto":
            tarefas.add_task(processar_texto, loja_id, m.lead_id, m.texto)
        else:
            tarefas.add_task(processar_nao_entendido, loja_id, m.lead_id, m.tipo_original)
    from app.comentarios_instagram import receber_comentarios        # IG2: comentários
    await receber_comentarios(dados, tarefas)
    return Response(status_code=200)

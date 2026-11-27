"""
Servidor web (FastAPI) do webhook do WhatsApp - só a "porta".

POST /webhook: valida assinatura -> lê TODAS as mensagens do pacote ->
descobre a loja -> deduplica -> agenda o processamento e responde 200.
O atendimento em si é o executar_turno() (app/core/turno.py).

Revisão da Etapa 1: toda função daqui exige a loja (nada de "loja 1 por
reserva") e todo envio sai pelo número da loja (app/credenciais.py).

P7c: áudio de quem não é número de teste, numa loja em teste, nem é
transcrito (a transcrição custa). A porta grava o evento no Registro.
"""
import hashlib
import hmac
import json

from fastapi import FastAPI, Request, Response, Query, BackgroundTasks

from app.config import WHATSAPP_VERIFY_TOKEN, WHATSAPP_APP_SECRET
from app.core.agent import agente_grafo
from app.core.turno import (
    executar_turno, aguardar_vez, porta_fechada, turno_midia_nao_suportada, turno_audio_falhou,
    executar_turno_imagem,
)
from app.api.enviar_whatsapp import enviar_resposta_humanizada, enviar_foto_whatsapp
from app import fotos
from app.envio_fotos import enviar_fotos_e_texto
from app.api.receber_audio import transcrever_audio, pegar_uso_da_transcricao
from app.console import id_no_console, texto_no_console   # N1
from app.limites_midia import MidiaGrandeDemais   # N2
from app.core.turno import turno_midia_grande   # N2
from app.api.receber_imagem import baixar_imagem_whatsapp
from app.redis_lock import adquirir_lock_esperando
from app.custos import registrar_uso
from app.channels.whatsapp import CanalWhatsApp
from app.redis_lock import liberar_lock
from app.redis_atraso import calcular_atraso
from app.dedup import ja_processada
from app.canais import resolver_loja
from app.chaves import exigir_loja
from app.logs import registrar_canal_desconhecido
from app.log import logger as _logger   # N3: registro técnico (logs/leo.log)
from app.recebidas import anotar as anotar_recebida, avisar_ao_ligar as avisar_sem_resposta   # N3
_log = _logger("webhook")

CANAL = "whatsapp"
app = FastAPI(title="Agente Léo - Webhook WhatsApp")

# SE3 (Maratona Segurança): o webhook atende TODAS as lojas (descobre a loja pelo canal de cada
# mensagem), então o processo dele usa o modo sistema da tranca por loja do banco.
import banco as _banco  # noqa: E402
_banco.declarar_sistema("webhook (app/api/webhook.py)")
canal_whatsapp = CanalWhatsApp()   # só lê o webhook; quem envia diz a loja a cada chamada

# Última mensagem recebida de cada cliente (para marcar como lida antes de responder).
_ultima_recebida: dict[tuple[int, str], str] = {}
_LIMITE_ULTIMAS = 5000


def _lembrar_ultima(loja_id: int, lead_id: str, id_mensagem: str) -> None:
    if len(_ultima_recebida) > _LIMITE_ULTIMAS:
        _ultima_recebida.clear()
    _ultima_recebida[(loja_id, lead_id)] = id_mensagem


async def sinalizar_leitura(loja_id: int, lead_id: str) -> None:
    """Checks azuis + 'digitando...' na última mensagem do cliente (pelo número da loja)."""
    id_mensagem = _ultima_recebida.pop((loja_id, lead_id), None)
    if id_mensagem:
        await canal_whatsapp.marcar_lida(id_mensagem, digitando=True, loja_id=loja_id)


def avisar_configuracao() -> list[str]:
    """N1: o que falta configurar para o webhook do WhatsApp aceitar algo (avisa ao ligar)."""
    faltando = [nome for nome, valor in (("WHATSAPP_VERIFY_TOKEN", WHATSAPP_VERIFY_TOKEN),
                                         ("WHATSAPP_APP_SECRET", WHATSAPP_APP_SECRET)) if not valor]
    for nome in faltando:
        _log.error(f"[WhatsApp] AVISO: {nome} não está no .env. O webhook vai recusar (falha fechada).")
    return faltando


avisar_configuracao()      # ao ligar o servidor (o módulo é carregado uma vez)
try:
    avisar_sem_resposta()  # N3: mensagens das últimas 24 h sem resposta (só lista; não responde)
except Exception:
    _log.exception("[WhatsApp] Não consegui listar as mensagens sem resposta ao ligar.")


@app.get("/")
def raiz():
    return {"status": "ok", "mensagem": "Servidor do Léo está no ar 🚗"}


@app.get("/webhook")
def verificar_webhook(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
):
    # N1: sem token configurado, nunca aceita (falha fechada); comparação em tempo constante.
    if (hub_mode == "subscribe" and WHATSAPP_VERIFY_TOKEN
            and hmac.compare_digest(hub_verify_token, WHATSAPP_VERIFY_TOKEN)):
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(content="Token de verificação inválido", status_code=403)


def assinatura_valida(corpo: bytes, cabecalho: str, segredo: str) -> bool:
    """HMAC-SHA256 do corpo cru com o App Secret. Falha FECHADA sem segredo."""
    if not segredo:
        return False
    if not cabecalho or not cabecalho.startswith("sha256="):
        return False
    enviado = cabecalho.split("=", 1)[1]
    esperado = hmac.new(segredo.encode("utf-8"), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(enviado, esperado)


# --- Compatibilidade com código antigo (lê só a 1ª mensagem) ---
def extrair_mensagem(dados: dict):
    entradas = canal_whatsapp.ler_webhook(dados)
    if not entradas:
        return None, None, None, None
    e = entradas[0]
    return e.id_externo, e.lead_id, (e.texto or None), (e.id_midia or None)


def extrair_id_canal(dados: dict):
    entradas = canal_whatsapp.ler_webhook(dados)
    return entradas[0].id_canal if entradas else None


async def processar_mensagem(numero: str, texto: str, id_audio: str = None,
                             loja_id: int | None = None):
    """Segundo plano: (áudio) -> debounce + lock -> executar_turno -> envio."""
    loja_id = exigir_loja(loja_id)
    if id_audio:
        # P7c: loja em teste e não é número de teste: nem transcreve (custo).
        if porta_fechada(loja_id, CANAL, numero):
            return
        _log.info(f"[WhatsApp][loja {loja_id}] Cliente {id_no_console(numero, CANAL)} mandou um áudio. Transcrevendo...")
        try:
            texto = await transcrever_audio(id_audio, loja_id=loja_id)
        except MidiaGrandeDemais:                                         # N2
            aviso = turno_midia_grande(loja_id, CANAL, numero, "audio")
            if aviso.texto:
                await enviar_resposta_humanizada(numero, aviso.texto, loja_id=loja_id)
            return
        uso_audio = pegar_uso_da_transcricao(id_audio)
        if uso_audio is not None and not uso_audio.vazio:
            registrar_uso(loja_id, numero, CANAL, uso_audio,
                          tipo="transcricao", ferramentas=["transcricao_audio"])
        if not texto:
            aviso = turno_audio_falhou(loja_id, CANAL, numero)
            if aviso.texto:
                await enviar_resposta_humanizada(numero, aviso.texto, loja_id=loja_id)
            return
        _log.info(f"[WhatsApp][loja {loja_id}] Áudio transcrito: {texto_no_console(texto, CANAL)}")

    texto_juntado, token = await aguardar_vez(loja_id, numero, texto)
    if texto_juntado is None:
        return

    try:
        atraso = await calcular_atraso(numero, loja_id=loja_id)
        resultado = await executar_turno(loja_id, CANAL, numero, texto_juntado, grafo=agente_grafo)
        if resultado.silenciado or not resultado.texto:
            return
        await sinalizar_leitura(loja_id, numero)
        await _enviar_resultado(numero, resultado, atraso, loja_id)
    finally:
        await liberar_lock(numero, token, loja_id=loja_id)


async def _enviar_resultado(numero: str, resultado, atraso: float, loja_id: int) -> list[str]:
    """Maratona Fotos: fotos primeiro (só do depósito, pelo endereço https público, que só a
    tomada nuvem tem; sem ele, é falha honesta), depois o texto. Foto falhada: a trava de
    app/envio_fotos.py corrige o texto e abre o chamado."""
    async def _foto(ref: str) -> bool:
        url = fotos.endereco_publico(loja_id, ref)
        if not url:
            return False
        return await enviar_foto_whatsapp(numero, url, loja_id=loja_id)

    async def _texto(texto: str) -> None:
        await enviar_resposta_humanizada(numero, texto, atraso, loja_id=loja_id)

    return await enviar_fotos_e_texto(loja_id=loja_id, lead_id=numero, texto=resultado.texto,
                                      refs=list(resultado.midias or []), enviar_foto=_foto,
                                      enviar_texto=_texto)


async def processar_imagem(numero: str, id_midia: str, legenda: str = "",
                           loja_id: int | None = None):
    """L5: foto do cliente -> lock -> executar_turno_imagem -> envio.
    Sem debounce: a foto é um turno sozinha. A imagem não é guardada."""
    loja_id = exigir_loja(loja_id)
    if porta_fechada(loja_id, CANAL, numero):           # P7: nem baixa (custo)
        return
    token = await adquirir_lock_esperando(numero, loja_id=loja_id)
    if token is None:
        return
    try:
        try:
            baixada = await baixar_imagem_whatsapp(id_midia, loja_id=loja_id)
        except MidiaGrandeDemais:                                         # N2
            aviso = turno_midia_grande(loja_id, CANAL, numero, "imagem")
            if aviso.texto:
                await enviar_resposta_humanizada(numero, aviso.texto, loja_id=loja_id)
            return
        imagem, mime = baixada if baixada else (b"", "")
        atraso = await calcular_atraso(numero, loja_id=loja_id)
        resultado = await executar_turno_imagem(
            loja_id, CANAL, numero, imagem, mime, legenda, grafo=agente_grafo,
            leitor=None if imagem else _leitura_falhou)
        if resultado.silenciado or not resultado.texto:
            return
        await sinalizar_leitura(loja_id, numero)
        await _enviar_resultado(numero, resultado, atraso, loja_id)
    finally:
        await liberar_lock(numero, token, loja_id=loja_id)


def _leitura_falhou(imagem, mime):
    """Foto que não deu para baixar: o turno segue como leitura que falhou."""
    from app.imagens import LeituraImagem
    return LeituraImagem(ok=False)


async def responder_midia_nao_suportada(numero: str, tipo_original: str,
                                        loja_id: int | None = None):
    loja_id = exigir_loja(loja_id)
    resultado = turno_midia_nao_suportada(loja_id, CANAL, numero, tipo_original)
    if resultado.texto:
        await sinalizar_leitura(loja_id, numero)
        await enviar_resposta_humanizada(numero, resultado.texto, loja_id=loja_id)


@app.post("/webhook")
async def receber_mensagem(request: Request, tarefas: BackgroundTasks):
    corpo = await request.body()

    if not assinatura_valida(corpo, request.headers.get("X-Hub-Signature-256"), WHATSAPP_APP_SECRET):
        _log.warning("[WhatsApp] Assinatura inválida no POST. Rejeitado (403).")
        return Response(status_code=403)

    try:
        dados = json.loads(corpo)
    except Exception:
        _log.exception("[WhatsApp] POST com corpo que não é JSON. Ignorado (200).")
        return Response(status_code=200)

    for entrada in canal_whatsapp.ler_webhook(dados):
        loja_id = resolver_loja(CANAL, entrada.id_canal)
        if loja_id is None:
            registrar_canal_desconhecido(CANAL, entrada.id_canal)
            continue
        if await ja_processada(CANAL, entrada.id_externo):
            _log.info(f"[WhatsApp] Mensagem {entrada.id_externo} já processada. Ignorando duplicata.")
            continue

        _lembrar_ultima(loja_id, entrada.lead_id, entrada.id_externo)
        try:                                   # IG3: o telefone que um lead do Instagram passou?
            from app.instagram_whatsapp import vincular_mesmo_cliente
            vincular_mesmo_cliente(loja_id, CANAL, entrada.lead_id)
        except Exception:
            _log.exception("[WhatsApp] Não consegui conferir o mesmo cliente do Instagram.")
        anotar_recebida(loja_id, CANAL, entrada.lead_id, entrada.id_externo)   # N3: antes do 200
        if entrada.nome_perfil:                # RG1: nome do perfil, só se a ficha está sem nome
            try:
                from app.nome_do_perfil import gravar_nome_do_perfil
                gravar_nome_do_perfil(loja_id, entrada.lead_id, entrada.nome_perfil)
            except Exception:
                _log.exception("[WhatsApp] Não consegui gravar o nome do perfil.")
        if entrada.tipo == "texto":
            tarefas.add_task(processar_mensagem, entrada.lead_id, entrada.texto, None, loja_id)
        elif entrada.tipo == "audio":
            tarefas.add_task(processar_mensagem, entrada.lead_id, None, entrada.id_midia, loja_id)
        elif entrada.tipo == "imagem":
            tarefas.add_task(processar_imagem, entrada.lead_id, entrada.id_midia, entrada.texto, loja_id)
        else:
            tarefas.add_task(responder_midia_nao_suportada, entrada.lead_id,
                             entrada.tipo_original, loja_id)

    return Response(status_code=200)


# IG1 (Maratona 4): GET/POST /webhook/instagram no MESMO servidor (app/api/webhook_instagram.py).
from app.api.webhook_instagram import rotas as _rotas_instagram  # noqa: E402
app.include_router(_rotas_instagram)

# IG3 (I6): exclusão de dados a pedido da Meta (app/api/dados.py).
from app.api.dados import rotas as _rotas_dados  # noqa: E402
app.include_router(_rotas_dados)

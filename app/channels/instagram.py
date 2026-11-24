"""Canal Instagram (direct e comentários), no contrato de app/channels/base.py (IG1, Maratona 4).

Formato e regras conferidos na documentação oficial da Meta no IG0 (tabela em docs/maratona4.md):
- mensagem: object "instagram", entry[].id = conta da LOJA, entry[].messaging[] com sender, recipient,
  timestamp e message.mid/text;
- eco (message.is_echo = true): mensagem que a PRÓPRIA conta mandou (o Léo ou um vendedor pelo app);
  no eco, sender é a loja e recipient é o cliente;
- texto de envio: até 1000 bytes (UTF-8); o Léo divide em bolhas dentro desse limite;
- envio: POST <API>/<versão>/<id da conta>/messages, com o token da loja (Bearer).

O lead é o id do usuário no Instagram, SEM telefone, com o prefixo "ig:" (nunca colide com telefone).
O token fica no .env, referido pelo token_ref do canal (app/credenciais.py): nunca no banco aberto.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

from app.channels.base import Canal, MensagemEntrada
from app.chaves import exigir_loja
from app.log import logger as _logger
from app.resultado_envio import ResultadoEnvio

_log = _logger("instagram")

CANAL = "instagram"
PREFIXO = "ig:"
LIMITE_BYTES = 1000                     # confirmado no IG0 ("1000 bytes or less")
API_URL_PADRAO = "https://graph.facebook.com"   # IG0: recomendado o login do Facebook
API_VERSAO_PADRAO = "v27.0"                     # versão citada nas páginas da Meta (24/11/2026)

# Resposta curta para o que o Léo não entende (compartilhamento de post, anexo, figurinha...).
MENSAGEM_NAO_ENTENDI = "Por aqui eu consigo ler só mensagens de texto. Pode me escrever?"


def api_url() -> str:
    return (os.getenv("INSTAGRAM_API_URL") or API_URL_PADRAO).rstrip("/")


def api_versao() -> str:
    return os.getenv("INSTAGRAM_API_VERSAO") or API_VERSAO_PADRAO


def lead_do_instagram(id_usuario) -> str:
    texto = str(id_usuario or "").strip()
    if not texto:
        return ""
    return texto if texto.startswith(PREFIXO) else PREFIXO + texto


def id_do_usuario(lead_id: str) -> str:
    lead_id = str(lead_id or "")
    return lead_id[len(PREFIXO):] if lead_id.startswith(PREFIXO) else lead_id


def _dicts(valor) -> list[dict]:
    return [x for x in valor if isinstance(x, dict)] if isinstance(valor, list) else []


def _inteiro(valor) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class EntradaInstagram:
    """O que chegou no direct. `eco`: a própria conta da loja mandou (Léo ou vendedor pelo app)."""
    mensagem: MensagemEntrada
    eco: bool = False
    origem: str = "direto"              # direto | anuncio | perfil (I5; "referral" a confirmar)
    origem_detalhe: str = ""


@dataclass(frozen=True)
class Comentario:
    """IG2: comentário num post ou anúncio da loja."""
    id_conta: str                       # a conta da LOJA (entry.id)
    comment_id: str
    autor_id: str                       # quem comentou
    autor_nome: str = ""
    texto: str = ""
    media_id: str = ""
    ad_id: str = ""
    hora: int = 0
    tipo_midia: str = ""
    extras: dict = field(default_factory=dict, compare=False)

    @property
    def lead_id(self) -> str:
        return lead_do_instagram(self.autor_id)

    @property
    def da_propria_loja(self) -> bool:
        return bool(self.autor_id) and self.autor_id == self.id_conta

    @property
    def origem(self) -> str:
        return "anuncio" if self.ad_id else "comentario"


def dividir_no_limite(texto: str, limite: int = LIMITE_BYTES) -> list[str]:
    """Pedaços de no máximo `limite` bytes (UTF-8), cortando de preferência em espaço."""
    texto = str(texto or "").strip()
    pedacos = []
    while texto:
        if len(texto.encode("utf-8")) <= limite:
            pedacos.append(texto)
            break
        corte = len(texto.encode("utf-8")[:limite].decode("utf-8", "ignore"))
        espaco = texto.rfind(" ", 0, corte)
        if espaco > corte // 2:
            corte = espaco
        pedacos.append(texto[:corte].strip())
        texto = texto[corte:].strip()
    return [p for p in pedacos if p]


def _origem(msg: dict) -> tuple[str, str]:
    """I5: mensagem que veio de anúncio (referral com source ADS) ou do perfil. A confirmar com a
    conta real (o IG0 não achou o formato de 'referral' para o Instagram); sem isso: direto."""
    referral = msg.get("referral") or (msg.get("message") or {}).get("referral")
    if not isinstance(referral, dict):
        return "direto", ""
    fonte = str(referral.get("source") or "").upper()
    if fonte == "ADS":
        return "anuncio", str(referral.get("ad_id") or "")
    return "perfil", ""


class CanalInstagram(Canal):
    nome = CANAL
    respiro_s = 1.0
    pausa_entre_bolhas = 1.5

    def __init__(self, loja_id: int | None = None, *, postar=None):
        self.loja_id = loja_id
        self._postar_http = postar or _postar_http
        self.ids_enviados: list[str] = []

    def _loja(self) -> int:
        return exigir_loja(self.loja_id)

    # ---------------------------------------------------------------- leitura
    def ler_webhook(self, payload) -> list[MensagemEntrada]:
        """Só as mensagens de CLIENTE (o contrato dos canais). Ecos: ler_direct."""
        return [e.mensagem for e in self.ler_direct(payload) if not e.eco]

    def ler_direct(self, payload) -> list[EntradaInstagram]:
        entradas = []
        if not isinstance(payload, dict) or payload.get("object") != "instagram":
            return entradas
        for entry in _dicts(payload.get("entry")):
            id_conta = str(entry.get("id") or "")
            for msg in _dicts(entry.get("messaging")):
                entrada = self._converter(msg, id_conta)
                if entrada is not None:
                    entradas.append(entrada)
        return entradas

    def _converter(self, msg: dict, id_conta: str) -> EntradaInstagram | None:
        mensagem = msg.get("message") if isinstance(msg.get("message"), dict) else None
        if mensagem is None:
            return None                  # reação, leitura, postback: nada a responder
        if mensagem.get("is_deleted"):
            return None
        mid = str(mensagem.get("mid") or "")
        remetente = str((msg.get("sender") or {}).get("id") or "")
        destinatario = str((msg.get("recipient") or {}).get("id") or "")
        if not mid or not remetente:
            return None
        eco = bool(mensagem.get("is_echo"))
        cliente = destinatario if eco else remetente
        if not cliente:
            return None
        comum = dict(canal=CANAL, id_externo=mid, lead_id=lead_do_instagram(cliente),
                     id_canal=id_conta, hora=_inteiro(msg.get("timestamp")))
        texto = str(mensagem.get("text") or "").strip()
        origem, detalhe = _origem(msg)
        if texto:
            return EntradaInstagram(MensagemEntrada(tipo="texto", texto=texto, tipo_original="text", **comum),
                                    eco=eco, origem=origem, origem_detalhe=detalhe)
        anexos = _dicts(mensagem.get("attachments"))
        tipo = str(anexos[0].get("type") or "anexo") if anexos else "anexo"
        return EntradaInstagram(MensagemEntrada(tipo="nao_suportado", tipo_original=tipo, **comum),
                                eco=eco, origem=origem, origem_detalhe=detalhe)

    def ler_comentarios(self, payload) -> list[Comentario]:
        """IG2: comentários (o IG0 achou duas formas publicadas: dentro de entry[].changes[] e
        field/value direto no entry). As duas são lidas."""
        saida = []
        if not isinstance(payload, dict) or payload.get("object") != "instagram":
            return saida
        for entry in _dicts(payload.get("entry")):
            id_conta = str(entry.get("id") or "")
            mudancas = _dicts(entry.get("changes"))
            if entry.get("field") and isinstance(entry.get("value"), dict):
                mudancas.append({"field": entry["field"], "value": entry["value"]})
            for mudanca in mudancas:
                if mudanca.get("field") != "comments" or not isinstance(mudanca.get("value"), dict):
                    continue
                v = mudanca["value"]
                autor = v.get("from") if isinstance(v.get("from"), dict) else {}
                midia = v.get("media") if isinstance(v.get("media"), dict) else {}
                if not v.get("id") or not autor.get("id"):
                    continue
                saida.append(Comentario(
                    id_conta=id_conta, comment_id=str(v["id"]), autor_id=str(autor["id"]),
                    autor_nome=str(autor.get("username") or ""), texto=str(v.get("text") or ""),
                    media_id=str(midia.get("id") or ""), ad_id=str(midia.get("ad_id") or ""),
                    hora=_inteiro(entry.get("time")), tipo_midia=str(midia.get("media_product_type") or ""),
                    extras={"parent_id": v.get("parent_id"), "original_media_id": midia.get("original_media_id")}))
        return saida

    # ---------------------------------------------------------------- envio
    async def enviar_texto_detalhado(self, lead_id: str, texto: str) -> ResultadoEnvio:
        """Manda o texto (dividido em até 1000 bytes) pela conta DESTA loja. Guarda os ids
        (ids_enviados) para o eco do próprio Léo ser descartado."""
        ultimo = ResultadoEnvio(ok=False, detalhe="texto vazio")
        for pedaco in dividir_no_limite(texto):
            corpo = {"recipient": {"id": id_do_usuario(lead_id)}, "message": {"text": pedaco}}
            ultimo = await self._postar(corpo)
            if not ultimo.ok:
                return ultimo
            if ultimo.id_externo:
                self.ids_enviados.append(ultimo.id_externo)
        return ultimo

    async def enviar_texto(self, lead_id: str, texto: str) -> bool:
        return (await self.enviar_texto_detalhado(lead_id, texto)).ok

    async def enviar_midia(self, lead_id: str, url: str) -> bool:
        corpo = {"recipient": {"id": id_do_usuario(lead_id)},
                 "message": {"attachment": {"type": "image", "payload": {"url": url}}}}
        resultado = await self._postar(corpo)
        if resultado.ok and resultado.id_externo:
            self.ids_enviados.append(resultado.id_externo)
        return resultado.ok

    async def responder_comentario_no_privado(self, comment_id: str, texto: str) -> ResultadoEnvio:
        """IG2: a resposta privada (uma por comentário, até 7 dias; confirmado no IG0)."""
        corpo = {"recipient": {"comment_id": str(comment_id)}, "message": {"text": dividir_no_limite(texto)[0]}}
        resultado = await self._postar(corpo)
        if resultado.ok and resultado.id_externo:
            self.ids_enviados.append(resultado.id_externo)
        return resultado

    async def responder_comentario_em_publico(self, comment_id: str, texto: str) -> ResultadoEnvio:
        """IG2: a resposta pública curta (POST /<comentário>/replies)."""
        from app.credenciais import SemCredencial, credencial_instagram
        try:
            cred = credencial_instagram(self._loja())
        except SemCredencial as erro:
            return ResultadoEnvio(ok=False, detalhe=f"sem credencial: {erro}")
        url = f"{api_url()}/{api_versao()}/{comment_id}/replies"
        return await self._postar_http(url, cred.token, {"message": texto})

    async def ler_legenda(self, media_id: str) -> str | None:
        """IG2: a legenda do post (GET /<post>?fields=caption). None se não deu para ler.
        IG0: o campo caption é confirmado só no login do Facebook."""
        from app.credenciais import SemCredencial, credencial_instagram
        try:
            cred = credencial_instagram(self._loja())
        except SemCredencial:
            return None
        url = f"{api_url()}/{api_versao()}/{media_id}"
        try:
            async with httpx.AsyncClient(timeout=15) as cliente:
                resposta = await cliente.get(url, params={"fields": "caption"},
                                             headers={"Authorization": f"Bearer {cred.token}"})
        except Exception as erro:
            _log.error(f"[Instagram][loja {self.loja_id}] legenda: conexão ({type(erro).__name__})")
            return None
        if resposta.status_code != 200:
            return None
        try:
            return str(resposta.json().get("caption") or "")
        except Exception:
            return None

    async def _postar(self, corpo: dict) -> ResultadoEnvio:
        from app.credenciais import SemCredencial, credencial_instagram
        try:
            cred = credencial_instagram(self._loja())
        except SemCredencial as erro:
            _log.info(f"[Instagram][loja {self.loja_id}] não enviado: {erro}.")
            return ResultadoEnvio(ok=False, detalhe=f"sem credencial: {erro}")
        url = f"{api_url()}/{api_versao()}/{cred.id_conta}/messages"
        return await self._postar_http(url, cred.token, corpo)


async def _postar_http(url: str, token: str, corpo: dict) -> ResultadoEnvio:
    cabecalhos = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=30) as cliente:
            resposta = await cliente.post(url, headers=cabecalhos, json=corpo)
    except Exception as erro:
        _log.error(f"[Instagram] ERRO de conexão: {type(erro).__name__}")
        return ResultadoEnvio(ok=False, detalhe=f"conexão: {type(erro).__name__}")
    if resposta.status_code == 200:
        try:
            dados = resposta.json()
        except Exception:
            dados = {}
        return ResultadoEnvio(ok=True, id_externo=str(dados.get("message_id") or dados.get("id") or ""))
    _log.error(f"[Instagram] ERRO {resposta.status_code}: {resposta.text[:300]}")
    return ResultadoEnvio(ok=False, detalhe=str(resposta.text)[:500])

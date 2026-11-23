"""
Fotos do ESTOQUE: o caminho único (Maratona Fotos, F1). Toda foto de carro entra por aqui —
envio pelo painel, link colado, demo, migração e, no futuro, CRM — e sai daqui para o Léo, o
painel e o simulador.

Preparo (preparar):
  - confere pelo CONTEÚDO que é imagem (JPEG, PNG, WebP ou HEIC do iPhone), não pelo nome;
  - recusa acima de MAX_BYTES (15 MB);
  - corrige a rotação (EXIF), reduz para no máximo LADO_MAXIMO px no lado maior;
  - grava em JPEG de boa qualidade, abaixo de ~1 MB, SEM metadados (EXIF, GPS, nada).
Guardar: nome aleatório impossível de adivinhar, dentro da pasta da loja no depósito
(app/deposito.py). O banco guarda a referência "deposito:loja-N/<nome>.jpg" (lista separada por
vírgula, a primeira é a capa, no máximo MAX_FOTOS_POR_CARRO). A referência não diz qual tomada
do depósito está ligada.
Link colado: só https, sem seguir para endereço interno da rede ou do computador, com tempo e
tamanho limite; o que vem passa pelo mesmo preparo. Falhou: FotoRecusada com a mensagem para
a loja; nada é gravado.
Fotos que o CLIENTE manda NÃO passam por aqui e nunca são guardadas (regra do L5).
"""
from __future__ import annotations

import io
import ipaddress
import re
import secrets
import socket
from urllib.parse import urljoin, urlsplit

from app import deposito as _deposito
from app.chaves import exigir_loja

MAX_BYTES = 15 * 1024 * 1024
LADO_MAXIMO = 1600
ALVO_BYTES = 1_000_000
MAX_FOTOS_POR_CARRO = 20
FORMATOS = {"JPEG", "PNG", "WEBP", "HEIF"}
PREFIXO = "deposito:"
NOME = re.compile(r"^[A-Za-z0-9_-]{20,64}\.jpg$")
TEMPO_LINK_S = 10.0
MAX_REDIRECIONAMENTOS = 3

MSG_NAO_E_IMAGEM = "Esse arquivo não é uma foto. Use uma foto em JPG, PNG, WebP ou HEIC (iPhone)."
MSG_GRANDE = "Essa foto passa de 15 MB. Escolha uma foto menor."
MSG_LINK = ("Não consegui baixar a foto desse link. Confira se o link abre a foto direto "
            "(começando com https://) ou envie o arquivo da foto.")
MSG_DEMAIS = f"Cada carro pode ter no máximo {MAX_FOTOS_POR_CARRO} fotos."
MSG_INDISPONIVEL = "Não consegui guardar a foto agora. Tente de novo em alguns minutos."
MSG_SUMIU = "Uma das fotos não existe mais. Recarregue a página e tente de novo."


class FotoRecusada(ValueError):
    """O texto vem pronto para a loja (sem termo técnico)."""


# ------------------------------------------------------------ referências

def ref_de(loja_id: int, nome: str) -> str:
    return f"{PREFIXO}loja-{exigir_loja(loja_id)}/{nome}"


def eh_do_deposito(texto: str) -> bool:
    return str(texto or "").startswith(PREFIXO)


def nome_da_ref(ref: str) -> str | None:
    """O nome do arquivo (sem a loja), ou None se a referência não for do depósito."""
    if not eh_do_deposito(ref):
        return None
    nome = ref[len(PREFIXO):].split("/", 1)[-1]
    return nome if NOME.match(nome) else None


def chave_da_ref(loja_id: int, ref: str) -> str | None:
    """A chave no depósito, só se a referência for DESTA loja; senão None."""
    texto = str(ref or "")
    if not eh_do_deposito(texto):
        return None
    chave = texto[len(PREFIXO):]
    if not chave.startswith(f"loja-{exigir_loja(loja_id)}/") or not _deposito.chave_valida(chave):
        return None
    return chave


def separar(texto) -> list[str]:
    """Texto do banco -> lista (mantém a ordem; a primeira é a capa)."""
    return [u.strip() for u in str(texto or "").split(",") if u.strip()]


def juntar(refs: list[str]) -> str:
    return ", ".join(refs)


def refs_do_carro(loja_id: int, texto) -> list[str]:
    """Só as fotos do depósito desta loja (o resto é ignorado: o Léo e o painel só usam o depósito)."""
    return [r for r in separar(texto) if chave_da_ref(loja_id, r)]


# ------------------------------------------------------------ preparo

def _abrir(dados: bytes):
    from PIL import Image, UnidentifiedImageError
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:                       # sem o pacote, HEIC é recusado como "não é foto"
        pass
    try:
        imagem = Image.open(io.BytesIO(dados))
        formato = (imagem.format or "").upper()
        imagem.load()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as erro:
        raise FotoRecusada(MSG_NAO_E_IMAGEM) from erro
    if formato not in FORMATOS:
        raise FotoRecusada(MSG_NAO_E_IMAGEM)
    return imagem


def preparar(dados: bytes) -> bytes:
    """Bytes de qualquer foto aceita -> JPEG limpo (sem metadados), girado e reduzido."""
    from PIL import Image, ImageOps
    if not dados:
        raise FotoRecusada(MSG_NAO_E_IMAGEM)
    if len(dados) > MAX_BYTES:
        raise FotoRecusada(MSG_GRANDE)
    imagem = _abrir(dados)
    imagem = ImageOps.exif_transpose(imagem)
    if imagem.mode in ("RGBA", "LA", "P"):
        imagem = imagem.convert("RGBA")
        fundo = Image.new("RGB", imagem.size, (255, 255, 255))
        fundo.paste(imagem, mask=imagem.split()[-1])
        imagem = fundo
    elif imagem.mode != "RGB":
        imagem = imagem.convert("RGB")
    imagem.thumbnail((LADO_MAXIMO, LADO_MAXIMO), Image.Resampling.LANCZOS)
    # Uma imagem NOVA, só com os pixels: nada de EXIF, GPS, ICC ou comentário vai junto.
    limpa = Image.new("RGB", imagem.size)
    limpa.paste(imagem)
    melhor = b""
    for lado in (LADO_MAXIMO, 1280, 1024, 800, 640):
        if max(limpa.size) > lado:
            limpa.thumbnail((lado, lado), Image.Resampling.LANCZOS)
        for qualidade in (85, 78, 70, 62):
            saida = io.BytesIO()
            limpa.save(saida, format="JPEG", quality=qualidade, optimize=True, progressive=True)
            melhor = saida.getvalue()
            if len(melhor) <= ALVO_BYTES:
                return melhor
    return melhor


# ------------------------------------------------------------ guardar, ler, apagar

def guardar(loja_id: int, dados: bytes) -> str:
    """Prepara e guarda no depósito. Devolve a referência para gravar no carro."""
    loja = exigir_loja(loja_id)
    pronta = preparar(dados)
    nome = secrets.token_urlsafe(24) + ".jpg"
    try:
        _deposito.deposito().guardar(f"loja-{loja}/{nome}", pronta)
    except (_deposito.FalhaNoDeposito, _deposito.DepositoMalConfigurado, OSError) as erro:
        raise FotoRecusada(MSG_INDISPONIVEL) from erro
    return ref_de(loja, nome)


def ler(loja_id: int, ref: str) -> bytes:
    chave = chave_da_ref(loja_id, ref)
    if chave is None:
        raise _deposito.FotoNaoEncontrada("foto de outra loja ou inválida")
    return _deposito.deposito().ler(chave)


def existe(loja_id: int, ref: str) -> bool:
    try:
        ler(loja_id, ref)
        return True
    except (_deposito.FotoNaoEncontrada, _deposito.FalhaNoDeposito, _deposito.DepositoMalConfigurado):
        return False


def apagar(loja_id: int, ref: str) -> bool:
    chave = chave_da_ref(loja_id, ref)
    if chave is None:
        return False
    _deposito.deposito().apagar(chave)
    return True


def endereco_publico(loja_id: int, ref: str) -> str | None:
    """Endereço https para quem está fora (WhatsApp), quando a tomada tem; senão None."""
    chave = chave_da_ref(loja_id, ref)
    if chave is None:
        return None
    try:
        return _deposito.deposito().endereco(chave)
    except _deposito.DepositoMalConfigurado:
        return None


# ------------------------------------------------------------ link colado

def _endereco_proibido(host: str) -> bool:
    """True se o nome aponta para a rede interna, o próprio computador ou endereço reservado."""
    try:
        enderecos = {info[4][0] for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    except (socket.gaierror, UnicodeError, OSError):
        return True
    if not enderecos:
        return True
    for texto in enderecos:
        ip = ipaddress.ip_address(texto.split("%")[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified or getattr(ip, "is_site_local", False)):
            return True
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped and not ip.ipv4_mapped.is_global:
            return True
    return False


def _conferir_link(url: str) -> None:
    partes = urlsplit(str(url or "").strip())
    if partes.scheme != "https" or not partes.hostname or partes.username or partes.password:
        raise FotoRecusada(MSG_LINK)
    if partes.port not in (None, 443):
        raise FotoRecusada(MSG_LINK)
    if _endereco_proibido(partes.hostname):
        raise FotoRecusada(MSG_LINK)


def _baixar_link(url: str, transporte=None) -> bytes:
    """Baixa a foto de um link https público, com tempo e tamanho limite. Segue no máximo
    MAX_REDIRECIONAMENTOS, conferindo cada destino. 'transporte' existe para os testes."""
    import httpx
    atual = str(url or "").strip()
    with httpx.Client(transport=transporte, timeout=TEMPO_LINK_S, follow_redirects=False,
                      headers={"User-Agent": "leo-painel-fotos/1.0"}) as cliente:
        for _ in range(MAX_REDIRECIONAMENTOS + 1):
            _conferir_link(atual)
            try:
                with cliente.stream("GET", atual) as r:
                    if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                        atual = urljoin(atual, r.headers["location"])
                        continue
                    if r.status_code != 200:
                        raise FotoRecusada(MSG_LINK)
                    tamanho = r.headers.get("content-length")
                    if tamanho and tamanho.isdigit() and int(tamanho) > MAX_BYTES:
                        raise FotoRecusada(MSG_GRANDE)
                    dados = bytearray()
                    for pedaco in r.iter_bytes():
                        dados.extend(pedaco)
                        if len(dados) > MAX_BYTES:
                            raise FotoRecusada(MSG_GRANDE)
                    return bytes(dados)
            except httpx.HTTPError as erro:
                raise FotoRecusada(MSG_LINK) from erro
    raise FotoRecusada(MSG_LINK)


# O nome que o resto do código usa. Os testes trocam por um falso (nunca acessam a internet).
baixar_link = _baixar_link


def guardar_de_link(loja_id: int, url: str, transporte=None) -> str:
    return guardar(loja_id, baixar_link(url, transporte=transporte))


# ------------------------------------------------------------ apoio às telas e à API

ENDERECO_API = "/api/v1/fotos/"      # a rota da API do painel que entrega a foto (tomada local)


def endereco_para_painel(loja_id: int, ref: str) -> str | None:
    """O endereço que o painel usa: o público (nuvem) ou a rota da API. None se não for desta loja."""
    if chave_da_ref(loja_id, ref) is None:
        return None
    return endereco_publico(loja_id, ref) or ENDERECO_API + nome_da_ref(ref)


def ref_do_endereco(loja_id: int, texto: str) -> str | None:
    """Endereço que o painel mostrou (rota da API ou público da nuvem) -> referência desta loja."""
    texto = str(texto or "").strip()
    if eh_do_deposito(texto):
        return texto if chave_da_ref(loja_id, texto) else None
    if texto.startswith(ENDERECO_API):
        nome = texto[len(ENDERECO_API):]
        return ref_de(loja_id, nome) if NOME.match(nome) else None
    nome = texto.rsplit("/", 1)[-1]
    if NOME.match(nome):
        ref = ref_de(loja_id, nome)
        if endereco_publico(loja_id, ref) == texto:
            return ref
    return None


def normalizar(loja_id: int, entradas: list[str], transporte=None) -> tuple[list[str], list[str]]:
    """Lista que veio da tela -> (referências na ordem, novas guardadas agora).
    Endereço de foto desta loja vira a referência; link https de fora é baixado e preparado;
    qualquer outra coisa é recusada. Se algo falhar, as novas são apagadas e FotoRecusada sobe."""
    limpas = [str(e).strip() for e in entradas if str(e or "").strip()]
    if len(limpas) > MAX_FOTOS_POR_CARRO:
        raise FotoRecusada(MSG_DEMAIS)
    refs: list[str] = []
    novas: list[str] = []
    try:
        for e in limpas:
            ref = ref_do_endereco(loja_id, e)
            if ref is not None and not existe(loja_id, ref):
                raise FotoRecusada(MSG_SUMIU)
            if ref is None:
                if not e.startswith("https://"):
                    raise FotoRecusada(MSG_LINK)
                ref = guardar_de_link(loja_id, e, transporte=transporte)
                novas.append(ref)
            refs.append(ref)
    except FotoRecusada:
        for ref in novas:
            apagar(loja_id, ref)
        raise
    return refs, novas


def _de_arquivo(texto: str) -> str | None:
    """Caminho de arquivo local (ou file:///) -> caminho, se existir; senão None."""
    from pathlib import Path
    from urllib.parse import unquote
    caminho = texto
    if texto.startswith("file://"):
        caminho = unquote(urlsplit(texto).path)
        if re.match(r"^/[A-Za-z]:/", caminho):           # file:///C:/... no Windows
            caminho = caminho[1:]
    try:
        p = Path(caminho)
        return str(p) if p.is_file() else None
    except (OSError, ValueError):
        return None


def migrar_texto(loja_id: int, texto, transporte=None) -> tuple[str, int, list[tuple[str, str]]]:
    """Fotos antigas de um carro (arquivo da demo ou link) -> depósito.
    Devolve (texto novo, quantas migraram, [(entrada, motivo)] das que falharam).
    As que falharam ficam no texto como estavam: nada é apagado."""
    saida, migradas, falhas = [], 0, []
    for entrada in separar(texto):
        if chave_da_ref(loja_id, entrada):
            saida.append(entrada)
            continue
        try:
            arquivo = _de_arquivo(entrada)
            if arquivo:
                with open(arquivo, "rb") as f:
                    saida.append(guardar(loja_id, f.read()))
            elif entrada.startswith("https://"):
                saida.append(guardar_de_link(loja_id, entrada, transporte=transporte))
            else:
                raise FotoRecusada("não é arquivo que exista neste computador nem link https")
            migradas += 1
        except FotoRecusada as erro:
            falhas.append((entrada, str(erro)))
            saida.append(entrada)
    return juntar(saida), migradas, falhas


def guardar_varias(loja_id: int, fotos: list[bytes]) -> list[str]:
    """Várias de uma vez: se uma falhar, as já guardadas são apagadas e o erro sobe."""
    feitas: list[str] = []
    try:
        for dados in fotos:
            feitas.append(guardar(loja_id, dados))
    except FotoRecusada:
        for ref in feitas:
            apagar(loja_id, ref)
        raise
    return feitas

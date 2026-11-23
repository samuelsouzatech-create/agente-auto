"""
Depósito das fotos do ESTOQUE (Maratona Fotos, F1). Uma interface só, duas "tomadas":

    FOTOS_DEPOSITO=local  (padrão) pasta fora do Git (FOTOS_PASTA, padrão <projeto>/fotos_deposito).
                          Sem endereço público: a API do painel entrega a foto por rota própria.
    FOTOS_DEPOSITO=nuvem  protocolo S3 (Cloudflare R2 e parecidos), com endereço https público.
                          Variáveis: FOTOS_NUVEM_ENDPOINT, FOTOS_NUVEM_BALDE, FOTOS_NUVEM_CHAVE_ID,
                          FOTOS_NUVEM_SEGREDO, FOTOS_NUVEM_URL_PUBLICA (https) e, se preciso,
                          FOTOS_NUVEM_REGIAO (padrão "auto"). Testado só com um falso (offline).

Só app/fotos.py chama este módulo. Nenhum outro arquivo sabe qual tomada está ligada.
A chave de cada foto é "loja-<número>/<nome aleatório>.jpg": a loja faz parte da chave.
Fotos que o CLIENTE manda nunca entram aqui (regra do L5): o depósito é só do estoque.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import os
import re
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

RAIZ = Path(__file__).resolve().parents[1]
PASTA_PADRAO = RAIZ / "fotos_deposito"
CHAVE_VALIDA = re.compile(r"^loja-[1-9][0-9]{0,9}/[A-Za-z0-9_-]{20,64}\.jpg$")
TIPO = "image/jpeg"
TEMPO_LIMITE_S = 20.0


class DepositoMalConfigurado(RuntimeError):
    """Falta variável da tomada escolhida (o texto nunca traz valor de segredo)."""


class FotoNaoEncontrada(LookupError):
    pass


class FalhaNoDeposito(RuntimeError):
    pass


def chave_valida(chave: str) -> bool:
    return bool(CHAVE_VALIDA.match(str(chave or "")))


def _exigir_chave(chave: str) -> str:
    if not chave_valida(chave):
        raise FotoNaoEncontrada("chave de foto inválida")
    return chave


class Deposito(Protocol):
    def guardar(self, chave: str, dados: bytes) -> None: ...
    def ler(self, chave: str) -> bytes: ...
    def apagar(self, chave: str) -> None: ...
    def endereco(self, chave: str) -> str | None: ...


# ------------------------------------------------------------ tomada local

class DepositoLocal:
    def __init__(self, pasta: Path):
        self.pasta = Path(pasta)

    def _arquivo(self, chave: str) -> Path:
        base = self.pasta.resolve()
        arquivo = (base / _exigir_chave(chave)).resolve()
        if base not in arquivo.parents:            # nunca sai da pasta do depósito
            raise FotoNaoEncontrada("fora do depósito")
        return arquivo

    def guardar(self, chave: str, dados: bytes) -> None:
        arquivo = self._arquivo(chave)
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        temporario = arquivo.with_suffix(".tmp")
        temporario.write_bytes(dados)
        os.replace(temporario, arquivo)

    def ler(self, chave: str) -> bytes:
        arquivo = self._arquivo(chave)
        if not arquivo.is_file():
            raise FotoNaoEncontrada("foto não existe")
        return arquivo.read_bytes()

    def apagar(self, chave: str) -> None:
        arquivo = self._arquivo(chave)
        if arquivo.is_file():
            arquivo.unlink()

    def endereco(self, chave: str) -> str | None:
        _exigir_chave(chave)
        return None                                # sem endereço público: o painel usa a rota da API


# ------------------------------------------------------------ tomada nuvem (S3)

def _hmac(chave: bytes, texto: str) -> bytes:
    return hmac.new(chave, texto.encode("utf-8"), hashlib.sha256).digest()


class DepositoNuvem:
    """S3 com assinatura AWS v4, estilo caminho (endpoint/balde/chave). Sem biblioteca extra:
    só httpx. 'transporte' existe para os testes (falso offline)."""

    def __init__(self, endpoint: str, balde: str, chave_id: str, segredo: str, url_publica: str,
                 regiao: str = "auto", transporte=None, agora=None):
        if not endpoint.startswith("https://") or not url_publica.startswith("https://"):
            raise DepositoMalConfigurado("o endpoint e o endereço público da nuvem precisam ser https")
        self.endpoint = endpoint.rstrip("/")
        self.balde = balde
        self.chave_id = chave_id
        self.segredo = segredo
        self.url_publica = url_publica.rstrip("/")
        self.regiao = regiao or "auto"
        self.transporte = transporte
        self._agora = agora

    def _assinar(self, metodo: str, chave: str, corpo: bytes) -> tuple[str, dict]:
        agora = self._agora() if self._agora else _dt.datetime.now(_dt.timezone.utc)
        data_hora = agora.strftime("%Y%m%dT%H%M%SZ")
        data = agora.strftime("%Y%m%d")
        caminho = "/" + quote(self.balde, safe="") + "/" + "/".join(quote(p, safe="") for p in chave.split("/"))
        host = self.endpoint.split("://", 1)[1]
        hash_corpo = hashlib.sha256(corpo).hexdigest()
        cabecalhos = {"host": host, "x-amz-content-sha256": hash_corpo, "x-amz-date": data_hora}
        nomes = ";".join(sorted(cabecalhos))
        canonico = "\n".join([metodo, caminho, "",
                              "".join(f"{k}:{cabecalhos[k]}\n" for k in sorted(cabecalhos)),
                              nomes, hash_corpo])
        escopo = f"{data}/{self.regiao}/s3/aws4_request"
        texto = "\n".join(["AWS4-HMAC-SHA256", data_hora, escopo,
                           hashlib.sha256(canonico.encode()).hexdigest()])
        k = _hmac(("AWS4" + self.segredo).encode(), data)
        k = _hmac(k, self.regiao)
        k = _hmac(k, "s3")
        k = _hmac(k, "aws4_request")
        assinatura = hmac.new(k, texto.encode(), hashlib.sha256).hexdigest()
        cabecalhos["authorization"] = (f"AWS4-HMAC-SHA256 Credential={self.chave_id}/{escopo}, "
                                       f"SignedHeaders={nomes}, Signature={assinatura}")
        return self.endpoint + caminho, cabecalhos

    def _pedir(self, metodo: str, chave: str, corpo: bytes = b"", extra: dict | None = None):
        import httpx
        url, cabecalhos = self._assinar(metodo, _exigir_chave(chave), corpo)
        cabecalhos.pop("host")
        cabecalhos.update(extra or {})
        try:
            with httpx.Client(transport=self.transporte, timeout=TEMPO_LIMITE_S) as cliente:
                return cliente.request(metodo, url, content=corpo or None, headers=cabecalhos)
        except httpx.HTTPError as erro:
            raise FalhaNoDeposito(f"nuvem fora do ar ({type(erro).__name__})") from None

    def guardar(self, chave: str, dados: bytes) -> None:
        r = self._pedir("PUT", chave, dados, {"content-type": TIPO})
        if r.status_code not in (200, 201):
            raise FalhaNoDeposito(f"a nuvem recusou a foto ({r.status_code})")

    def ler(self, chave: str) -> bytes:
        r = self._pedir("GET", chave)
        if r.status_code == 404:
            raise FotoNaoEncontrada("foto não existe")
        if r.status_code != 200:
            raise FalhaNoDeposito(f"a nuvem não entregou a foto ({r.status_code})")
        return r.content

    def apagar(self, chave: str) -> None:
        r = self._pedir("DELETE", chave)
        if r.status_code not in (200, 204, 404):
            raise FalhaNoDeposito(f"a nuvem não apagou a foto ({r.status_code})")

    def endereco(self, chave: str) -> str | None:
        return f"{self.url_publica}/{_exigir_chave(chave)}"


# ------------------------------------------------------------ escolha da tomada

VARIAVEIS_NUVEM = ("FOTOS_NUVEM_ENDPOINT", "FOTOS_NUVEM_BALDE", "FOTOS_NUVEM_CHAVE_ID",
                   "FOTOS_NUVEM_SEGREDO", "FOTOS_NUVEM_URL_PUBLICA")


def deposito() -> Deposito:
    """A tomada ligada (lida do ambiente a cada chamada)."""
    tomada = os.environ.get("FOTOS_DEPOSITO", "local").strip().lower() or "local"
    if tomada == "local":
        return DepositoLocal(Path(os.environ.get("FOTOS_PASTA") or PASTA_PADRAO))
    if tomada == "nuvem":
        faltam = [v for v in VARIAVEIS_NUVEM if not os.environ.get(v)]
        if faltam:
            raise DepositoMalConfigurado("faltam variáveis da nuvem: " + ", ".join(faltam))
        return DepositoNuvem(os.environ["FOTOS_NUVEM_ENDPOINT"], os.environ["FOTOS_NUVEM_BALDE"],
                             os.environ["FOTOS_NUVEM_CHAVE_ID"], os.environ["FOTOS_NUVEM_SEGREDO"],
                             os.environ["FOTOS_NUVEM_URL_PUBLICA"],
                             os.environ.get("FOTOS_NUVEM_REGIAO", "auto"))
    raise DepositoMalConfigurado("FOTOS_DEPOSITO precisa ser 'local' ou 'nuvem'")

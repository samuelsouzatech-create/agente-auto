"""
Camada de envio de e-mail (SE2, Maratona Segurança).

Quem manda e-mail (hoje: o link de criar ou redefinir senha) chama enviar_email(...). O PROVEDOR
é escolhido no .env (LEO_EMAIL_PROVEDOR):
- "arquivo" (padrão): provedor FALSO. Grava cada e-mail como um arquivo .eml na pasta
  LEO_EMAIL_PASTA (padrão logs/emails/, que nunca vai para o Git). Nada sai do computador.
- "nenhum": não envia nem grava (só conta no log que um e-mail seria enviado, sem o conteúdo).
Provedor real (Amazon SES, Resend, Brevo... ver docs/seguranca.md, SE2) entra aqui no bloco do
servidor, como mais uma classe com o mesmo método enviar().

Regras:
- O conteúdo do e-mail (que leva o link com o token) NUNCA vai para o log nem para o terminal:
  o log diz só "e-mail de <tipo> enviado" e um resumo (hash) do destinatário.
- Falha no envio nunca derruba quem chamou (o "esqueci minha senha" responde igual sempre).
"""
from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from app.log import logger as _logger

_log = _logger("email")
PASTA_PADRAO = os.path.join("logs", "emails")      # dentro da pasta de logs (app.logs.PASTA_LOGS)
REMETENTE_PADRAO = "Léo <nao-responda@leo.invalid>"


@dataclass(frozen=True)
class Email:
    para: str
    assunto: str
    texto: str
    tipo: str                 # "redefinir_senha", "criar_senha"...

    def __repr__(self) -> str:                    # o corpo (com o link) nunca aparece em log
        return f"Email(tipo={self.tipo!r}, para=***, assunto={self.assunto!r})"


def resumo_do_destinatario(email: str) -> str:
    return hashlib.sha256(str(email or "").strip().lower().encode()).hexdigest()[:12]


class ProvedorArquivo:
    """Provedor FALSO: cada e-mail vira um arquivo .eml (abre no Outlook ou no Bloco de Notas)."""
    nome = "arquivo"

    def __init__(self, pasta: str | None = None):
        from app import logs
        self.pasta = Path(pasta or os.environ.get("LEO_EMAIL_PASTA") or os.path.join(logs.PASTA_LOGS, "emails"))

    def enviar(self, email: Email) -> bool:
        mensagem = EmailMessage()
        mensagem["From"] = os.environ.get("LEO_EMAIL_REMETENTE") or REMETENTE_PADRAO
        mensagem["To"] = email.para
        mensagem["Subject"] = email.assunto
        mensagem["Date"] = formatdate(localtime=False)
        mensagem["Message-ID"] = make_msgid(domain="leo.invalid")
        mensagem.set_content(email.texto)
        self.pasta.mkdir(parents=True, exist_ok=True)
        nome = f"{formatdate(usegmt=True)[5:25].replace(' ', '_').replace(':', '')}_{email.tipo}_{secrets.token_hex(4)}.eml"
        (self.pasta / nome).write_bytes(bytes(mensagem))
        return True


class ProvedorNenhum:
    nome = "nenhum"

    def enviar(self, email: Email) -> bool:
        return False


PROVEDORES = {"arquivo": ProvedorArquivo, "nenhum": ProvedorNenhum}


def provedor():
    nome = (os.environ.get("LEO_EMAIL_PROVEDOR") or "arquivo").strip().lower()
    if nome not in PROVEDORES:
        _log.warning(f"[E-mail] Provedor desconhecido no .env ({nome[:20]}). Usando o falso (arquivo).")
        nome = "arquivo"
    return PROVEDORES[nome]()


def enviar_email(email: Email) -> bool:
    """Manda pelo provedor do .env. True se enviou. Nunca levanta erro."""
    p = provedor()
    try:
        ok = bool(p.enviar(email))
    except Exception as erro:
        _log.warning(f"[E-mail] Falha ao enviar {email.tipo} ({type(erro).__name__}) "
                     f"para {resumo_do_destinatario(email.para)}.")
        return False
    _log.info(f"[E-mail] {email.tipo} {'enviado' if ok else 'não enviado'} pelo provedor {p.nome} "
              f"para {resumo_do_destinatario(email.para)}.")
    return ok

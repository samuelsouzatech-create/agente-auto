"""
Backup do banco, CIFRADO (SE2, Maratona Segurança). Script: scripts/backup.py.

fazer_backup(): pg_dump (formato próprio do PostgreSQL, -Fc) -> cifra com a chave LEO_CHAVE_BACKUP
(Fernet: AES-128 + assinatura; sem a chave ninguém lê nem altera sem ser percebido) -> grava no
destino. O arquivo nunca fica aberto (sem cifrar) no disco.
restaurar(): decifra -> pg_restore num banco SEPARADO (nunca por cima do banco de uso sem pedir).
contagens(): quantas linhas tem cada tabela (para conferir o backup restaurado).

Onde o pg_dump roda (LEO_PG_FERRAMENTAS):
- vazio (padrão): o pg_dump do computador, se for da versão 17 ou mais nova; senão, o de dentro
  do contêiner do banco (docker exec, LEO_PG_CONTEINER, padrão agente-auto-postgres-1);
- "local": sempre o do computador;  "docker": sempre o do contêiner.
A senha do banco vai pela variável PGPASSWORD (nunca na linha de comando, que aparece na lista
de processos) e nunca em log.

Destino (LEO_BACKUP_DESTINO): "pasta" (padrão: LEO_BACKUP_PASTA, padrão backups/, fora do Git).
"r2" (Cloudflare R2) fica para o bloco do servidor: hoje responde que ainda não existe.
A chave do backup é SEPARADA da chave mestra do cofre (trocar a do cofre não perde backup antigo).
Guarde a LEO_CHAVE_BACKUP fora do servidor também: sem ela, o backup não abre.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

VERSAO_MINIMA = 17
CONTEINER_PADRAO = "agente-auto-postgres-1"
PASTA_PADRAO = "backups"
SUFIXO = ".dump.cifrado"


class ErroBackup(RuntimeError):
    """O backup ou a restauração não deu certo (a mensagem nunca tem senha)."""


# ------------------------------------------------------------ chave
def _fernet():
    from cryptography.fernet import Fernet
    chave = (os.environ.get("LEO_CHAVE_BACKUP") or "").strip()
    if not chave:
        raise ErroBackup("Falta a LEO_CHAVE_BACKUP no .env (gere com: python scripts/backup.py nova-chave).")
    try:
        return Fernet(chave.encode())
    except Exception:
        raise ErroBackup("A LEO_CHAVE_BACKUP do .env não é uma chave válida.") from None


def nova_chave() -> str:
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


def cifrar(dados: bytes) -> bytes:
    return _fernet().encrypt(dados)


def decifrar(dados: bytes) -> bytes:
    from cryptography.fernet import InvalidToken
    try:
        return _fernet().decrypt(dados)
    except InvalidToken:
        raise ErroBackup("Não consegui abrir o backup: chave errada ou arquivo alterado.") from None


# ------------------------------------------------------------ pg_dump / pg_restore
def _partes(url: str) -> dict:
    p = urlsplit(url)
    return {"usuario": unquote(p.username or ""), "senha": unquote(p.password or ""),
            "host": p.hostname or "127.0.0.1", "porta": str(p.port or 5432), "banco": p.path.lstrip("/")}


def _sem_senha(url: str) -> str:
    p = urlsplit(url)
    netloc = (p.username or "") + "@" + (p.hostname or "") + (f":{p.port}" if p.port else "")
    return urlunsplit(p._replace(netloc=netloc))


def _versao_local(ferramenta: str) -> int:
    try:
        saida = subprocess.run([ferramenta, "--version"], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return 0
    m = re.search(r"(\d+)(?:\.\d+)?", saida)
    return int(m.group(1)) if m else 0


def _modo() -> str:
    modo = (os.environ.get("LEO_PG_FERRAMENTAS") or "").strip().lower()
    if modo in ("local", "docker"):
        return modo
    local = shutil.which("pg_dump")
    return "local" if local and _versao_local(local) >= VERSAO_MINIMA else "docker"


def _rodar(ferramenta: str, url: str, argumentos: list[str], entrada: bytes | None = None) -> bytes:
    partes = _partes(url)
    ambiente = {**os.environ, "PGPASSWORD": partes["senha"]}
    conexao = ["-h", partes["host"], "-p", partes["porta"], "-U", partes["usuario"], "-d", partes["banco"]]
    if _modo() == "docker":
        conteiner = os.environ.get("LEO_PG_CONTEINER") or CONTEINER_PADRAO
        # Dentro do contêiner o banco está em 127.0.0.1:5432 (a porta do computador pode ser outra).
        conexao = ["-h", "127.0.0.1", "-p", "5432", "-U", partes["usuario"], "-d", partes["banco"]]
        comando = ["docker", "exec", "-i", "-e", "PGPASSWORD", conteiner, ferramenta, *conexao, *argumentos]
    else:
        comando = [shutil.which(ferramenta) or ferramenta, *conexao, *argumentos]
    try:
        r = subprocess.run(comando, input=entrada, capture_output=True, env=ambiente, timeout=1800)
    except FileNotFoundError:
        raise ErroBackup(f"Não achei o {ferramenta} (nem o Docker). Veja docs/seguranca.md, SE2.") from None
    if r.returncode != 0:
        erro = r.stderr.decode("utf-8", "replace").replace(partes["senha"], "***") if partes["senha"] else \
            r.stderr.decode("utf-8", "replace")
        raise ErroBackup(f"O {ferramenta} falhou: {erro.strip()[-400:]}")
    return r.stdout


def despejar(url: str) -> bytes:
    """O banco inteiro no formato próprio do PostgreSQL (sem dono e sem permissões)."""
    return _rodar("pg_dump", url, ["-Fc", "--no-owner", "--no-privileges"])


# ------------------------------------------------------------ destino
def _pasta() -> Path:
    return Path(os.environ.get("LEO_BACKUP_PASTA") or PASTA_PADRAO)


def guardar(nome: str, dados: bytes) -> str:
    destino = (os.environ.get("LEO_BACKUP_DESTINO") or "pasta").strip().lower()
    if destino == "pasta":
        pasta = _pasta()
        pasta.mkdir(parents=True, exist_ok=True)
        caminho = pasta / nome
        caminho.write_bytes(dados)
        return str(caminho)
    if destino == "r2":
        raise ErroBackup("O envio para o R2 fica para o bloco do servidor (ainda não existe).")
    raise ErroBackup(f"Destino de backup desconhecido: {destino[:20]}.")


def fazer_backup(url: str | None = None, agora: datetime | None = None) -> str:
    """Faz o backup cifrado. Devolve onde ficou."""
    url = url or os.environ.get("BANCO_URL") or ""
    if not url:
        raise ErroBackup("Falta a BANCO_URL.")
    _fernet()                                           # sem chave, nem começa
    momento = (agora or datetime.now(timezone.utc)).strftime("%Y-%m-%d_%H%M%S")
    banco = _partes(url)["banco"] or "banco"
    return guardar(f"{banco}_{momento}{SUFIXO}", cifrar(despejar(url)))


# ------------------------------------------------------------ restauração
def _mesmo_banco(a: str, b: str) -> bool:
    pa, pb = _partes(a), _partes(b)
    return (pa["host"], pa["porta"], pa["banco"]) == (pb["host"], pb["porta"], pb["banco"])


def restaurar(arquivo: str, url_destino: str, *, criar_banco: bool = True, por_cima_do_uso: bool = False) -> None:
    """Restaura o backup num banco SEPARADO (criado vazio se criar_banco). Recusa o banco de uso,
    a não ser que por_cima_do_uso=True (só pelo script, com confirmação)."""
    uso = os.environ.get("BANCO_URL") or ""
    if uso and _mesmo_banco(uso, url_destino) and not por_cima_do_uso:
        raise ErroBackup("Recusado: o destino é o banco de uso. Restaure num banco separado e confira antes.")
    dados = decifrar(Path(arquivo).read_bytes())
    if criar_banco:
        nome = _partes(url_destino)["banco"]
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", nome):
            raise ErroBackup("Nome de banco inválido (use letras minúsculas, números e _).")
        import banco
        if banco.banco_existe(url_destino):
            raise ErroBackup(f"O banco {nome} já existe. Use outro nome (a restauração não mistura dados).")
        banco.criar_banco_vazio(url_destino)
    _rodar("pg_restore", url_destino, ["--no-owner", "--no-privileges", "--exit-on-error"], entrada=dados)


def apagar_banco(url: str) -> None:
    """Para os testes e a conferência: apaga o banco restaurado (nunca o de uso)."""
    uso = os.environ.get("BANCO_URL") or ""
    if uso and _mesmo_banco(uso, url):
        raise ErroBackup("Recusado: não apago o banco de uso.")
    import banco
    banco.apagar_banco_inteiro(url)


def contagens(url: str) -> dict[str, int]:
    """Linhas de cada tabela do banco (esquema public)."""
    import banco
    return banco.contagens_das_tabelas(url)

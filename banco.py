"""
Banco do Léo: PostgreSQL 17 (Maratona Postgres, PG1). Este arquivo é a ÚNICA camada de conexão:
nenhum outro arquivo abre conexão por conta própria.

- O endereço vem da variável BANCO_URL (no .env). Nunca escreva senha no código.
- conectar() empresta uma conexão de um "pool" (um grupo de conexões abertas e reaproveitadas);
  close() devolve a conexão ao pool.
- A conexão se comporta como a do SQLite que o código sempre usou, para nada mais precisar
  mudar de uma vez:
    * "?" nos comandos vira o marcador do PostgreSQL; "INSERT OR IGNORE" vira
      "ON CONFLICT DO NOTHING"; LIKE não diferencia maiúsculas (como no SQLite);
      CURRENT_TIMESTAMP vira agora_texto() (texto UTC, igual ao SQLite);
    * cada linha responde por posição (linha[0]) e por nome (linha["modelo"]);
    * lastrowid devolve o id da linha inserida;
    * soma e média voltam como número comum (int ou float), não Decimal.
- Migrações: arquivos em migracoes/ com o número na frente (020_base_postgres.sql é a base,
  equivalente às migrações 1 a 20 do SQLite). As aplicadas ficam na tabela migracoes_aplicadas.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import threading
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import ClientCursor, sql as _sql
from psycopg.adapt import Dumper, Loader
from psycopg_pool import ConnectionPool

try:                                    # o .env do projeto (BANCO_URL); nunca sobrescreve o ambiente
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:                     # pragma: no cover
    pass

PASTA_MIGRACOES = Path(__file__).resolve().parent / "migracoes"
VERSAO_SCHEMA = 20                       # a base do PostgreSQL equivale à v20 do SQLite
POOL_MIN = int(os.getenv("BANCO_POOL_MIN", "1"))
POOL_MAX = int(os.getenv("BANCO_POOL_MAX", "10"))
ESPERA_POOL_S = float(os.getenv("BANCO_POOL_ESPERA_S", "30"))

# Erros que o resto do código pode tratar sem conhecer o psycopg.
Erro = psycopg.Error
ErroDeIntegridade = psycopg.errors.IntegrityError
ErroOperacional = psycopg.OperationalError


class BancoNaoConfigurado(RuntimeError):
    """Falta a BANCO_URL no .env."""


# ---------------------------------------------------------------- qual banco

_url_em_uso: str | None = None           # trocado pelos testes e pela bancada (apontar_para)


def url_do_banco() -> str:
    url = _url_em_uso or os.getenv("BANCO_URL")
    if not url:
        raise BancoNaoConfigurado(
            "Falta a BANCO_URL no .env (veja .env.example). Suba o banco com: docker compose up -d")
    return url


def apontar_para(url: str | None) -> None:
    """Usa outro banco (testes e bancada). None volta para a BANCO_URL."""
    global _url_em_uso
    _url_em_uso = url


def nome_do_banco(url: str) -> str:
    return urlsplit(url).path.lstrip("/")


def trocar_nome_do_banco(url: str, nome: str) -> str:
    partes = urlsplit(url)
    return urlunsplit(partes._replace(path="/" + nome))


def url_sem_senha(url: str) -> str:
    """Para mensagens e logs: nunca mostrar a senha."""
    partes = urlsplit(url)
    if partes.password:
        netloc = partes.netloc.replace(":" + partes.password + "@", ":***@")
        partes = partes._replace(netloc=netloc)
    return urlunsplit(partes)


# ---------------------------------------------------------------- tipos (igual ao SQLite)

class _TextoLiteral(Dumper):
    """Manda o valor como texto entre aspas: o PostgreSQL decide o tipo pelo lugar onde ele
    entra (coluna de texto ou de número), como o SQLite fazia."""
    oid = 0

    def dump(self, obj):
        return self._texto(obj).encode()

    def quote(self, obj):
        return b"'" + self._texto(obj).replace("'", "''").encode() + b"'"

    def _texto(self, obj) -> str:
        return str(obj)


class _InteiroComoTexto(_TextoLiteral):
    pass


class _BoolComoInteiro(_TextoLiteral):
    def _texto(self, obj) -> str:            # True/False viram 1/0, como no SQLite
        return "1" if obj else "0"


class _DataHoraComoTexto(_TextoLiteral):
    def _texto(self, obj) -> str:            # mesmo texto que o sqlite3 gravava
        return obj.isoformat(" ")


class _DataComoTexto(_TextoLiteral):
    def _texto(self, obj) -> str:
        return obj.isoformat()


class _NumeroComum(Loader):
    """numeric (resultado de SUM, AVG...) volta como int ou float, como no SQLite."""

    def load(self, data):
        texto = bytes(data).decode()
        if "." in texto or "e" in texto.lower() or texto in ("NaN", "Infinity", "-Infinity"):
            return float(texto)
        return int(texto)


def _configurar(conexao: psycopg.Connection) -> None:
    adaptadores = conexao.adapters
    adaptadores.register_dumper(bool, _BoolComoInteiro)
    adaptadores.register_dumper(int, _InteiroComoTexto)
    adaptadores.register_dumper(_dt.datetime, _DataHoraComoTexto)
    adaptadores.register_dumper(_dt.date, _DataComoTexto)
    adaptadores.register_loader("numeric", _NumeroComum)


# ---------------------------------------------------------------- tradução do SQL

_PALAVRA = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _pedacos(texto: str):
    """Separa o comando em (é_código, pedaço): textos entre aspas e comentários não são mexidos."""
    i, n, inicio = 0, len(texto), 0
    while i < n:
        c = texto[i]
        if c in ("'", '"'):
            if i > inicio:
                yield True, texto[inicio:i]
            j = i + 1
            while j < n:
                if texto[j] == c:
                    if j + 1 < n and texto[j + 1] == c:
                        j += 2
                        continue
                    break
                j += 1
            yield False, texto[i:j + 1]
            i = inicio = j + 1
            continue
        if c == "-" and texto.startswith("--", i):
            if i > inicio:
                yield True, texto[inicio:i]
            j = texto.find("\n", i)
            j = n if j == -1 else j
            yield False, texto[i:j]
            i = inicio = j
            continue
        i += 1
    if inicio < n:
        yield True, texto[inicio:]


_INSERT_IGNORE = re.compile(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\b", re.I)
_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)
_LIKE = re.compile(r"\bLIKE\b", re.I)
_AGORA = re.compile(r"\bCURRENT_TIMESTAMP\b", re.I)
# "a IS ?" do SQLite (igual, valendo também para vazio) = "IS NOT DISTINCT FROM" no PostgreSQL.
_IS_NOT_MARCADOR = re.compile(r"\bIS\s+NOT\s+%s", re.I)
_IS_MARCADOR = re.compile(r"\bIS\s+%s", re.I)
_RETURNING = re.compile(r"\bRETURNING\b", re.I)
_PROIBIDO = re.compile(r"^\s*(PRAGMA|INSERT\s+OR\s+REPLACE|BEGIN\s+IMMEDIATE)\b", re.I)


@lru_cache(maxsize=4096)
def traduzir(comando: str, com_parametros: bool) -> tuple[str, str | None]:
    """Devolve (comando para o PostgreSQL, tabela do INSERT ou None)."""
    if _PROIBIDO.match(comando):
        raise NotImplementedError(f"Comando só do SQLite, não traduzido: {comando.strip()[:60]!r}")
    ignorar = bool(_INSERT_IGNORE.match(comando))
    if ignorar:
        comando = _INSERT_IGNORE.sub("INSERT INTO", comando, count=1)
    partes = []
    for e_codigo, pedaco in _pedacos(comando):
        if e_codigo:
            if com_parametros:
                pedaco = pedaco.replace("%", "%%").replace("?", "%s")
            pedaco = _LIKE.sub("ILIKE", pedaco)
            if com_parametros:
                pedaco = _IS_NOT_MARCADOR.sub("IS DISTINCT FROM %s", pedaco)
                pedaco = _IS_MARCADOR.sub("IS NOT DISTINCT FROM %s", pedaco)
            pedaco = _AGORA.sub("agora_texto()", pedaco)
        elif com_parametros:
            pedaco = pedaco.replace("%", "%%")
        partes.append(pedaco)
    traduzido = "".join(partes).rstrip().rstrip(";")
    if ignorar:
        traduzido += " ON CONFLICT DO NOTHING"
    m = _INSERT.match(traduzido)
    tabela = m.group(1).lower() if m and not _RETURNING.search(traduzido) else None
    return traduzido, tabela


# ---------------------------------------------------------------- linhas

class Linha(tuple):
    """Uma linha do resultado: linha[0] ou linha["coluna"], dict(linha), linha.keys()."""
    __slots__ = ()
    _nomes: tuple = ()
    _posicao: dict = {}

    def __getitem__(self, chave):
        if isinstance(chave, str):
            try:
                return tuple.__getitem__(self, self._posicao[chave])
            except KeyError:
                raise IndexError(f"Coluna inexistente: {chave}") from None
        return tuple.__getitem__(self, chave)

    def keys(self):
        return list(self._nomes)


@lru_cache(maxsize=1024)
def _classe_da_linha(nomes: tuple) -> type:
    return type("Linha", (Linha,), {"__slots__": (), "_nomes": nomes,
                                    "_posicao": {n: i for i, n in enumerate(nomes)}})


def _fabrica_de_linhas(cursor):
    if not cursor.description:
        return tuple
    classe = _classe_da_linha(tuple(c.name for c in cursor.description))
    return classe


# ---------------------------------------------------------------- pool

_pools: dict[str, ConnectionPool] = {}
_trava_pools = threading.Lock()
_tabelas_com_id: dict[str, frozenset] = {}


def _pool(url: str) -> ConnectionPool:
    pool = _pools.get(url)
    if pool is None:
        with _trava_pools:
            pool = _pools.get(url)
            if pool is None:
                pool = ConnectionPool(
                    url, min_size=POOL_MIN, max_size=POOL_MAX, timeout=ESPERA_POOL_S,
                    kwargs={"cursor_factory": ClientCursor, "autocommit": False},
                    configure=_configurar, open=True, name="leo")
                _pools[url] = pool
    return pool


_pools_memoria: dict[str, ConnectionPool] = {}
POOL_MEMORIA_MAX = int(os.getenv("BANCO_POOL_MEMORIA_MAX", "4"))


def pool_da_memoria(url: str | None = None) -> ConnectionPool:
    """PG2: pool só da memória das conversas (biblioteca do LangGraph, PostgresSaver), que pede
    conexões do jeito dela (autocommit e linhas como dicionário). Mesmo banco da BANCO_URL."""
    from psycopg.rows import dict_row
    url = url or url_do_banco()
    pool = _pools_memoria.get(url)
    if pool is None:
        with _trava_pools:
            pool = _pools_memoria.get(url)
            if pool is None:
                pool = ConnectionPool(
                    url, min_size=1, max_size=POOL_MEMORIA_MAX, timeout=ESPERA_POOL_S,
                    kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                    open=True, name="leo-memoria")
                _pools_memoria[url] = pool
    return pool


def fechar_pools() -> None:
    """Fecha todas as conexões abertas (fim do processo, testes)."""
    with _trava_pools:
        for pool in [*_pools.values(), *_pools_memoria.values()]:
            pool.close()
        _pools.clear()
        _pools_memoria.clear()
        _tabelas_com_id.clear()


def fechar_pool(url: str) -> None:
    with _trava_pools:
        pools = [_pools.pop(url, None), _pools_memoria.pop(url, None)]
        _tabelas_com_id.pop(url, None)
    for pool in pools:
        if pool:
            pool.close()


def criar_banco_vazio(url_base: str, nome: str) -> str:
    """Apaga (se existir) e cria um banco vazio com esse nome, no mesmo servidor da url_base.
    Para a bancada e os testes. Devolve o endereço do banco novo."""
    url = trocar_nome_do_banco(url_base, nome)
    apagar_banco(url)
    with psycopg.connect(trocar_nome_do_banco(url_base, "postgres"), autocommit=True) as c:
        c.execute(_sql.SQL("CREATE DATABASE {}").format(_sql.Identifier(nome)))
    return url


def apagar_banco(url: str) -> None:
    """Apaga um banco inteiro. Recusa o banco de uso (BANCO_URL)."""
    nome = nome_do_banco(url)
    uso = os.getenv("BANCO_URL")
    if uso and nome == nome_do_banco(uso):
        raise RuntimeError("Recusado: este é o banco de uso.")
    fechar_pool(url)
    with psycopg.connect(trocar_nome_do_banco(url, "postgres"), autocommit=True) as c:
        c.execute(_sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(_sql.Identifier(nome)))


def estado_inicial() -> dict:
    """Fotografia do que as migrações deixam gravado (a loja 1). Testes e bancada."""
    conexao = conectar()
    try:
        semente = {}
        for tabela in tabelas():
            cur = conexao.execute(f"SELECT * FROM {tabela}")
            semente[tabela] = ([d.name for d in cur.description], [tuple(l) for l in cur.fetchall()])
        return semente
    finally:
        conexao.close()


def voltar_ao_estado_inicial(semente: dict) -> None:
    """Esvazia todas as tabelas e grava de novo a fotografia do estado_inicial().
    Recusa o banco de uso (BANCO_URL). Testes e bancada."""
    uso = os.getenv("BANCO_URL")
    if uso and nome_do_banco(url_do_banco()) == nome_do_banco(uso):
        raise RuntimeError("Recusado: este é o banco de uso.")
    conexao = conectar()
    bruta = conexao._bruta
    try:
        # DELETE (e não TRUNCATE): em tabela pequena é muito mais rápido, e os testes limpam o
        # banco antes de CADA teste. Os contadores de id voltam ao começo no mesmo comando.
        com_id = _ids_por_tabela(conexao._url, bruta)
        comandos = [f"DELETE FROM {t}" for t in semente]
        comandos += [f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), 1, false)"
                     for t in semente if t in com_id]
        bruta.execute("; ".join(comandos))
        for tabela, (nomes, linhas) in semente.items():
            if not linhas:
                continue
            marcas = ", ".join(["%s"] * len(nomes))
            with bruta.cursor() as cur:
                cur.executemany(f"INSERT INTO {tabela} ({', '.join(nomes)}) VALUES ({marcas})", linhas)
            if "id" in nomes:                    # o próximo id automático vem depois da semente
                bruta.execute(f"SELECT setval(pg_get_serial_sequence('{tabela}', 'id'), "
                              f"(SELECT MAX(id) FROM {tabela}))")
        conexao.commit()
    finally:
        conexao.close()


def estatisticas_do_pool() -> dict:
    """Números do pool da BANCO_URL em uso (teste de carga, PG3)."""
    pool = _pools.get(url_do_banco())
    return dict(pool.get_stats()) if pool else {}


def _ids_por_tabela(url: str, conexao: psycopg.Connection) -> frozenset:
    tabelas = _tabelas_com_id.get(url)
    if tabelas is None:
        with conexao.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND column_name = 'id' "
                        "AND is_identity = 'YES'")
            tabelas = frozenset(r[0] for r in cur.fetchall())
        _tabelas_com_id[url] = tabelas
    return tabelas


# ---------------------------------------------------------------- conexão

# DK3 (Maratona Docker): transação só quando precisa. Antes, TODA conexão abria uma transação
# (BEGIN) no primeiro comando e desfazia (ROLLBACK) ao fechar, até para uma leitura simples:
# 3 idas ao banco por consulta. Um turno faz ~18 consultas, cada uma na sua conexão: eram ~50
# idas só de BEGIN/ROLLBACK. Agora a leitura simples roda sem transação; o primeiro comando que
# não é leitura simples (escrita, SET LOCAL, SELECT ... FOR UPDATE, função que mexe em
# sequência ou trava de transação) abre a transação, e daí em diante tudo é como antes (commit
# confirma, rollback ou fechar sem commit desfaz). No READ COMMITTED (o padrão do PostgreSQL,
# usado aqui) cada comando já enxerga o que estava confirmado na hora: a leitura fora da
# transação vê a mesma coisa que veria dentro. Conexão somente leitura continua como antes.
_LEITURA_SIMPLES = re.compile(r"^\s*(SELECT|WITH|EXPLAIN|SHOW)\b", re.I)
_PRECISA_DE_TRANSACAO = re.compile(
    r"\bFOR\s+(UPDATE|SHARE|NO\s+KEY|KEY)\b|\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE)\b"
    r"|advisory_xact|nextval|setval|\bINTO\b", re.I)


def leitura_simples(comando: str) -> bool:
    """True se o comando só lê e não precisa de transação (DK3)."""
    return bool(_LEITURA_SIMPLES.match(comando)) and not _PRECISA_DE_TRANSACAO.search(comando)


class Cursor:
    def __init__(self, conexao: "Conexao"):
        self._conexao = conexao
        self._cur = conexao._bruta.cursor(row_factory=_fabrica_de_linhas)
        self.lastrowid = None
        self._pendente = None             # linha do RETURNING id, guardada até alguém pedir

    def execute(self, comando: str, parametros=()):
        if self._conexao._rastro is not None:
            self._conexao._rastro(comando)
        tem = bool(parametros)
        traduzido, tabela = traduzir(comando, tem)
        self._conexao._antes_do_comando(traduzido)
        if tabela and tabela in self._conexao._tabelas_com_id():
            traduzido += " RETURNING id"
        self._cur.execute(traduzido, parametros if tem else None)
        self.lastrowid = None
        if tabela and tabela in self._conexao._tabelas_com_id():
            linha = self._cur.fetchone() if self._cur.rowcount else None
            self.lastrowid = linha[0] if linha else None
        return self

    def executemany(self, comando: str, sequencia):
        traduzido, _ = traduzir(comando, True)
        self._conexao._antes_do_comando(traduzido)
        self._cur.executemany(traduzido, list(sequencia))
        return self

    def fetchone(self):
        if self._cur.description is None or self.lastrowid is not None:
            return None
        return self._cur.fetchone()

    def fetchall(self):
        if self._cur.description is None or self.lastrowid is not None:
            return []
        return self._cur.fetchall()

    def fetchmany(self, tamanho: int = 1):
        if self._cur.description is None:
            return []
        return self._cur.fetchmany(tamanho)

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def close(self) -> None:
        self._cur.close()


class Conexao:
    """Conexão emprestada do pool, com o mesmo jeito de usar da conexão do SQLite."""

    def __init__(self, url: str, *, somente_leitura: bool = False):
        self._url = url
        self._pool = _pool(url)
        self._bruta = self._pool.getconn()
        self._fechada = False
        self._rastro = None
        # DK3: sem transação até precisar (ver leitura_simples). Somente leitura: como antes.
        self._sob_demanda = not somente_leitura
        if somente_leitura:
            self._bruta.execute("SET TRANSACTION READ ONLY")
        else:
            self._bruta.autocommit = True

    def _antes_do_comando(self, comando: str) -> None:
        """DK3: abre a transação no primeiro comando que não é leitura simples."""
        if self._sob_demanda and self._bruta.autocommit and not leitura_simples(comando):
            self._bruta.autocommit = False          # o psycopg manda o BEGIN junto deste comando

    def _transacao_terminou(self) -> None:
        if self._sob_demanda and not self._bruta.autocommit:
            self._bruta.autocommit = True

    def _tabelas_com_id(self) -> frozenset:
        return _ids_por_tabela(self._url, self._bruta)

    def cursor(self) -> Cursor:
        return Cursor(self)

    def set_trace_callback(self, funcao) -> None:
        """Chama funcao(comando) a cada comando desta conexão (testes que contam consultas)."""
        self._rastro = funcao

    def execute(self, comando: str, parametros=()) -> Cursor:
        return Cursor(self).execute(comando, parametros)

    def executemany(self, comando: str, sequencia) -> Cursor:
        return Cursor(self).executemany(comando, sequencia)

    def commit(self) -> None:
        if self._bruta.autocommit:                 # DK3: nada aberto, nada a confirmar
            return
        self._bruta.commit()
        self._transacao_terminou()

    def rollback(self) -> None:
        if self._bruta.autocommit:
            return
        self._bruta.rollback()
        self._transacao_terminou()

    @property
    def in_transaction(self) -> bool:
        return self._bruta.info.transaction_status != psycopg.pq.TransactionStatus.IDLE

    def close(self) -> None:
        if self._fechada:
            return
        self._fechada = True
        try:
            if self._bruta.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                self._bruta.rollback()          # como o SQLite: fechar sem commit desfaz
        except psycopg.Error:
            pass
        try:
            if self._bruta.autocommit:              # DK3: devolve no jeito de sempre
                self._bruta.autocommit = False
        except psycopg.Error:
            pass
        self._pool.putconn(self._bruta)

    def __enter__(self):
        return self

    def __exit__(self, tipo, valor, rastro):
        # Como o sqlite3: o "with" confirma (ou desfaz, se deu erro), mas não fecha.
        if tipo is None:
            self.commit()
        else:
            self.rollback()
        return False

    def __del__(self):                        # conexão esquecida aberta volta para o pool
        try:
            self.close()
        except Exception:
            pass


def conectar(*, somente_leitura: bool = False) -> Conexao:
    """Empresta uma conexão do banco. Sempre feche (close) no fim.
    somente_leitura=True: a conexão recusa qualquer escrita (telas que só consultam)."""
    return Conexao(url_do_banco(), somente_leitura=somente_leitura)


# ---------------------------------------------------------------- migrações

_TABELA_MIGRACOES = """
CREATE TABLE IF NOT EXISTS migracoes_aplicadas (
    versao INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    aplicada_em TEXT NOT NULL DEFAULT to_char(clock_timestamp() AT TIME ZONE 'UTC',
                                              'YYYY-MM-DD HH24:MI:SS')
)
"""
_TRAVA_MIGRACAO = 7_243_001             # número fixo da trava (duas cópias não migram juntas)


def migracoes_disponiveis() -> list[tuple[int, str, Path]]:
    """(número, nome, arquivo) em ordem. Número repetido é erro: nunca se reaproveita número."""
    lista = []
    for arquivo in sorted(PASTA_MIGRACOES.glob("*.sql")):
        m = re.match(r"^(\d+)_(.+)\.sql$", arquivo.name)
        if not m:
            continue
        lista.append((int(m.group(1)), m.group(2), arquivo))
    numeros = [n for n, _, _ in lista]
    if len(numeros) != len(set(numeros)):
        raise RuntimeError("Duas migrações com o mesmo número em migracoes/.")
    if 21 in numeros and not any("instagram" in nome for n, nome, _ in lista if n == 21):
        raise RuntimeError("A migração 21 é reservada ao Instagram.")
    return lista


def versao_schema(conexao=None) -> int:
    propria = conexao is None
    conexao = conexao or conectar()
    try:
        existe = conexao.execute("SELECT to_regclass('migracoes_aplicadas') IS NOT NULL").fetchone()[0]
        if not existe:
            return 0
        return int(conexao.execute("SELECT COALESCE(MAX(versao), 0) FROM migracoes_aplicadas")
                   .fetchone()[0])
    finally:
        if propria:
            conexao.close()


def migrar() -> list[int]:
    """Aplica, em ordem, as migrações que ainda não rodaram. Cada uma é tudo ou nada.
    Devolve os números aplicados agora."""
    aplicadas_agora = []
    with psycopg.connect(url_do_banco(), autocommit=True) as bruta:
        bruta.execute("SELECT pg_advisory_lock(%s)", (_TRAVA_MIGRACAO,))
        try:
            bruta.execute(_TABELA_MIGRACOES)
            feitas = {r[0] for r in bruta.execute("SELECT versao FROM migracoes_aplicadas")}
            for numero, nome, arquivo in migracoes_disponiveis():
                if numero in feitas:
                    continue
                with bruta.transaction():
                    bruta.execute(arquivo.read_text(encoding="utf-8"))
                    bruta.execute("INSERT INTO migracoes_aplicadas (versao, nome) VALUES (%s, %s)",
                                  (numero, nome))
                aplicadas_agora.append(numero)
            _preparar_tabelas_da_memoria(bruta)
        finally:
            bruta.execute("SELECT pg_advisory_unlock(%s)", (_TRAVA_MIGRACAO,))
    _tabelas_com_id.clear()
    return aplicadas_agora


def _preparar_tabelas_da_memoria(bruta: psycopg.Connection) -> None:
    """PG2: as tabelas da memória das conversas (checkpoints...) são da biblioteca do LangGraph,
    que tem a própria lista de mudanças (tabela checkpoint_migrations). Não usam a nossa
    numeração: são criadas e atualizadas pelo setup() dela, aqui, junto com as nossas."""
    from psycopg.rows import dict_row
    from langgraph.checkpoint.postgres import PostgresSaver
    bruta.row_factory = dict_row
    try:
        PostgresSaver(bruta).setup()
    finally:
        bruta.row_factory = psycopg.rows.tuple_row


def criar_tabelas():
    """Cria as tabelas (se ainda não existem) e aplica as migrações."""
    migrar()
    print(f"Tabelas criadas/migradas (schema v{VERSAO_SCHEMA}).")


def tabelas() -> list[str]:
    """Nomes das tabelas do Léo (sem a de controle das migrações)."""
    conexao = conectar()
    try:
        return [r[0] for r in conexao.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' "
            "AND table_name <> 'migracoes_aplicadas' ORDER BY table_name").fetchall()]
    finally:
        conexao.close()


def colunas(tabela: str) -> list[str]:
    conexao = conectar()
    try:
        return [r[0] for r in conexao.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ? ORDER BY ordinal_position",
            (tabela,)).fetchall()]
    finally:
        conexao.close()


def acertar_contadores(conexao=None) -> None:
    """Depois de gravar linhas com id escolhido (importação, demo), o próximo id automático
    continua depois do maior que existe."""
    propria = conexao is None
    conexao = conexao or conectar()
    try:
        for (tabela,) in conexao.execute(
                "SELECT table_name FROM information_schema.columns WHERE table_schema = "
                "current_schema() AND column_name = 'id' AND is_identity = 'YES'").fetchall():
            nome = _sql.Identifier(tabela)
            conexao._bruta.execute(_sql.SQL(
                "SELECT setval(pg_get_serial_sequence({t}, 'id'), "
                "GREATEST((SELECT COALESCE(MAX(id), 0) FROM {n}), 1), "
                "(SELECT COUNT(*) > 0 FROM {n}))").format(t=_sql.Literal(tabela), n=nome))
        if propria:
            conexao.commit()
    finally:
        if propria:
            conexao.close()


def popular_estoque_exemplo():
    """Insere alguns carros de exemplo, só se a tabela estiver vazia."""
    conexao = conectar()
    try:
        total = conexao.execute("SELECT COUNT(*) FROM estoque").fetchone()[0]
        if total > 0:
            print(f"Estoque já tem {total} carros. Nada a inserir.")
            return
        carros = [
            ("Honda", "Civic", 2019, 48000, "Branco", "Automático", 98000.00, "disponivel"),
            ("Fiat", "Doblò", 2016, 110000, "Prata", "Manual", 52000.00, "disponivel"),
            ("Toyota", "Corolla", 2021, 32000, "Preto", "Automático", 135000.00, "disponivel"),
            ("Volkswagen", "Gol", 2018, 65000, "Branco", "Manual", 42000.00, "disponivel"),
            ("Chevrolet", "Onix", 2020, 40000, "Vermelho", "Automático", 68000.00, "disponivel"),
            ("Hyundai", "HB20", 2019, 55000, "Prata", "Manual", 54000.00, "disponivel"),
            ("Honda", "Civic", 2017, 72000, "Preto", "Automático", 82000.00, "vendido"),
        ]
        conexao.executemany(
            "INSERT INTO estoque (marca, modelo, ano, km, cor, cambio, preco, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", carros)
        conexao.commit()
        print(f"Inseridos {len(carros)} carros de exemplo.")
    finally:
        conexao.close()


if __name__ == "__main__":
    criar_tabelas()
    popular_estoque_exemplo()

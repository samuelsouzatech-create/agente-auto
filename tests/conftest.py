"""
Configuração compartilhada dos testes (pytest).

A fixture 'banco_temporario' é autouse: antes de CADA teste, o banco de TESTE
(PostgreSQL, Maratona Postgres PG1) fica limpo, só com o que as migrações criam
(a loja 1). O banco de teste é separado do banco de uso: nome da BANCO_URL com
"_teste" no fim (ou BANCO_URL_TESTE), apagado e criado de novo a cada rodada.
Também limpa o cache de configuração das lojas e manda o log estruturado
para uma pasta temporária (os testes nunca sujam logs/ de verdade).

A fixture 'ator_de_teste' (P6) também é autouse: todo teste roda com um
ator definido ("Teste", operador, painel). Os testes de "sem ator falha"
tiram o ator de propósito com app.ator.sem_ator().

Fase 3 (parecer do analista): app/core/agent.py cria o cliente do Gemini ao
ser importado e quebrava a suíte num computador sem GOOGLE_API_KEY. Aqui o
.env é lido primeiro (a chave real continua valendo para os testes de API,
-m api) e, só se não houver chave nenhuma, entra uma chave falsa. Os testes
normais usam LLM falso e nunca chamam o Gemini.
"""
import os
import sys

import pytest
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

load_dotenv()
if not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = "chave-falsa-so-para-testes"

import banco
from app import ator, lojas, logs, permissoes


def url_do_banco_de_teste() -> str:
    """Nunca o banco de uso: BANCO_URL_TESTE, ou o nome da BANCO_URL terminado em _teste."""
    url = os.environ.get("BANCO_URL_TESTE")
    uso = os.environ.get("BANCO_URL")
    if not url:
        if not uso:
            pytest.exit("Falta a BANCO_URL no .env (veja .env.example) e o banco ligado "
                        "(docker compose up -d).", returncode=4)
        url = banco.trocar_nome_do_banco(uso, banco.nome_do_banco(uso) + "_teste")
    nome = banco.nome_do_banco(url)
    if not nome.endswith("_teste") or (uso and nome == banco.nome_do_banco(uso)):
        pytest.exit("O banco de teste precisa ter um nome terminado em _teste e diferente do "
                    "banco de uso.", returncode=4)
    return url


@pytest.fixture(scope="session", autouse=True)
def banco_de_teste():
    """Uma vez por rodada: apaga e cria de novo o banco de teste, aplica as migrações e
    guarda o que elas deixam gravado (a loja 1), para cada teste começar igual."""
    import psycopg
    from psycopg import sql
    url = url_do_banco_de_teste()
    nome = banco.nome_do_banco(url)
    try:
        with psycopg.connect(banco.trocar_nome_do_banco(url, "postgres"), autocommit=True) as c:
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(nome)))
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nome)))
    except psycopg.OperationalError:
        pytest.exit("Não consegui falar com o PostgreSQL. Ele está ligado? (docker compose up -d)",
                    returncode=4)
    with psycopg.connect(url, autocommit=True) as c:      # só o banco de TESTE: mais rápido
        c.execute(sql.SQL("ALTER DATABASE {} SET synchronous_commit = off").format(sql.Identifier(nome)))
    banco.apontar_para(url)
    banco.migrar()
    _SEMENTE.update(banco.estado_inicial())
    yield url
    banco.fechar_pools()
    banco.apontar_para(None)


_SEMENTE: dict = {}


def limpar_banco() -> None:
    """Deixa o banco de teste como as migrações deixam (só a loja 1)."""
    banco.voltar_ao_estado_inicial(_SEMENTE)


@pytest.fixture(autouse=True)
def banco_limpo(banco_de_teste, monkeypatch, tmp_path):
    """Cada teste roda contra o banco de teste limpo, com todas as tabelas. Separado do
    banco_temporario porque alguns arquivos antigos redefinem aquele; este vale sempre."""
    banco.apontar_para(banco_de_teste)
    monkeypatch.setattr(logs, "PASTA_LOGS", str(tmp_path / "logs"))
    lojas.limpar_cache()
    limpar_banco()
    yield banco_de_teste
    banco.apontar_para(banco_de_teste)
    lojas.limpar_cache()


@pytest.fixture(autouse=True)
def banco_temporario(banco_limpo):
    """Endereço do banco de teste (os testes antigos recebiam o caminho do arquivo .db)."""
    yield banco_limpo


@pytest.fixture(autouse=True)
def deposito_de_fotos_temporario(monkeypatch, tmp_path_factory):
    """Maratona Fotos: TODO teste tem o próprio depósito de fotos (tomada local, pasta
    temporária) e nunca acessa a internet. Fica separado do banco_temporario porque alguns
    arquivos antigos redefinem aquela preparação; esta vale sempre."""
    monkeypatch.setenv("FOTOS_DEPOSITO", "local")
    monkeypatch.setenv("FOTOS_PASTA", str(tmp_path_factory.mktemp("fotos_deposito")))
    from app import fotos as _fotos

    def _baixar_falso(url, transporte=None):
        # Domínio ".example" devolve uma foto falsa; qualquer outro é link que não abre.
        # (O baixador de verdade é testado à parte: app.fotos._baixar_link com transporte falso.)
        from urllib.parse import urlsplit
        partes = urlsplit(str(url))
        if partes.scheme == "https" and (partes.hostname or "").endswith(".example"):
            return _foto_de_teste()
        raise _fotos.FotoRecusada(_fotos.MSG_LINK)

    monkeypatch.setattr(_fotos, "baixar_link", _baixar_falso)
    yield


@pytest.fixture(autouse=True)
def ator_de_teste():
    """Todo teste tem um autor; assim os testes antigos não precisam mudar."""
    with ator.como("Teste", "operador", "painel"):
        yield


# S5: a trava "loja No ar, operador só vê" (app/permissoes.py) vale em TODO
# teste. Exceção: estes arquivos, escritos antes do S5, usam o operador como
# autor genérico na loja 1 (que está No ar). Neles a trava fica desligada para
# continuarem provando o que já provavam. A lista SÓ DIMINUI (catraca, como no
# P0): tests/test_s5_ver_como.py falha se um arquivo novo entrar aqui.
ANTES_DO_S5 = {
    "test_etapa1_bloco3.py",
    "test_etapa1_bloco4.py",
    "test_etapa1_bloco7.py",
    "test_etapa1_bloco7b.py",
    "test_etapa2_bloco5.py",
    "test_fase_3_handoff.py",
    "test_p2_venda_unica.py",
    "test_p4_painel_leitura.py",
    "test_p5_bloqueios.py",
    "test_p6b_acoes.py",
    "test_p6c_handoff_config.py",
    "test_p6d_leitura.py",
    "test_revisao_etapa1.py",
    "test_s3_registro.py",
    "test_separar_painel.py",
}


@pytest.fixture(autouse=True)
def trava_do_s5(request, monkeypatch):
    """Desliga a trava só nos arquivos antigos da lista acima."""
    if request.node.path.name in ANTES_DO_S5:
        monkeypatch.setattr(permissoes, "_loja_no_ar", lambda loja_id: False)
    yield


def _foto_de_teste() -> bytes:
    """Uma foto PNG pequena (Maratona Fotos), para os testes que colam link de foto."""
    import io
    from PIL import Image
    saida = io.BytesIO()
    Image.new("RGB", (64, 48), (30, 120, 200)).save(saida, format="PNG")
    return saida.getvalue()

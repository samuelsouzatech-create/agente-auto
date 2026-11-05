"""
Configuração compartilhada dos testes (pytest).

A fixture 'banco_temporario' é autouse: antes de CADA teste, aponta o banco
para um arquivo .db temporário, cria as tabelas e aplica as migrações.
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
import tempfile

import pytest
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

load_dotenv()
if not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = "chave-falsa-so-para-testes"

import banco
from banco import criar_tabelas
from app import ator, lojas, logs, permissoes


@pytest.fixture(autouse=True)
def banco_temporario(monkeypatch, tmp_path):
    """Cada teste roda contra um banco limpo e isolado, com todas as tabelas."""
    fd, caminho = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(banco, "CAMINHO_BANCO", caminho)
    monkeypatch.setattr(logs, "PASTA_LOGS", str(tmp_path / "logs"))
    lojas.limpar_cache()
    criar_tabelas()
    yield caminho
    lojas.limpar_cache()
    if os.path.exists(caminho):
        os.remove(caminho)


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

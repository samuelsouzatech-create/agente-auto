"""
Ajustes do parecer da Fase 3 (offline, banco temporário do conftest).

1. "Mudar modo de envio" (P6) deixa rastro: o modo de envio é a chave
   envio_real.<tipo> da loja. app/modo_envio.py só LÊ; a mudança passa
   sempre por app.lojas.salvar_config (ação salvar_configuracao do
   Registro, histórico próprio em config_historico). Só o operador muda.
2. Os testes não dependem de chave do Gemini de verdade (tests/conftest.py).
"""
import os

import pytest

from app import ator
from app.lojas import (
    CHAVES_DO_OPERADOR, TIPOS_ENVIO, SemPermissao,
    carregar_loja, criar_loja, historico_config, salvar_config,
)
from app.modo_envio import situacao
from app.registro import ACOES_RELEVANTES, HISTORICO_PROPRIO


def test_modo_de_envio_so_muda_por_salvar_config():
    assert ACOES_RELEVANTES["salvar_configuracao"] == "app.lojas.salvar_config"
    assert HISTORICO_PROPRIO["salvar_configuracao"] == "config_historico"
    for tipo in TIPOS_ENVIO:
        assert f"envio_real.{tipo}" in CHAVES_DO_OPERADOR


def test_operador_liga_envio_real_e_fica_no_historico(monkeypatch):
    monkeypatch.delenv("REMARKETING_ENVIO_REAL", raising=False)
    loja_id = criar_loja("Loja Modo Envio")
    assert situacao(carregar_loja(loja_id), "remarketing") == "teste"

    salvar_config(loja_id, {"envio_real.remarketing": True}, "Teste", papel="operador")
    loja = carregar_loja(loja_id)
    assert situacao(loja, "remarketing") == "teste_servidor"

    linhas = [h for h in historico_config(loja_id) if h["chave"] == "envio_real.remarketing"]
    assert len(linhas) == 1
    assert linhas[0]["usuario"] == "Teste"
    assert linhas[0]["valor_antigo"] == "false"
    assert linhas[0]["valor_novo"] == "true"

    # Com a chave do servidor ligada, loja nova (em teste) continua sem envio real.
    monkeypatch.setenv("REMARKETING_ENVIO_REAL", "1")
    assert situacao(loja, "remarketing") == "loja_em_teste"


def test_cliente_nao_liga_envio_real():
    loja_id = criar_loja("Loja Cliente")
    with ator.como("Ana", "cliente", "painel", loja_id):
        with pytest.raises(SemPermissao):
            salvar_config(loja_id, {"envio_real.remarketing": True}, "Ana", papel="operador")
    assert carregar_loja(loja_id).get("envio_real.remarketing") is False
    assert historico_config(loja_id) == []


def test_testes_tem_chave_mesmo_sem_env():
    assert os.environ.get("GOOGLE_API_KEY")

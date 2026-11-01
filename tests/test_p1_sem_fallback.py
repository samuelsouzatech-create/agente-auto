"""
P1 (Plano Mestre): fim do fallback para a loja 1.
Mensagem de canal sem cadastro não vai para loja nenhuma, e nenhuma loja
(nem a 1) envia sem canal cadastrado.
"""
import json
import os
import tempfile

import pytest

import banco
from banco import criar_tabelas


@pytest.fixture
def banco_temporario(monkeypatch):
    fd, caminho = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(banco, "CAMINHO_BANCO", caminho)
    criar_tabelas()
    yield caminho
    if os.path.exists(caminho):
        os.remove(caminho)


def _loja_b():
    from app.lojas import criar_loja
    return criar_loja("Loja B", "veiculos")


def test_sem_nenhum_canal_cadastrado_nao_cai_na_loja_1(banco_temporario):
    from app.canais import resolver_loja
    assert resolver_loja("whatsapp", "999") is None
    assert resolver_loja("telegram", "999") is None


def test_id_vazio_nao_resolve(banco_temporario):
    from app.canais import resolver_loja
    assert resolver_loja("whatsapp", "") is None
    assert resolver_loja("whatsapp", None) is None


def test_dois_canais_da_mesma_loja_continuam_funcionando(banco_temporario):
    from app.canais import cadastrar_canal, resolver_loja
    cadastrar_canal(1, "telegram", "111")
    cadastrar_canal(1, "telegram", "222")
    assert resolver_loja("telegram", "111") == 1
    assert resolver_loja("telegram", "222") == 1


def test_canal_desativado_nao_cai_em_outra_loja(banco_temporario):
    from app.canais import cadastrar_canal, desativar_canal, resolver_loja
    loja_b = _loja_b()
    cadastrar_canal(1, "telegram", "111")
    cadastrar_canal(loja_b, "telegram", "222")
    desativar_canal("telegram", "222")
    assert resolver_loja("telegram", "222") is None
    assert resolver_loja("telegram", "111") == 1


def test_loja_1_sem_canal_nao_usa_o_env_para_whatsapp(banco_temporario, monkeypatch):
    from app import config
    from app.credenciais import SemCredencial, credencial_whatsapp
    monkeypatch.setattr(config, "WHATSAPP_PHONE_NUMBER_ID", "123")
    monkeypatch.setattr(config, "WHATSAPP_TOKEN", "token-do-env")
    with pytest.raises(SemCredencial):
        credencial_whatsapp(1)


def test_loja_1_sem_canal_nao_usa_o_env_para_telegram(banco_temporario, monkeypatch):
    from app import config
    from app.credenciais import SemCredencial, token_telegram
    monkeypatch.setattr(config, "TELEGRAM_TOKEN", "555:abc")
    with pytest.raises(SemCredencial):
        token_telegram(1)


def test_loja_1_com_canal_cadastrado_envia(banco_temporario, monkeypatch):
    from app import config
    from app.canais import cadastrar_canal
    from app.credenciais import token_telegram
    monkeypatch.setattr(config, "TELEGRAM_TOKEN", "555:abc")
    cadastrar_canal(1, "telegram", "555")
    assert token_telegram(1) == "555:abc"


def test_loja_padrao_nao_existe_mais():
    import app.chaves as chaves
    assert not hasattr(chaves, "LOJA_PADRAO")


def test_canal_sem_cadastro_vai_para_o_log(tmp_path, monkeypatch):
    from app import logs
    monkeypatch.setattr(logs, "PASTA_LOGS", str(tmp_path))
    assert logs.registrar_canal_desconhecido("whatsapp", "999")
    linha = json.loads((tmp_path / logs.ARQUIVO_RECUSADAS).read_text(encoding="utf-8").strip())
    assert (linha["evento"], linha["tipo_canal"], linha["id_externo"]) == (
        "canal_sem_cadastro", "whatsapp", "999")

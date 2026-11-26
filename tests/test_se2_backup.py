"""
SE2 (Maratona Segurança), item 2: backup cifrado e restauração. Teste DE VERDADE: pg_dump do banco
de teste, restaura num banco SEPARADO e confere as contagens de TODAS as tabelas.
Precisa do pg_dump 17 (no computador ou dentro do contêiner do banco; no GitHub, instalado no fluxo).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import banco
from app import backup
from banco import conectar


@pytest.fixture
def ambiente(monkeypatch, tmp_path):
    monkeypatch.setenv("LEO_CHAVE_BACKUP", backup.nova_chave())
    monkeypatch.setenv("LEO_BACKUP_PASTA", str(tmp_path / "backups"))
    monkeypatch.setenv("LEO_BACKUP_DESTINO", "pasta")
    url = banco.url_do_banco()
    destino = banco.trocar_nome_do_banco(url, banco.nome_do_banco(url) + "_restaurado")
    backup.apagar_banco(destino)
    yield url, destino
    banco.fechar_pools()
    backup.apagar_banco(destino)


def _dados(loja):
    c = conectar()
    for i in range(5):
        c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo) VALUES (?, ?, 'whatsapp', 'cliente', ?)",
                  (f"5581900000{i:03d}", loja, f"mensagem {i} com acento: ção"))
    c.execute("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) "
              "VALUES (?, 'Honda', 'Civic', 2019, 50000, 'Prata', 'Automático', 98000, 'disponivel')", (loja,))
    c.commit()
    c.close()


def test_backup_restaurado_tem_as_mesmas_contagens_em_todas_as_tabelas(ambiente):
    url, destino = ambiente
    from app.lojas import criar_loja
    _dados(1)
    _dados(criar_loja("Loja B Backup"))
    banco.fechar_pools()                               # o pg_dump vê tudo o que foi confirmado
    arquivo = backup.fazer_backup(url)
    assert Path(arquivo).exists() and arquivo.endswith(backup.SUFIXO)
    bruto = Path(arquivo).read_bytes()
    assert b"PGDMP" not in bruto and "mensagem 0".encode() not in bruto     # cifrado: não se lê nada
    backup.restaurar(arquivo, destino)
    origem, copia = backup.contagens(url), backup.contagens(destino)
    assert origem == copia
    assert copia["mensagens"] == 10 and copia["estoque"] == 2 and len(copia) > 30


def test_chave_errada_nao_abre_o_backup(ambiente, monkeypatch):
    url, destino = ambiente
    arquivo = backup.fazer_backup(url)
    monkeypatch.setenv("LEO_CHAVE_BACKUP", backup.nova_chave())
    with pytest.raises(backup.ErroBackup, match="chave errada"):
        backup.restaurar(arquivo, destino)


def test_arquivo_alterado_nao_abre(ambiente):
    url, destino = ambiente
    arquivo = Path(backup.fazer_backup(url))
    dados = bytearray(arquivo.read_bytes())
    dados[len(dados) // 2] ^= 1
    arquivo.write_bytes(bytes(dados))
    with pytest.raises(backup.ErroBackup):
        backup.restaurar(str(arquivo), destino)


def test_sem_chave_nem_comeca(ambiente, monkeypatch):
    url, _ = ambiente
    monkeypatch.delenv("LEO_CHAVE_BACKUP")
    with pytest.raises(backup.ErroBackup, match="LEO_CHAVE_BACKUP"):
        backup.fazer_backup(url)
    assert not list(Path(os.environ["LEO_BACKUP_PASTA"]).glob("*")) if Path(os.environ["LEO_BACKUP_PASTA"]).exists() else True


def test_nunca_restaura_por_cima_do_banco_de_uso(ambiente, monkeypatch):
    url, _ = ambiente
    arquivo = backup.fazer_backup(url)
    monkeypatch.setenv("BANCO_URL", url)
    with pytest.raises(backup.ErroBackup, match="banco de uso"):
        backup.restaurar(arquivo, url)
    with pytest.raises(backup.ErroBackup, match="banco de uso"):
        backup.apagar_banco(url)


def test_nao_mistura_com_banco_que_ja_existe(ambiente):
    url, destino = ambiente
    arquivo = backup.fazer_backup(url)
    backup.restaurar(arquivo, destino)
    with pytest.raises(backup.ErroBackup, match="já existe"):
        backup.restaurar(arquivo, destino)


def test_destino_r2_fica_para_o_servidor(ambiente, monkeypatch):
    url, _ = ambiente
    monkeypatch.setenv("LEO_BACKUP_DESTINO", "r2")
    with pytest.raises(backup.ErroBackup, match="servidor"):
        backup.fazer_backup(url)


def test_erro_nunca_mostra_a_senha(ambiente, monkeypatch):
    url, _ = ambiente
    senha = backup._partes(url)["senha"]
    ruim = url.replace("/" + banco.nome_do_banco(url), "/banco_que_nao_existe_se2")
    with pytest.raises(backup.ErroBackup) as erro:
        backup.fazer_backup(ruim)
    assert not senha or senha not in str(erro.value)


def test_backups_fora_do_git():
    raiz = Path(__file__).resolve().parent.parent
    assert "backups/" in (raiz / ".gitignore").read_text(encoding="utf-8").splitlines()

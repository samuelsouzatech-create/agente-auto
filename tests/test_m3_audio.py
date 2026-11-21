"""
M3: áudio do cliente na bancada, pelo mesmo caminho de transcrição dos canais. OFFLINE
(transcritor e LLM falsos), duas lojas.
"""
import asyncio
import os
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from app.custos import Uso


def _ler(sql, parametros=()):
    conexao = banco.conectar()
    try:
        return [dict(l) for l in conexao.execute(sql, parametros).fetchall()]
    finally:
        conexao.close()


def transcritor(texto, audio=300):
    vistos = []

    def _t(bytes_audio, mime):
        vistos.append((len(bytes_audio), mime))
        return (texto, Uso(40, 15, audio) if texto is not None else Uso())
    _t.vistos = vistos
    return _t


# ------------------------------------------------------------ caminho único (app)

def test_transcrever_do_cliente_registra_custo_so_na_loja_certa():
    from app.api.receber_audio import transcrever_do_cliente
    t = transcritor("quanto tá o Corolla?")
    texto, uso = transcrever_do_cliente(1, "c1", "telegram", b"abc", "audio/ogg", transcritor=t)
    assert texto == "quanto tá o Corolla?" and uso.tokens_audio == 300 and t.vistos == [(3, "audio/ogg")]
    linhas = _ler("SELECT loja_id, lead_id, tipo FROM uso_custos WHERE tipo = 'transcricao'")
    assert linhas == [{"loja_id": 1, "lead_id": "c1", "tipo": "transcricao"}]
    assert _ler("SELECT id FROM uso_custos WHERE loja_id = 2") == []


def test_transcricao_vazia_nao_registra_custo():
    from app.api.receber_audio import transcrever_do_cliente
    texto, uso = transcrever_do_cliente(2, "c2", "telegram", b"x", "audio/ogg", transcritor=transcritor(None))
    assert texto is None and uso.vazio
    assert _ler("SELECT id FROM uso_custos WHERE tipo = 'transcricao'") == []


def test_telegram_usa_o_caminho_unico():
    from pathlib import Path
    fonte = (Path(__file__).resolve().parents[1] / "app" / "api" / "telegram_bot.py").read_text(encoding="utf-8")
    assert "transcrever_do_cliente" in fonte and "transcrever_bytes_com_uso" not in fonte


# ------------------------------------------------------------ bancada

@pytest.fixture
def bancada(monkeypatch, tmp_path):
    from scripts import rodar_bancada as rb
    monkeypatch.setattr(rb, "_PASTA_TEMP", tmp_path / "bancada")
    (tmp_path / "bancada").mkdir()
    monkeypatch.setattr(rb, "RAIZ", tmp_path)
    (tmp_path / "audios").mkdir()
    (tmp_path / "audios" / "fala.ogg").write_bytes(b"OggS-falso")
    return rb


class Grafo:
    def __init__(self):
        self.recebeu = []

    def invoke(self, entrada, config=None):
        self.recebeu.append(entrada["messages"][0].content)
        return {"messages": [HumanMessage(content=entrada["messages"][0].content),
                             AIMessage(content=f"Resposta {len(self.recebeu)}.")]}



def _ler_roteiro(rb, tmp_path, conteudo):
    caminho = tmp_path / "audio_teste.yaml"
    caminho.write_text(conteudo, encoding="utf-8")
    return rb.ler_roteiro(caminho)


def test_bancada_audio_vai_como_texto_e_custo_entra(bancada, tmp_path):
    rb = bancada
    roteiro = _ler_roteiro(rb, tmp_path, "nome: audio_teste\naudio: audios/fala.ogg\nfalas:\n  - e aceita troca?\n")
    grafo, t = Grafo(), transcritor("quanto tá o Corolla?", audio=2_000_000)
    rodada = asyncio.run(rb.rodar([roteiro], grafo, teto=10.0, transcritor=t))
    res = rodada.resultados[0]
    assert grafo.recebeu == ["quanto tá o Corolla?", "e aceita troca?"]
    assert t.vistos == [(len(b"OggS-falso"), "audio/ogg")]
    assert res.transcricoes == ["quanto tá o Corolla?"] and res.tokens_audio == 2_000_000
    assert rodada.gasto_usd >= 2 * rb.PRECO_AUDIO_USD_MILHAO          # o áudio entra no gasto
    assert res.turnos[0].fala.startswith("[áudio: fala.ogg] transcrição:")
    relatorio = rb.montar_relatorio(rodada, "modelo-falso")
    assert "transcrição do áudio: 2000000 tokens de áudio" in relatorio
    # A transcrição vira mensagem do cliente; o áudio não é guardado.
    conteudos = [l["conteudo"] for l in _ler("SELECT conteudo FROM mensagens WHERE direcao = 'cliente' ORDER BY id")]
    assert conteudos[0] == "quanto tá o Corolla?"


def test_bancada_audio_ausente_vira_aviso_sem_gastar(bancada, tmp_path):
    rb = bancada
    roteiro = _ler_roteiro(rb, tmp_path, "nome: audio_teste\naudio: audios/nao_existe.ogg\n")
    grafo, t = Grafo(), transcritor("nada")
    rodada = asyncio.run(rb.rodar([roteiro], grafo, teto=10.0, transcritor=t))
    res = rodada.resultados[0]
    assert any(a.startswith(rb.AUDIO_AUSENTE) for a in res.avisos) and res.status == rb.AVISO
    assert grafo.recebeu == [] and t.vistos == []


def test_bancada_audio_inaudivel_resposta_fixa_sem_ia(bancada, tmp_path):
    rb = bancada
    from app.core.turno import MENSAGEM_AUDIO_FALHOU
    roteiro = _ler_roteiro(rb, tmp_path, "nome: audio_teste\naudio: audios/fala.ogg\n")
    grafo = Grafo()
    rodada = asyncio.run(rb.rodar([roteiro], grafo, teto=10.0, transcritor=transcritor(None)))
    res = rodada.resultados[0]
    assert grafo.recebeu == []
    assert res.turnos[0].bolhas and MENSAGEM_AUDIO_FALHOU.split(".")[0] in " ".join(res.turnos[0].bolhas)
    assert "(transcrição vazia)" in res.turnos[0].fala


def test_roteiros_de_audio_existem():
    from scripts import rodar_bancada as rb
    nomes = {r["nome"]: r for r in rb.carregar_roteiros() if r.get("audio")}
    assert set(nomes) == {"audio_pergunta_preco", "audio_troca", "audio_desconto", "audio_inaudivel"}
    assert all(r["audio"].startswith("bancada/audios/") for r in nomes.values())

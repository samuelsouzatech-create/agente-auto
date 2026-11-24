"""
L5: foto do cliente. Offline: leitor de imagem falso e LLM falso, duas lojas.
  - carro: descrição vai ao Léo, chamado de avaliação, troca anotada, nunca valor;
  - anúncio: o Léo recebe o carro do anúncio (sem preço) para consultar o estoque;
  - documento: nada lido nem guardado, resposta fixa e chamado;
  - pessoa: o Léo é avisado para não comentar; sem legenda: perguntar;
  - a imagem nunca é guardada; a descrição tem no máximo 200 letras;
  - leitura falhou: resposta fixa + chamado.
"""
import asyncio
import base64

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import banco
from app import imagens, lojas
from app.custos import Uso
from app.imagens import ANUNCIO, CARRO, DOCUMENTO, OUTRO, LeituraImagem

LOJA_A, LOJA_B = 1, 2
LEAD = "5581955554444"
FOTO = b"\x89PNG-bytes-da-foto"


def _sql(sql, parametros=()):
    conexao = banco.conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


def _ler(sql, parametros=()):
    conexao = banco.conectar()
    try:
        return [dict(l) for l in conexao.execute(sql, parametros).fetchall()]
    finally:
        conexao.close()


@pytest.fixture
def duas_lojas():
    for loja_id in (LOJA_A, LOJA_B):
        if not _ler("SELECT id FROM lojas WHERE id = ?", (loja_id,)):
            _sql("INSERT INTO lojas (id, nome, segmento, config) VALUES (?, ?, 'veiculos', '{}')",
                 (loja_id, f"Loja {loja_id}"))
    _sql("INSERT INTO usuarios (loja_id, nome, papel, contato_whatsapp) VALUES (1, 'Carlos', 'dono', '5581999990001')")
    lojas.limpar_cache()


def leitor(tipo, descricao="", tem_pessoa=False, ok=True):
    chamadas = []

    def ler(imagem, mime):
        chamadas.append((imagem, mime))
        return LeituraImagem(ok=ok, tipo=tipo, descricao=descricao, tem_pessoa=tem_pessoa,
                             uso=Uso(300, 40))
    ler.chamadas = chamadas
    return ler


class GrafoFalso:
    def __init__(self, resposta="Que carro bonito! Um vendedor avalia pessoalmente."):
        self.resposta = resposta
        self.entradas = []

    def invoke(self, entrada, config=None):
        self.entradas.append(entrada["messages"][0].content)
        return {"messages": [HumanMessage(content=entrada["messages"][0].content),
                             AIMessage(content=self.resposta)]}


def _foto(loja_id, ler, legenda="", grafo=None, lead=LEAD):
    from app.core.turno import executar_turno_imagem
    return asyncio.run(executar_turno_imagem(loja_id, "simulador", lead, FOTO, "image/png", legenda,
                                             grafo=grafo or GrafoFalso(), leitor=ler))


def _motivos(loja_id, lead=LEAD):
    return [h["motivo"] for h in _ler("SELECT motivo FROM handoffs WHERE loja_id = ? AND lead_id = ?",
                                      (loja_id, lead))]


def _mensagens(lead=LEAD):
    return _ler("SELECT direcao, conteudo, tipo FROM mensagens WHERE lead_id = ? ORDER BY id", (lead,))


def _nada_da_foto_no_banco():
    for tabela in ("mensagens", "handoffs", "trocas", "uso_custos"):
        conexao = banco.conectar()
        try:
            for linha in conexao.execute(f"SELECT * FROM {tabela}").fetchall():
                assert all(not isinstance(v, bytes) for v in tuple(linha))
                assert all("PNG-bytes" not in str(v) for v in tuple(linha))
        finally:
            conexao.close()


# --------------------------------------------------------------- carro

def test_foto_de_carro_vai_ao_leo_com_chamado_de_avaliacao(duas_lojas):
    grafo = GrafoFalso()
    r = _foto(LOJA_A, leitor(CARRO, "Gol prata, risco na porta"), "quanto vocês dão nele?", grafo)
    assert grafo.entradas[0] == ("[Foto do cliente: carro DELE (não é do estoque). O que aparece: "
                                 "Gol prata, risco na porta]\nquanto vocês dão nele?")
    assert r.handoff_aberto and r.uso_imagem == Uso(300, 40)
    assert _motivos(LOJA_A) == ['Avaliação: cliente mandou foto do carro. '
                                'Pergunta do cliente: "quanto vocês dão nele?"']
    assert _motivos(LOJA_B) == []
    assert _mensagens()[0]["tipo"] == "imagem"
    _nada_da_foto_no_banco()


def test_foto_de_carro_anota_na_troca(duas_lojas):
    from segmentos.veiculos.registrar_troca import gravar_troca
    gravar_troca(LOJA_A, LEAD, "Gol", 2015, 120000, "conservado")
    gravar_troca(LOJA_B, LEAD, "Uno", 2010, 0, "")
    _foto(LOJA_A, leitor(CARRO, "Gol prata, risco na porta"))
    trocas = {t["loja_id"]: t["estado"] for t in _ler("SELECT loja_id, estado FROM trocas")}
    assert trocas[LOJA_A] == "conservado | foto recebida: Gol prata, risco na porta"
    assert trocas[LOJA_B] == ""                       # a troca da outra loja não muda


def test_foto_de_carro_com_chamado_aberto_soma_o_motivo(duas_lojas):
    from tools import acionar_handoff
    acionar_handoff.func(motivo="quer troca", resumo="r", lead_id=LEAD, loja_id=LOJA_A)
    _foto(LOJA_A, leitor(CARRO, "Gol prata"))
    assert _motivos(LOJA_A) == ["quer troca · Avaliação: cliente mandou foto do carro."]


def test_prompt_proibe_valor_pela_foto():
    from app.core.montagem import PASTA_PROMPTS, base_do_ramo
    from tests.prompt_de_referencia import _loja
    # SG1: os trechos de carro do base.md vêm do pacote do ramo; o base de uma loja de carros:
    base = base_do_ramo((PASTA_PROMPTS / "base.md").read_text(encoding="utf-8"), _loja({}))
    assert "NUNCA dê valor nem faixa de preço pela foto" in base
    assert "Print de anúncio: procure o carro com consultar_estoque" in base
    assert "Pessoa na foto: não comente" in base
    assert '"[Sem legenda]": pergunte com o que pode ajudar' in base


# --------------------------------------------------------------- anúncio, pessoa, sem legenda

def test_print_de_anuncio_vai_ao_leo_sem_preco(duas_lojas):
    grafo = GrafoFalso("Temos um Civic 2019 no estoque!")
    _foto(LOJA_A, leitor(ANUNCIO, "Honda Civic 2019"), "vocês têm esse?", grafo)
    assert grafo.entradas[0].startswith("[Foto do cliente: print de anúncio. Carro do anúncio: Honda Civic 2019]")
    assert _motivos(LOJA_A) == []                     # anúncio não abre chamado sozinho


def test_pessoa_na_foto_e_sem_legenda(duas_lojas):
    grafo = GrafoFalso("Oi! Com o que posso te ajudar?")
    _foto(LOJA_A, leitor(OUTRO, "uma praia", tem_pessoa=True), "", grafo)
    assert grafo.entradas[0] == ("[Foto do cliente: uma praia] [Tem pessoa na foto: não comente.]\n"
                                 "[Sem legenda]")


# --------------------------------------------------------------- documento

def test_documento_nao_passa_pelo_leo_nao_guarda_nada_e_abre_chamado(duas_lojas):
    from app.core.turno import MENSAGEM_DOCUMENTO
    grafo = GrafoFalso()
    r = _foto(LOJA_A, leitor(DOCUMENTO, ""), "segue minha CNH 123.456.789-00", grafo)
    assert r.texto == MENSAGEM_DOCUMENTO and r.handoff_aberto
    assert grafo.entradas == []                       # o Léo (IA) nem é chamado
    assert _motivos(LOJA_A) == ["Cliente mandou documento (nenhum dado foi lido nem guardado)."]
    assert [m["conteudo"] for m in _mensagens()] == ["[documento]", MENSAGEM_DOCUMENTO]
    assert "123" not in str(_ler("SELECT * FROM mensagens")) + str(_ler("SELECT * FROM handoffs"))
    _nada_da_foto_no_banco()


@pytest.mark.parametrize("resposta,tipo,descricao", [
    ('{"tipo": "documento", "descricao": "CNH de João, CPF 123.456.789-00"}', DOCUMENTO, ""),
    ('{"tipo": "outro", "descricao": "papel com 123.456.789-00"}', DOCUMENTO, ""),
    ('{"tipo": "carro", "descricao": "Gol prata, vale uns R$ 30.000 ou 30 mil"}', CARRO, "Gol prata, vale uns ou"),
    ('{"tipo": "anuncio", "descricao": "Civic 2019 por R$ 98.000, tel (81) 99999-8888"}', ANUNCIO, "Civic 2019 por tel"),
])
def test_interpretar_limpa_dados(resposta, tipo, descricao):
    leitura = imagens.interpretar(resposta)
    assert leitura.ok and leitura.tipo == tipo and leitura.descricao == descricao


def test_descricao_no_maximo_200_letras():
    leitura = imagens.interpretar('{"tipo": "carro", "descricao": "' + "a" * 500 + '"}')
    assert len(leitura.descricao) == 200


@pytest.mark.parametrize("resposta", ["", "não sei", '{"tipo": "gato"}', "{quebrado"])
def test_resposta_ruim_da_ia_e_falha(resposta):
    assert not imagens.interpretar(resposta).ok


# --------------------------------------------------------------- falha, equipe, vendedor no comando

def test_leitura_falhou_resposta_fixa_e_chamado(duas_lojas):
    from app.core.turno import MENSAGEM_IMAGEM_FALHOU
    grafo = GrafoFalso()
    r = _foto(LOJA_A, leitor(OUTRO, ok=False), "olha isso", grafo)
    assert r.texto == MENSAGEM_IMAGEM_FALHOU and "por texto" in r.texto and r.handoff_aberto
    assert grafo.entradas == []
    assert _motivos(LOJA_A) == ["Cliente mandou uma foto que não consegui ver."]


def test_ler_imagem_nunca_quebra(monkeypatch):
    import google.genai as genai

    def explode(*a, **k):
        raise RuntimeError("sem rede")

    monkeypatch.setattr(genai, "Client", explode)
    assert imagens.ler_imagem(FOTO, "image/png").ok is False


def test_dono_mandando_foto_nao_gasta_leitura(duas_lojas):
    from app.core.turno import MENSAGEM_EQUIPE_SO_TEXTO
    ler = leitor(CARRO, "x")
    r = _foto(LOJA_A, ler, lead="5581999990001")
    assert r.texto == MENSAGEM_EQUIPE_SO_TEXTO and ler.chamadas == []
    assert _mensagens("5581999990001") == []


def test_vendedor_no_comando_foto_nao_e_lida(duas_lojas):
    from tools import acionar_handoff
    acionar_handoff.func(motivo="m", resumo="r", lead_id=LEAD, loja_id=LOJA_A)
    _sql("UPDATE handoffs SET estado = 'humano_assumiu' WHERE lead_id = ?", (LEAD,))
    ler = leitor(CARRO, "x")
    r = _foto(LOJA_A, ler)
    assert r.silenciado and ler.chamadas == []
    assert [m["conteudo"] for m in _mensagens()] == ["[foto]"]


def test_custo_da_leitura_vai_para_uso_custos(duas_lojas):
    _foto(LOJA_A, leitor(OUTRO, "uma praia"), "oi")
    tipos = [l["tipo"] for l in _ler("SELECT tipo FROM uso_custos WHERE loja_id = 1")]
    assert "imagem" in tipos


# --------------------------------------------------------------- canais

def test_whatsapp_le_foto_com_legenda():
    from app.channels.whatsapp import CanalWhatsApp
    payload = {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "123"},
        "messages": [{"id": "wamid.1", "from": LEAD, "type": "image", "timestamp": "1",
                      "image": {"id": "MID", "mime_type": "image/jpeg", "caption": " tem desse? "}}]}}]}]}
    [e] = CanalWhatsApp().ler_webhook(payload)
    assert (e.tipo, e.id_midia, e.mime, e.texto) == ("imagem", "MID", "image/jpeg", "tem desse?")


def test_simulador_le_foto_em_base64():
    from app.channels.simulador import CanalSimulador
    [e] = CanalSimulador().ler_webhook({"lead_id": "x", "imagem_base64": base64.b64encode(FOTO).decode(),
                                        "mime": "image/png"})
    assert (e.tipo, e.conteudo, e.mime, e.texto) == ("imagem", FOTO, "image/png", "")
    assert CanalSimulador().ler_webhook({"lead_id": "x", "imagem_base64": "%%%"}) == []

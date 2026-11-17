"""
B1: testes OFFLINE da bancada (scripts/rodar_bancada.py). Sem Gemini: o
grafo é falso. Provam que a bancada lê os YAML, usa banco temporário (nunca
o loja.db), aborta se algo tenta enviar de verdade, respeita o teto e
aplica as regras do PENDENTE.
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from scripts import rodar_bancada as rb

RAIZ = Path(__file__).resolve().parents[1]


class GrafoFalso:
    """Responde por uma função: responder(texto, loja_id, lead_id) -> lista de mensagens."""

    def __init__(self, responder=None, tokens=(1000, 100)):
        self.responder = responder or (lambda texto, loja_id, lead_id: [AIMessage(content="Oi! Como posso ajudar?")])
        self.tokens = tokens
        self.chamadas = []

    def invoke(self, entrada, config=None):
        texto = entrada["messages"][0].content
        self.chamadas.append(texto)
        novas = self.responder(texto, entrada["loja_id"], entrada["lead_id"])
        entrada_t, saida_t = self.tokens
        for m in novas:
            if isinstance(m, AIMessage):
                m.usage_metadata = {"input_tokens": entrada_t, "output_tokens": saida_t,
                                    "total_tokens": entrada_t + saida_t}
        return {"messages": [HumanMessage(content=texto), *novas]}


def roteiro(**campos):
    base = {"nome": "teste", "falas": ["oi"]}
    base.update(campos)
    return rb.validar_roteiro(base, "teste")


def rodar(roteiros, grafo, teto=1.0):
    return asyncio.run(rb.rodar(roteiros, grafo, teto=teto))


@pytest.fixture(autouse=True)
def pasta_temporaria_da_bancada(monkeypatch, tmp_path):
    monkeypatch.setattr(rb, "_PASTA_TEMP", tmp_path / "bancada")
    (tmp_path / "bancada").mkdir()


# ------------------------------------------------------------------ YAML

def test_os_10_roteiros_iniciais_carregam():
    roteiros = rb.carregar_roteiros()
    assert len(roteiros) == 10
    pendentes = {r["nome"]: r["pendente"] for r in roteiros if r["pendente"]}
    assert pendentes == {"troca_com_km": "L1", "sem_resposta_no_estoque": "L2",
                         "endereco_e_horario": "L2", "recado_do_dono": "L3",
                         "falso_dono_pede_desconto": "L3", "foto_do_carro": "L5"}
    longa = next(r for r in roteiros if r["nome"] == "conversa_longa")
    assert len(longa["falas"]) == 12


def test_le_yaml_com_todos_os_campos(tmp_path):
    (tmp_path / "x.yaml").write_text(
        "nome: x\nremetente: '5581999990001'\nimagem: bancada/imagens/a.jpg\n"
        "falas: [oi, 'tem civic?']\ndeve:\n  tools: [consultar_estoque]\n  handoff: não\n"
        "nao_pode: [preco_inventado]\npendente: L1\n", encoding="utf-8")
    r = rb.carregar_roteiros(tmp_path)[0]
    assert r["remetente"] == "5581999990001"
    assert r["falas"] == ["oi", "tem civic?"]
    assert r["deve"] == {"tools": ["consultar_estoque"], "handoff": False, "contem": []}
    assert r["pendente"] == "L1"
    assert rb.carregar_roteiros(tmp_path, so="x")[0]["nome"] == "x"


@pytest.mark.parametrize("dados", [
    {"falas": ["oi"]},                                          # sem nome
    {"nome": "x", "falas": []},                                 # sem falas
    {"nome": "x", "falas": ["oi"], "nao_pode": ["outra_coisa"]},
    {"nome": "x", "falas": ["oi"], "deve": {"handoff": "talvez"}},
    {"nome": "x", "falas": ["oi"], "campo_errado": 1},
])
def test_roteiro_invalido_e_recusado(dados):
    with pytest.raises(rb.RoteiroInvalido):
        rb.validar_roteiro(dados, "x")


def test_opcao_roteiro_inexistente_avisa():
    with pytest.raises(rb.RoteiroInvalido):
        rb.carregar_roteiros(so="nao-existe")


# ------------------------------------------------------- banco temporário

def test_usa_banco_temporario_e_nunca_o_real():
    real = RAIZ / "loja.db"
    antes = real.stat().st_mtime if real.exists() else None
    caminhos = []

    def responder(texto, loja_id, lead_id):
        caminhos.append(Path(banco.CAMINHO_BANCO).resolve())
        return [AIMessage(content="Oi!")]

    rodar([roteiro(), roteiro(nome="outro")], GrafoFalso(responder))
    assert len(set(caminhos)) == 2                      # um banco novo por roteiro
    assert all(c != real.resolve() and c.parent == (rb._PASTA_TEMP).resolve() for c in caminhos)
    assert (real.stat().st_mtime if real.exists() else None) == antes


def test_loja_ficticia_tem_estoque_e_equipe_so_dela():
    vistos = {}

    def responder(texto, loja_id, lead_id):
        vistos["loja1"] = rb._ler("SELECT COUNT(*) n FROM estoque WHERE loja_id = 1")[0]["n"]
        vistos["dono"] = rb._ler("SELECT papel FROM usuarios WHERE contato_whatsapp = '5581999990001'")
        return [AIMessage(content="Oi!")]

    rodar([roteiro()], GrafoFalso(responder))
    assert vistos["loja1"] == len(rb.ESTOQUE)
    assert vistos["dono"] == [{"papel": "gestor"}]


def test_chamado_de_outra_loja_nao_conta_como_aviso_ao_vendedor():
    """Duas lojas: chamado aberto na loja 2 para o mesmo cliente não aparece na loja 1."""
    from tools import acionar_handoff

    def responder(texto, loja_id, lead_id):
        rb._sql("INSERT OR IGNORE INTO lojas (id, nome, segmento, config) VALUES (2, 'B', 'veiculos', '{}')")
        acionar_handoff.func(motivo="da loja B", resumo="r", lead_id=lead_id, loja_id=2)
        return [AIMessage(content="Oi!")]

    rodada = rodar([roteiro(deve={"handoff": "não"})], GrafoFalso(responder))
    res = rodada.resultados[0]
    assert all(not t.avisos_vendedor for t in res.turnos)
    assert res.status == rb.PASSOU


# ------------------------------------------------------- envio falso / real

def test_envio_vira_registro_com_bolhas_fotos_e_aviso_ao_vendedor():
    from tools import acionar_handoff

    def responder(texto, loja_id, lead_id):
        acionar_handoff.func(motivo="cliente pediu desconto", resumo="r", lead_id=lead_id, loja_id=loja_id)
        return [
            AIMessage(content="", tool_calls=[{"name": "enviar_fotos", "args": {}, "id": "f1"},
                                              {"name": "acionar_handoff", "args": {}, "id": "h1"}]),
            ToolMessage(content="Fotos.", tool_call_id="f1", name="enviar_fotos",
                        artifact={"tipo": "fotos", "urls": ["https://exemplo/civic.jpg"]}),
            ToolMessage(content="Handoff acionado.", tool_call_id="h1", name="acionar_handoff"),
            AIMessage(content="Olha as fotos! Vou passar seu pedido para a equipe."),
        ]

    rodada = rodar([roteiro(deve={"tools": ["enviar_fotos"], "handoff": "sim"})], GrafoFalso(responder))
    turno = rodada.resultados[0].turnos[0]
    assert turno.bolhas and turno.fotos == ["https://exemplo/civic.jpg"]
    assert turno.tools == ["enviar_fotos", "acionar_handoff"]
    assert turno.avisos_vendedor == ["cliente pediu desconto"]
    assert rodada.resultados[0].status == rb.PASSOU
    texto = rb.montar_relatorio(rodada)
    assert "**Cliente:** oi" in texto and "**Léo:**" in texto and "civic.jpg" in texto


def test_tentativa_de_envio_real_aborta_a_rodada():
    import httpx

    def responder(texto, loja_id, lead_id):
        httpx.post("https://api.telegram.org/botXYZ/sendMessage", json={"text": "oi"})
        return [AIMessage(content="Oi!")]

    rodada = rodar([roteiro(), roteiro(nome="segundo")], GrafoFalso(responder))
    assert rodada.abortada and "api.telegram.org" in rodada.abortada
    assert len(rodada.resultados) == 0          # parou no primeiro roteiro
    assert "RODADA ABORTADA" in rb.montar_relatorio(rodada)


@pytest.mark.parametrize("url", ["https://graph.facebook.com/v21.0/123/messages",
                                 "https://graph.instagram.com/me/messages"])
def test_whatsapp_e_instagram_tambem_abortam(url):
    import httpx

    def responder(texto, loja_id, lead_id):
        with httpx.Client() as cliente:
            cliente.post(url, json={})
        return [AIMessage(content="Oi!")]

    assert rodar([roteiro()], GrafoFalso(responder)).abortada


def test_aviso_pelo_bot_do_telegram_aborta():
    from app import avisos

    def responder(texto, loja_id, lead_id):
        avisos._enviar("123", "chamado novo")
        return [AIMessage(content="Oi!")]

    rodada = rodar([roteiro()], GrafoFalso(responder))
    assert "Telegram" in rodada.abortada


def test_trava_sai_de_cena_depois_da_rodada():
    import httpx
    from app import avisos
    envio, aviso = httpx.Client.send, avisos._enviar
    rodar([roteiro()], GrafoFalso())
    assert httpx.Client.send is envio and avisos._enviar is aviso


# ------------------------------------------------------------------ teto

def test_teto_zero_nao_roda_nada():
    grafo = GrafoFalso()
    rodada = rodar([roteiro(), roteiro(nome="b")], grafo, teto=0.0)
    assert grafo.chamadas == []
    assert rodada.parou_no_teto
    assert "RODADA INCOMPLETA" in rb.montar_relatorio(rodada)


def test_teto_para_no_meio_da_rodada():
    # 1 milhão de tokens de entrada por resposta = US$ 0,25 por turno.
    grafo = GrafoFalso(tokens=(1_000_000, 0))
    rodada = rodar([roteiro(falas=["a", "b", "c"]), roteiro(nome="b")], grafo, teto=0.50)
    assert len(grafo.chamadas) == 2
    assert rodada.parou_no_teto
    assert rodada.resultados[1].status == rb.NAO_RODOU
    assert rodada.gasto_usd == pytest.approx(0.50)


def test_teto_vem_da_variavel(monkeypatch):
    monkeypatch.delenv("LEO_API_TETO_USD", raising=False)
    assert rb.teto_usd() == pytest.approx(0.50)
    monkeypatch.setenv("LEO_API_TETO_USD", "0,20")
    assert rb.teto_usd() == pytest.approx(0.20)
    monkeypatch.setenv("LEO_API_TETO_USD", "abc")
    assert rb.teto_usd() == pytest.approx(0.50)


# ---------------------------------------------------------- regras PENDENTE

def test_decidir():
    assert rb.decidir([], [], [], None) == (rb.PASSOU, None)
    assert rb.decidir([], ["x"], [], None) == (rb.FALHOU, None)
    assert rb.decidir([], ["x"], [], "L1") == ("PENDENTE (L1)", None)
    assert rb.decidir([], [], [], "L1") == (rb.PASSOU, rb.ALERTA_PENDENTE)
    assert rb.decidir(["preço"], [], [], "L1") == (rb.FALHOU, None)
    assert rb.decidir([], [], ["robô"], None) == (rb.AVISO, None)
    assert rb.decidir([], ["x"], ["imagem ausente: a.jpg"], "L5") == (rb.AVISO, None)


def test_pendente_que_falha_vira_pendente():
    rodada = rodar([roteiro(deve={"tools": ["registrar_recado"]}, pendente="L3")], GrafoFalso())
    assert rodada.resultados[0].status == "PENDENTE (L3)"


def test_pendente_que_passa_pede_para_tirar_o_pendente():
    rodada = rodar([roteiro(pendente="L2")], GrafoFalso())
    res = rodada.resultados[0]
    assert (res.status, res.alerta) == (rb.PASSOU, rb.ALERTA_PENDENTE)
    assert "remova o pendente" in rb.montar_relatorio(rodada)


def test_preco_inventado_e_falha_mesmo_com_pendente():
    rodada = rodar([roteiro(falas=["quanto é o civic?"], nao_pode=["preco_inventado"], pendente="L1")],
                   GrafoFalso(lambda t, l, c: [AIMessage(content="Sai por R$ 77.000,00.")]))
    res = rodada.resultados[0]
    assert res.status == rb.FALHOU
    assert res.turnos[0].barrado == "Sai por R$ 77.000,00."


def test_preco_que_veio_da_tool_passa():
    def responder(texto, loja_id, lead_id):
        return [AIMessage(content="", tool_calls=[{"name": "consultar_estoque", "args": {}, "id": "e1"}]),
                ToolMessage(content="Civic 2019 - R$ 98.000,00", tool_call_id="e1", name="consultar_estoque"),
                AIMessage(content="O Civic sai por R$ 98.000,00.")]

    rodada = rodar([roteiro(nao_pode=["preco_inventado"], deve={"tools": ["consultar_estoque"]})],
                   GrafoFalso(responder))
    assert rodada.resultados[0].status == rb.PASSOU


@pytest.mark.parametrize("chave,resposta", [
    ("credito", "Pode ficar tranquilo, seu crédito está aprovado!"),
    ("desconto", "Consigo te dar um desconto de 5 mil no Corolla."),
    ("valor_troca", "No seu Gol a gente paga R$ 30.000,00 na troca."),
])
def test_promessas_falham_mesmo_com_pendente(chave, resposta):
    rodada = rodar([roteiro(nao_pode=[chave], pendente="L1")],
                   GrafoFalso(lambda t, l, c: [AIMessage(content=resposta)]))
    assert rodada.resultados[0].status == rb.FALHOU


@pytest.mark.parametrize("resposta", [
    "Não consigo dar desconto por aqui, vou passar para a equipe.",
    "Vou verificar com o vendedor se consegue algum desconto.",
    "Crédito depende da análise do banco, não consigo garantir.",
])
def test_frases_sem_promessa_nao_falham(resposta):
    rodada = rodar([roteiro(nao_pode=["credito", "desconto", "valor_troca"])],
                   GrafoFalso(lambda t, l, c: [AIMessage(content=resposta)]))
    assert rodada.resultados[0].status == rb.PASSOU


def test_imagem_ausente_da_aviso_e_nao_quebra():
    rodada = rodar([roteiro(imagem="bancada/imagens/nao_existe.jpg", pendente="L5")], GrafoFalso())
    res = rodada.resultados[0]
    assert res.status == rb.AVISO
    assert any("imagem ausente" in a for a in res.avisos)
    assert res.turnos and res.turnos[0].fala == "oi"


def test_imagem_presente_passa_pelo_caminho_de_midia_de_hoje(tmp_path, monkeypatch):
    (tmp_path / "carro.jpg").write_bytes(b"\xff\xd8\xff")
    monkeypatch.setattr(rb, "RAIZ", tmp_path)
    rodada = rodar([roteiro(imagem="carro.jpg")], GrafoFalso())
    primeiro = rodada.resultados[0].turnos[0]
    assert primeiro.fala == "[foto: carro.jpg]" and primeiro.bolhas


def test_contem_confere_o_texto_do_leo():
    grafo = GrafoFalso(lambda t, l, c: [AIMessage(content="Abrimos às 8h no sábado.")])
    rodada = rodar([roteiro(deve={"contem": ["8h|08:00", "domingos ferreira"]})], grafo)
    res = rodada.resultados[0]
    assert res.status == rb.FALHOU
    assert any("domingos ferreira" in f for f in res.falhas)


def test_relatorio_tem_resumo_e_custo(tmp_path):
    rodada = rodar([roteiro(), roteiro(nome="b", pendente="L2", deve={"tools": ["x"]})], GrafoFalso())
    texto = rb.montar_relatorio(rodada, "modelo-falso")
    assert "## Resumo" in texto and "| PASSOU | 1 |" in texto and "| PENDENTE | 1 |" in texto
    assert "Custo total: US$" in texto
    caminho = rb.salvar_relatorio(texto, tmp_path)
    assert caminho.name.startswith("rodada_") and caminho.suffix == ".md"

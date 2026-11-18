"""
L10: emoji no que o cliente recebe, toques de remarketing diferentes de verdade, jobs que não
quebram em terminal cp1252, aviso do juiz. OFFLINE, LLM falso, duas lojas.
"""
import asyncio
import io
import os
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from app import lojas
from app.custos import Uso
from app.guarda_politica import MENSAGEM_SEGURA, contar_emojis, limitar_emojis, sem_emoji

LOJA_A, LOJA_B = 1, 2


# ------------------------------------------------------------ contar e limitar

@pytest.mark.parametrize("texto,n", [
    ("Oi! 😊", 1), ("👍🏽 beleza", 1), ("❤️", 1), ("🇧🇷", 1), ("👨‍👩‍👧 família", 1),
    ("sem nada", 0), ("10% de entrada → ok", 0), ("Oi 😊 tudo bem? 🚗🔥", 3),
])
def test_contar_emojis(texto, n):
    assert contar_emojis(texto) == n


def test_limitar_emojis_tira_o_excedente_sem_sobrar_espaco():
    assert limitar_emojis("Oi 😊 tudo bem? 🚗 Temos o Civic 🔥!", 1) == ("Oi 😊 tudo bem? Temos o Civic!", 2)
    assert limitar_emojis("Temos sim 👍 . Quer ver?", 0) == ("Temos sim. Quer ver?", 1)
    assert limitar_emojis("Linha um\n🚗🚗\nLinha dois", 0) == ("Linha um\nLinha dois", 2)
    assert limitar_emojis("Parágrafo 1\n\nParágrafo 2", 0) == ("Parágrafo 1\n\nParágrafo 2", 0)


def test_textos_fixos_sem_emoji():
    assert contar_emojis(MENSAGEM_SEGURA) == 0
    assert contar_emojis(lojas.PADROES["instagram"]["texto_private_reply"]) == 0


def test_prompt_tem_as_regras_curtas():
    from app.core.montagem import PASTA_PROMPTS, pasta_do_segmento
    base = (PASTA_PROMPTS / "base.md").read_text(encoding="utf-8")
    assert "Escreva sem emoji; no máximo 1 se o cliente usou emoji, nunca em assunto sério." in base
    assert '"Gostaria de...?"' in base
    assert "entre os SUVs ou no geral" in (pasta_do_segmento("veiculos") / "prompt.md").read_text(encoding="utf-8")


# ------------------------------------------------------------ no turno

def _sql(sql, parametros=()):
    conexao = banco.conectar()
    try:
        conexao.execute(sql, parametros)
        conexao.commit()
    finally:
        conexao.close()


@pytest.fixture
def duas_lojas():
    for loja_id in (LOJA_A, LOJA_B):
        _sql("INSERT OR IGNORE INTO lojas (id, nome, segmento, config) VALUES (?, ?, 'veiculos', '{}')",
             (loja_id, f"Loja {loja_id}"))
    lojas.limpar_cache()


class GrafoFalso:
    def __init__(self, resposta):
        self.resposta = resposta

    def invoke(self, entrada, config=None):
        return {"messages": [HumanMessage(content=entrada["messages"][0].content),
                             AIMessage(content=self.resposta)]}


def _turno(loja_id, lead, texto, resposta):
    from app.core.turno import executar_turno
    return asyncio.run(executar_turno(loja_id, "simulador", lead, texto, grafo=GrafoFalso(resposta)))


def test_cliente_sem_emoji_recebe_zero(duas_lojas):
    assert _turno(LOJA_A, "l1", "tem civic?", "Temos sim! 🚗😊 Quer ver fotos? 👀").texto == "Temos sim! Quer ver fotos?"


def test_cliente_com_emoji_recebe_no_maximo_um(duas_lojas):
    r = _turno(LOJA_A, "l2", "oi 😊 tem civic?", "Temos sim! 🚗😊 Quer ver fotos? 👀")
    assert contar_emojis(r.texto) == 1 and r.texto == "Temos sim! 🚗 Quer ver fotos?"


def test_emoji_numa_mensagem_anterior_vale_na_conversa_mas_nao_em_outra_loja(duas_lojas):
    _turno(LOJA_A, "l3", "oi 😊", "Oi!")
    assert contar_emojis(_turno(LOJA_A, "l3", "tem civic?", "Temos 🚗🚗").texto) == 1
    assert contar_emojis(_turno(LOJA_B, "l3", "tem civic?", "Temos 🚗🚗").texto) == 0


def test_assunto_serio_nunca_tem_emoji(duas_lojas):
    r = _turno(LOJA_A, "l4", "isso é um absurdo 😡 vou no Procon", "Sinto muito 🙏 O pessoal da equipe vai falar com você.")
    assert r.handoff_aberto and contar_emojis(r.texto) == 0


def test_financiamento_com_chamado_nunca_tem_emoji(duas_lojas):
    r = _turno(LOJA_A, "l5", "sou autônomo 😅 consigo financiar?", "Vamos ver 😉 A aprovação depende da análise.")
    assert r.handoff_aberto and contar_emojis(r.texto) == 0


# ------------------------------------------------------------ remarketing e pós-venda

def test_remarketing_tira_emoji_e_reservas_nao_tem():
    from app.jobs import remarketing as rmk
    assert contar_emojis(rmk._limpar_texto("Oi! 🚗 O Civic continua aqui 😊")) == 0
    loja = lojas.Loja(id=1, nome="Loja", segmento="veiculos", config={}, versao_config=1, ativo=True)
    for dados in ({"nome": "", "carro": "Honda Civic 2019", "carro_disponivel": True, "alternativa": ""},
                  {"nome": "", "carro": "Honda Civic 2019", "carro_disponivel": False, "alternativa": "Jeep Renegade 2020"},
                  {"nome": "", "carro": "", "carro_disponivel": False, "alternativa": ""}):
        textos = [rmk._texto_reserva(loja, dados, t) for t in (1, 2, 3)]
        assert all(contar_emojis(t) == 0 for t in textos)
        from app.filtro_remarketing import repete_toque
        assert not repete_toque(textos[1], textos[:1]) and not repete_toque(textos[2], textos[:2])


def test_repete_toque():
    from app.filtro_remarketing import repete_toque
    assert repete_toque("Oi, tudo bem? Você ainda tem interesse no Civic?",
                        ["Oi, tudo bem? Você ainda tem interesse em ver o Civic?"])
    assert repete_toque("Oi tudo bem voce ainda quer?", ["Oi, tudo bem, você ainda pensa no carro?"])   # abertura
    assert not repete_toque("Lembrei de você: o Civic ainda está aqui.", ["Oi! O Civic continua disponível?"])


def test_redator_recebe_os_toques_anteriores():
    from app.jobs.remarketing import _prompt_redator
    loja = lojas.Loja(id=1, nome="Loja", segmento="veiculos", config={}, versao_config=1, ativo=True)
    dados = {"nome": "", "interesse": "", "carro": "Civic", "carro_disponivel": True, "alternativa": "",
             "veiculo_id": None, "carro_vendido": False, "toques_anteriores": ["Oi, tudo bem? E o Civic?"]}
    texto = _prompt_redator(loja, 2, dados, [])
    assert "PROIBIDO repetir a abertura" in texto and "Retomada 1: Oi, tudo bem? E o Civic?" in texto
    assert "sem emoji" in texto


@pytest.fixture
def pasta_temporaria_da_bancada(monkeypatch, tmp_path):
    from scripts import rodar_bancada as rb
    monkeypatch.setattr(rb, "_PASTA_TEMP", tmp_path / "bancada")
    (tmp_path / "bancada").mkdir()
    return rb


def _roteiro_job(rb, **campos):
    base = {"nome": "job", "conversa": [{"cliente": "tem civic?"}, {"leo": "Temos o Civic."}],
            "interesse": "Civic", "passos": [{"remarketing_dias": 30}]}
    base.update(campos)
    return rb.validar_roteiro(base, "teste")


def test_toque_igual_ao_anterior_vira_reserva(pasta_temporaria_da_bancada):
    rb = pasta_temporaria_da_bancada

    def repete(loja, lead_id, canal, toque, dados, historico):
        return "Oi, tudo bem? Você ainda tem interesse no Honda Civic 2019?", Uso()

    rodada = asyncio.run(rb.rodar([_roteiro_job(rb, deve={"toques": 3, "textos_diferentes": True})],
                                  GrafoFalso("Oi!"), teto=1.0, redator=repete))
    res = rodada.resultados[0]
    assert res.status == rb.PASSOU, res.falhas
    assert len({e["texto"] for e in res.envios_job}) == 3


def test_job_nao_quebra_em_terminal_cp1252(pasta_temporaria_da_bancada, monkeypatch):
    rb = pasta_temporaria_da_bancada
    saida = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", saida)

    def com_emoji(loja, lead_id, canal, toque, dados, historico):
        return f"Oi! 🚗 Retomada {toque} do Civic 😊", Uso()

    rodada = asyncio.run(rb.rodar([_roteiro_job(rb, passos=[{"remarketing_dias": 5}])],
                                  GrafoFalso("Oi!"), teto=1.0, redator=com_emoji))
    res = rodada.resultados[0]
    assert res.envios_job and all(contar_emojis(e["texto"]) == 0 for e in res.envios_job)
    assert not any("erro" in f for f in res.falhas)


def test_pos_venda_sai_sem_emoji(pasta_temporaria_da_bancada, monkeypatch):
    rb = pasta_temporaria_da_bancada
    from app.jobs import pos_venda
    monkeypatch.setattr(pos_venda, "_texto_livre", lambda modelo, valores: "Oi! 🎉 Obrigado pela compra 😊")
    rodada = asyncio.run(rb.rodar([rb.validar_roteiro({
        "nome": "pv", "conversa": [{"cliente": "fechei o Onix"}], "venda": {"modelo": "Onix", "pagamento": "avista"},
        "passos": [{"pos_venda_dias": 2}]}, "teste")], GrafoFalso("Oi!"), teto=1.0))
    envios = rodada.resultados[0].envios_job
    assert envios and all(e["texto"] == "Oi! Obrigado pela compra" for e in envios)


# ------------------------------------------------------------ bancada: checagens globais

def test_bancada_falha_emoji_sem_o_cliente_usar(pasta_temporaria_da_bancada, monkeypatch):
    rb = pasta_temporaria_da_bancada
    from app.core import turno
    monkeypatch.setattr(turno, "limitar_emojis", lambda texto, maximo: (texto, 0))   # desliga a guarda
    sem = asyncio.run(rb.rodar([rb.validar_roteiro({"nome": "e", "falas": ["tem civic?"]}, "t")],
                               GrafoFalso("Temos 🚗"), teto=1.0))
    assert sem.resultados[0].status == rb.FALHOU
    dois = asyncio.run(rb.rodar([rb.validar_roteiro({"nome": "e2", "falas": ["oi 😊"]}, "t")],
                                GrafoFalso("Oi 😊🚗"), teto=1.0))
    assert dois.resultados[0].status == rb.FALHOU
    um = asyncio.run(rb.rodar([rb.validar_roteiro({"nome": "e3", "falas": ["oi 😊"]}, "t")],
                              GrafoFalso("Oi 😊"), teto=1.0))
    assert um.resultados[0].status == rb.PASSOU


def test_toques_parecidos_na_bancada(pasta_temporaria_da_bancada):
    rb = pasta_temporaria_da_bancada
    problemas = rb.toques_parecidos(["Oi, tudo bem? Você ainda tem interesse no Civic?",
                                     "Oi, tudo bem? Você ainda quer o Civic?",
                                     "Fico à disposição quando quiser."])
    assert any("começam igual" in p for p in problemas)
    assert rb.toques_parecidos(["Oi! O Civic continua aqui.", "Lembrei de você: marco uma visita?"]) == []


def test_roteiro_50_carrega(pasta_temporaria_da_bancada):
    rb = pasta_temporaria_da_bancada
    roteiros = {r["nome"]: r for r in rb.carregar_roteiros()}
    assert roteiros["cliente_usa_emoji"]["falas"][0] == "oi 😊 tem civic?"
    assert roteiros["remarketing_carro_vendido"]["deve"]["textos_diferentes"] is True


# ------------------------------------------------------------ juiz

def test_juiz_avisa_quando_usa_o_mesmo_modelo(monkeypatch):
    from scripts import juiz_bancada as jz
    monkeypatch.delenv("LEO_JUIZ_MODELO", raising=False)
    assert jz.juiz_e_o_mesmo_modelo()
    texto = jz.montar([], "r.md", 0.0, "m", jz.juiz_e_o_mesmo_modelo())
    assert "juiz = mesmo modelo do Léo (notas otimistas)" in texto
    monkeypatch.setenv("LEO_JUIZ_MODELO", "outro")
    assert "notas otimistas" not in jz.montar([], "r.md", 0.0, "outro", jz.juiz_e_o_mesmo_modelo())

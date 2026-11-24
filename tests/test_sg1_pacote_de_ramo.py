"""
SG1 (Maratona 4): o motor separado do pacote de veículos. OFFLINE, sem IA.

Regra de ouro: o comportamento do Léo para lojas de carro NÃO muda.
- O prompt de uma loja de carros, em 13 situações, é IGUAL (letra por letra) ao de antes do SG1
  (foto em tests/dados/prompt_veiculos_antes_do_sg1.json, gerada na branch arrumacoes).
- As guardas de carro rodam pelo gancho do ramo, no mesmo lugar da lista N4.
- Um ramo sem guardas próprias não ganha nenhuma guarda de carro (duas lojas, ramos diferentes).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage

from app import segmentos
from app.core.pos_processamento import Contexto, PASSOS, pos_processar
from app.lojas import criar_loja
from tests import prompt_de_referencia as referencia

RAIZ = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ regra de ouro: o prompt
def test_prompt_da_loja_de_carros_igual_ao_de_antes_do_sg1():
    antes = json.loads(referencia.ARQUIVO.read_text(encoding="utf-8"))
    agora = referencia.montar_todos()
    assert set(agora) == set(antes)
    for situacao in antes:
        a, d = json.loads(antes[situacao]), json.loads(agora[situacao])
        assert d["ferramentas"] == a["ferramentas"], situacao
        assert d["prompt"] == a["prompt"], situacao


def test_base_do_prompt_nao_tem_carro_e_o_ramo_preenche():
    base = (RAIZ / "prompts" / "base.md").read_text(encoding="utf-8")
    assert "carro" not in base.lower() and "quilometragem" not in base.lower()
    assert "{{ramo:" in base


# ------------------------------------------------------------------ o encaixe
def test_motor_e_teste_usam_o_mesmo_modulo_do_ramo():
    import segmentos.veiculos.guardas as direto
    assert segmentos.modulo_do_segmento("veiculos", "guardas") is direto
    assert segmentos.gancho("veiculos", "guardas", "cortar_estado_inventado") is direto.cortar_estado_inventado


def test_gancho_inexistente_e_none():
    assert segmentos.gancho("veiculos", "guardas", "nao_existe") is None
    assert segmentos.gancho("veiculos", "arquivo_que_nao_existe", "x") is None
    assert segmentos.gancho("ramo_que_nao_existe", "guardas", "x") is None


def test_ordem_n4_nao_mudou():
    assert [p.__name__ for p in PASSOS] == [
        "texto_interno", "preco_inventado", "frases_proibidas", "regra_de_entrada", "risco_e_politica",
        "promessa_de_foto", "elogio_da_foto", "estado_sem_ficha", "agendamento", "chamado_pelo_codigo",
        "pos_venda_e_urgencia", "aviso_de_chamado", "falso_dono", "emoji", "palavra_de_tempo",
        "dia_de_reabertura", "fragmentos", "repeticoes", "frase_de_oferta"]


def test_nomes_de_ferramenta_do_ramo_carregado():
    import segmentos.veiculos.ferramentas  # noqa: F401  (o ramo está carregado)
    from app.core import agent
    from app.core.turno import FERRAMENTAS_QUE_GRAVAM
    assert {"consultar_estoque", "detalhes_veiculo", "registrar_troca"} <= set(agent.TOOLS_COM_LOJA_ID)
    assert "registrar_troca" in agent.TOOLS_COM_LEAD_ID and "registrar_troca" in FERRAMENTAS_QUE_GRAVAM
    assert "consultar_estoque" not in agent.TOOLS_COM_LEAD_ID


# ------------------------------------------------------------------ guardas de carro pelo gancho
def _contexto(loja_id, resposta, texto="tem o Civic?", do_turno=(), foto=False, lead="5581900000001"):
    return Contexto(loja_id=loja_id, canal="telegram", lead_id=lead, texto=texto, do_turno=list(do_turno),
                    mensagens=[], rotulo="[teste]", resposta=resposta, midias=[], handoff=False,
                    ferramentas=[], foto_carro=foto, sombra=True)


@pytest.fixture
def ramo_sem_guardas(tmp_path, monkeypatch):
    """Um segundo ramo de mentira (só prompt.md), ao lado do de veículos."""
    for nome in ("veiculos", "barbearia"):
        (tmp_path / nome).mkdir()
    (tmp_path / "veiculos" / "prompt.md").write_text("veículos", encoding="utf-8")
    (tmp_path / "barbearia" / "prompt.md").write_text("barbearia", encoding="utf-8")
    monkeypatch.setattr(segmentos, "PASTA_SEGMENTOS", tmp_path)
    return tmp_path


def test_loja_de_carro_corta_estado_inventado():
    c = pos_processar(_contexto(1, "O Civic está em ótimo estado. Quer ver?"))
    assert "ótimo estado" not in c.resposta and "guarda_estado" in c.ferramentas
    assert c.ramo == "veiculos"


def test_loja_de_carro_foto_sem_elogio():
    c = pos_processar(_contexto(1, "Que carro bem conservado!", foto=True))
    assert c.resposta.startswith("Obrigado pela foto!")


def test_loja_de_outro_ramo_nao_ganha_guarda_de_carro(ramo_sem_guardas):
    loja_carro = criar_loja("Loja Carro SG1")
    loja_outra = criar_loja("Barbearia SG1", segmento="barbearia")
    monkeypatch_volta = segmentos.PASTA_SEGMENTOS
    segmentos.PASTA_SEGMENTOS = segmentos._PASTA_OFICIAL        # a loja de carro usa o pacote real
    try:
        carro = pos_processar(_contexto(loja_carro, "O Civic está em ótimo estado. Quer ver?"))
    finally:
        segmentos.PASTA_SEGMENTOS = monkeypatch_volta
    outra = pos_processar(_contexto(loja_outra, "O corte está em ótimo estado. Quer ver?", foto=True))
    assert "ótimo estado" not in carro.resposta
    assert outra.ramo == "barbearia"
    assert "ótimo estado" in outra.resposta                       # nenhuma guarda de carro
    assert not {"guarda_estado", "guarda_elogio"} & set(outra.ferramentas)


def test_ficha_do_turno_vem_do_ramo():
    ficha = ToolMessage(content="Civic 2019, ótimo estado (laudo)", tool_call_id="1", name="consultar_estoque")
    c = pos_processar(_contexto(1, "O Civic está em ótimo estado. Quer ver?", do_turno=[ficha]))
    assert "ótimo estado" in c.resposta                           # veio da ficha: fica


def test_test_drive_lembra_a_cnh_pelo_gancho():
    from segmentos.veiculos.guardas import FRASE_CNH, depois_da_agenda
    assert depois_da_agenda("Marcado!", "Agendamento confirmado: test-drive sábado") == f"Marcado! {FRASE_CNH}"
    assert depois_da_agenda("Marcado! Traga a CNH.", "Agendamento confirmado: test-drive") == "Marcado! Traga a CNH."
    assert depois_da_agenda("Marcado!", "Agendamento confirmado: visita") == "Marcado!"


def test_troca_vem_antes_das_regras_do_motor():
    from segmentos.veiculos.guardas import motivo_do_chamado_pelo_codigo
    assert motivo_do_chamado_pelo_codigo("quanto vocês pagam no meu?", "Ok.")[1] == "guarda_troca"
    assert motivo_do_chamado_pelo_codigo("aceita troca?", "Ok.", "nao_informado")[1] == "guarda_aceita_troca"
    assert motivo_do_chamado_pelo_codigo("aceita troca?", "Ok.", "sim") is None


def test_motor_nao_tem_mais_as_guardas_de_carro():
    import app.guarda_politica as g
    import app.core.turno as t
    for nome in ("cortar_estado_inventado", "tirar_elogio_do_estado", "tirar_elogio_da_descricao",
                 "pergunta_se_aceita_troca", "pediu_valor_da_troca", "FRASE_ESTADO", "FRASE_CNH"):
        assert not hasattr(g, nome), nome
    for nome in ("_aceita_troca", "motivo_do_chamado_pelo_codigo", "_anotar_foto_na_troca", "FRASE_CNH"):
        assert not hasattr(t, nome), nome
    assert not (RAIZ / "app" / "categorias.py").exists()
    for nome in ("consultar_estoque", "detalhes_veiculo", "registrar_troca"):
        assert not (RAIZ / "tools" / f"{nome}.py").exists()
        assert (RAIZ / "segmentos" / "veiculos" / f"{nome}.py").exists()


def test_contrato_escrito():
    texto = (RAIZ / "docs" / "pacote_de_ramo.md").read_text(encoding="utf-8")
    for item in ("prompt.md", "ferramentas.py", "guardas.py", "textos.py", "catalogo.py",
                 "bancada/roteiros", "tirar_elogio_do_estado", "cortar_estado_inventado",
                 "depois_da_agenda", "motivo_do_chamado"):
        assert item in texto, item

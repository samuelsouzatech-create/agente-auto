"""
Maratona 3, N5 (último bloco da Fase Cérebro): regra dos 60% só na linha inteira e sem apagar ação
feita, guardas que mantêm o assunto, palavra de tempo, sombra com a mesma lista, juiz da bancada que
entende negação. OFFLINE, LLM falso, duas lojas.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from segmentos.veiculos.guardas import FRASE_ESTADO, cortar_estado_inventado                 # SG1: guardas do ramo
from app.guarda_politica import (FRASE_CONTATO, tirar_palavra_de_tempo,
                                 tirar_texto_interno, trocar_frases_proibidas)

RAIZ = Path(__file__).resolve().parents[1]
RESUMO = ["cliente pediu para falar com um vendedor",
          "O cliente perguntou sobre o Honda Civic 2019 e solicitou falar com um vendedor."]


def _ler(sql, parametros=()):
    conexao = banco.conectar()
    try:
        return [dict(l) for l in conexao.execute(sql, parametros).fetchall()]
    finally:
        conexao.close()


# ------------------------------------------------------------ 1) regra dos 60%

@pytest.mark.parametrize("feitas", [[], ["enviar_fotos", "acionar_handoff"]])
def test_frase_das_fotos_com_carro_do_resumo_fica(feitas):
    frase = "Enviei as fotos do Honda Civic 2019 para você."
    assert tirar_texto_interno(frase, RESUMO, feitas) == (frase, False)
    texto = f"{frase} O pessoal da equipe vai falar com você por aqui."
    assert tirar_texto_interno(texto, RESUMO, feitas) == (texto, False)


def test_linha_que_repete_o_resumo_inteiro_ainda_sai():
    texto = "O cliente perguntou sobre o Honda Civic 2019 e solicitou falar com um vendedor.\nTemos o Civic."
    assert tirar_texto_interno(texto, RESUMO) == ("Temos o Civic.", True)


def test_acao_feita_nunca_sai_mesmo_repetindo_o_resumo():
    resumo = ["Cliente pediu fotos do Honda Civic 2019 e quer agendar test-drive sábado."]
    linha = "Enviei as fotos do Honda Civic 2019 e agendei o test-drive de sábado."
    assert tirar_texto_interno(linha, resumo)[1] is True                  # sem a ação: repete o resumo
    assert tirar_texto_interno(linha, resumo, ["enviar_fotos", "agendar_visita"]) == (linha, False)


def test_regra_dos_60_nunca_tira_so_um_pedaco_da_linha():
    # a frase que repete o resumo está numa linha com conteúdo próprio da resposta: fica tudo,
    # porque a regra só apaga a linha inteira quando a LINHA repete o resumo
    texto = "Temos o Civic 2019 branco, automático, por R$ 98.000,00, com 48 mil km. Quer ver fotos dele?"
    assert tirar_texto_interno(texto, RESUMO) == (texto, False)


# ------------------------------------------------------------ 2) assunto mantido

@pytest.mark.parametrize("frase, assunto", [
    ("Como o pessoal da equipe já está acompanhando, eles vão confirmar a informação sobre o IPVA.", "o IPVA"),
    ("Já passei o seu questionamento sobre o histórico do veículo para eles.", "o histórico do carro"),
    ("Já passei sua dúvida sobre o leilão para a equipe.", "o leilão"),
])
def test_frase_proibida_trocada_mantem_o_assunto(frase, assunto):
    novo, trocou = trocar_frases_proibidas(frase)
    assert trocou and novo == f"O pessoal da equipe vai falar com você por aqui sobre {assunto}."


def test_frase_proibida_sem_assunto_fica_como_antes():
    assert trocar_frases_proibidas("Já passei para o pessoal.") == (FRASE_CONTATO, True)


def test_estado_do_carro_trocado_mantem_o_historico():
    novo, trocou = cortar_estado_inventado("Posso garantir que o histórico desse veículo é limpo.", "")
    assert trocou and "histórico do carro" in novo and "pessoalmente" in novo
    assert cortar_estado_inventado("Ele está em ótimo estado de conservação.", "")[0] == FRASE_ESTADO


# ------------------------------------------------------------ palavra de tempo

@pytest.mark.parametrize("antes, depois", [
    ("O pessoal da equipe logo vai falar com você por aqui.", "O pessoal da equipe vai falar com você por aqui."),
    ("O pessoal da equipe logo mais entra em contato.", "O pessoal da equipe entra em contato."),
    ("Em breve o pessoal da equipe vai falar com você.", "O pessoal da equipe vai falar com você."),
    ("Já já o vendedor te responde por aqui.", "O vendedor te responde por aqui."),
])
def test_palavra_de_tempo_sai_da_promessa(antes, depois):
    assert tirar_palavra_de_tempo(antes) == (depois, True)


def test_palavra_de_tempo_fora_de_promessa_fica():
    texto = "As fotos estão logo abaixo. Temos o Civic 2019."
    assert tirar_palavra_de_tempo(texto) == (texto, False)


# ------------------------------------------------------------ 3) sombra usa a mesma lista

class Grafo:
    def __init__(self, resposta, tools=()):
        self.resposta, self.tools = resposta, list(tools)

    def invoke(self, entrada, config=None):
        msgs = [HumanMessage(content=entrada["messages"][0].content)]
        for nome, args, retorno in self.tools:
            msgs.append(AIMessage(content="", tool_calls=[{"name": nome, "args": args, "id": f"c-{nome}"}]))
            msgs.append(ToolMessage(content=retorno, name=nome, tool_call_id=f"c-{nome}"))
        msgs.append(AIMessage(content=self.resposta))
        return {"messages": msgs}


def _ligar_sombra(loja_id):
    conexao = banco.conectar()
    try:
        conexao.execute("INSERT OR IGNORE INTO lojas (id, nome, segmento, config) VALUES (2, 'Loja B', 'veiculos', '{}')")
        conexao.execute("UPDATE lojas SET config = ? WHERE id = ?", (json.dumps({"modo_sombra": True}), loja_id))
        conexao.commit()
    finally:
        conexao.close()
    from app import lojas
    lojas.limpar_cache()


def test_sombra_tira_palavra_de_tempo_e_nada_e_gravado():
    from app.core.turno import executar_turno
    _ligar_sombra(1)
    r = asyncio.run(executar_turno(1, "simulador", "s-1", "quero falar com um vendedor",
                                   grafo=Grafo("O pessoal da equipe logo vai falar com você por aqui.")))
    assert r.silenciado
    [linha] = _ler("SELECT loja_id, sugestao FROM sombra_sugestoes")
    assert linha == {"loja_id": 1, "sugestao": "O pessoal da equipe vai falar com você por aqui."}
    assert _ler("SELECT id FROM handoffs") == [] and _ler("SELECT id FROM mensagens") == []


def test_sombra_e_turno_normal_saem_iguais():
    from tests.conftest import garantir_lojas  # SE3: a loja 2 precisa existir (chaves da loja)
    garantir_lojas(2)
    from app.core.turno import executar_turno
    texto_ia = "Como o pessoal da equipe já está acompanhando, eles vão confirmar a informação sobre o IPVA."
    normal = asyncio.run(executar_turno(2, "simulador", "n-1", "e o IPVA?", grafo=Grafo(texto_ia)))
    _ligar_sombra(1)
    asyncio.run(executar_turno(1, "simulador", "s-2", "e o IPVA?", grafo=Grafo(texto_ia)))
    [linha] = _ler("SELECT sugestao FROM sombra_sugestoes WHERE loja_id = 1")
    assert linha["sugestao"] == normal.texto and "IPVA" in normal.texto


# ------------------------------------------------------------ 4) prompt

def test_prompt_pede_para_citar_o_assunto():
    texto = (RAIZ / "prompts" / "base.md").read_text(encoding="utf-8")
    assert "- Ao responder, cite o assunto da pergunta (ex.: IPVA, leilão, laudo)." in texto


# ------------------------------------------------------------ 5) juiz da bancada

@pytest.mark.parametrize("texto, reprova", [
    ("Não tenho informação sobre vistorias desse carro.", False),
    ("Como sou assistente virtual, não tenho acesso a detalhes de colisões ou vistorias detalhadas.", False),
    ("Sem inspeção registrada na ficha, a equipe confirma.", False),
    ("O Civic passou por vistoria completa.", True),
    ("O carro foi revisado na concessionária.", True),
    ("Ele foi inspecionado e aprovado.", False),        # "inspecao" (a palavra) não aparece
])
def test_juiz_estado_do_carro_entende_negacao(texto, reprova):
    from scripts.rodar_bancada import cita_afirmando, normalizar
    termos = ["vistoria", "revisado", "inspecao"]
    assert any(cita_afirmando(normalizar(t), texto) for t in termos) is reprova


def test_juiz_outras_palavras_continuam_iguais():
    from scripts.rodar_bancada import cita_afirmando
    assert cita_afirmando("nunca bateu", "Ele nunca bateu.") is True
    assert cita_afirmando("bem conservado", "Não sei se está bem conservado.") is True

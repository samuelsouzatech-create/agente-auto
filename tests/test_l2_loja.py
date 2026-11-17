"""
L2: o Léo não inventa nem nega o que a loja tem.
  - endereço vem do cadastro da loja (sem cadastro: não sabe e passa para a equipe);
  - "tem SUV?" acha os carros da categoria;
  - disse que a equipe vai confirmar/falar com o cliente = chamado aberto no mesmo turno.
Offline, LLM falso, duas lojas (a loja A nunca enxerga a B).
"""
import asyncio
import json
from datetime import datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import banco
from app import lojas
from app.categorias import HATCH, PICAPE, SEDA, SUV, categoria_do_modelo, categoria_pedida
from app.guarda_politica import promete_contato_da_equipe

LOJA_A, LOJA_B = 1, 2


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


def _config(loja_id, config):
    texto = json.dumps(config, ensure_ascii=False)
    if _ler("SELECT id FROM lojas WHERE id = ?", (loja_id,)):
        _sql("UPDATE lojas SET config = ? WHERE id = ?", (texto, loja_id))
    else:
        _sql("INSERT INTO lojas (id, nome, segmento, config) VALUES (?, ?, 'veiculos', ?)",
             (loja_id, f"Loja {loja_id}", texto))
    lojas.limpar_cache()


def _carro(loja_id, marca, modelo, preco, ano=2020):
    _sql("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) "
         "VALUES (?, ?, ?, ?, 30000, 'Prata', 'Automático', ?, 'disponivel')",
         (loja_id, marca, modelo, ano, preco))


@pytest.fixture
def duas_lojas():
    _config(LOJA_A, {"endereco": "Av. Domingos Ferreira, 1000, Boa Viagem"})
    _config(LOJA_B, {})
    _carro(LOJA_A, "Jeep", "Renegade", 89900)
    _carro(LOJA_A, "Hyundai", "HB20", 54000)
    _carro(LOJA_A, "Toyota", "Corolla", 135000)
    _carro(LOJA_B, "Jeep", "Compass", 150000)


# ------------------------------------------------------------- categorias

@pytest.mark.parametrize("modelo,categoria", [
    ("Renegade", SUV), ("Corolla Cross", SUV), ("T-Cross", SUV), ("Corolla", SEDA),
    ("HB20S", SEDA), ("Onix Plus", SEDA), ("HB20", HATCH), ("Onix", HATCH), ("Gol", HATCH),
    ("Strada", PICAPE), ("Hilux", PICAPE), ("Doblò", None), ("Modelo Raro", None),
])
def test_categoria_do_modelo(modelo, categoria):
    assert categoria_do_modelo(modelo) == categoria


@pytest.mark.parametrize("texto,categoria", [
    ("SUV", SUV), ("suvs", SUV), ("sedã", SEDA), ("Sedan", SEDA), ("hatch", HATCH),
    ("pick-up", PICAPE), ("caminhonete", PICAPE), ("Renegade", None), ("", None),
])
def test_categoria_pedida(texto, categoria):
    assert categoria_pedida(texto) == categoria


def test_suv_acha_o_renegade_e_nao_ve_a_outra_loja(duas_lojas):
    from tools.consultar_estoque import consultar_estoque
    a = consultar_estoque.invoke({"categoria": "SUV", "loja_id": LOJA_A})
    assert "Renegade" in a and "HB20" not in a and "Corolla" not in a
    assert "Compass" not in a
    b = consultar_estoque.invoke({"categoria": "SUV", "loja_id": LOJA_B})
    assert "Compass" in b and "Renegade" not in b


def test_suv_no_campo_modelo_tambem_vale(duas_lojas):
    from tools.consultar_estoque import consultar_estoque
    assert "Renegade" in consultar_estoque.invoke({"modelo": "SUV", "loja_id": LOJA_A})


def test_categoria_desconhecida_avisa(duas_lojas):
    from tools.consultar_estoque import consultar_estoque
    texto = consultar_estoque.invoke({"categoria": "esportivo", "loja_id": LOJA_A})
    assert "Não sei filtrar" in texto


def test_sem_carro_da_categoria_avisa_dos_que_nao_sabe_classificar():
    from tools.consultar_estoque import consultar_estoque
    _config(LOJA_A, {})
    _carro(LOJA_A, "Fiat", "Doblò", 52000)
    texto = consultar_estoque.invoke({"categoria": "picape", "loja_id": LOJA_A})
    assert "Nenhum carro da categoria picape" in texto
    assert "não sei classificar" in texto


def test_busca_sem_categoria_continua_igual(duas_lojas):
    from tools.consultar_estoque import consultar_estoque
    texto = consultar_estoque.invoke({"loja_id": LOJA_A})
    assert all(m in texto for m in ("Renegade", "HB20", "Corolla"))


# ------------------------------------------------------------- endereço

def test_endereco_e_campo_editavel_e_vazio_por_padrao():
    assert lojas.PADROES["endereco"] == ""
    assert lojas.EDITAVEIS["endereco"]("  Rua A, 10  ") == "Rua A, 10"
    assert lojas.EDITAVEIS["endereco"]("") == ""
    with pytest.raises(ValueError):
        lojas.EDITAVEIS["endereco"]("x" * 201)


def test_prompt_traz_o_endereco_do_cadastro_so_da_propria_loja(duas_lojas):
    from app.core.montagem import _camada_da_loja
    a = _camada_da_loja(lojas.carregar_loja(LOJA_A), datetime(2026, 11, 18, 10, 0))
    b = _camada_da_loja(lojas.carregar_loja(LOJA_B), datetime(2026, 11, 18, 10, 0))
    assert "Endereço da loja: Av. Domingos Ferreira, 1000, Boa Viagem" in a
    assert "Domingos Ferreira" not in b
    assert "não cadastrado" in b and "acionar_handoff" in b and "Nunca invente" in b


def test_endereco_salvo_pela_configuracao_chega_ao_prompt():
    from app.core.montagem import _camada_da_loja
    _config(LOJA_B, {})
    lojas.salvar_config(LOJA_B, {"endereco": "Rua da Aurora, 50, Boa Vista"}, "Teste")
    assert "Rua da Aurora, 50, Boa Vista" in _camada_da_loja(lojas.carregar_loja(LOJA_B))
    assert "Rua da Aurora" not in _camada_da_loja(lojas.carregar_loja(LOJA_A))


# ------------------------------------------------- promessa de contato

@pytest.mark.parametrize("texto", [
    "Vou confirmar com a equipe e o pessoal vai falar com você por aqui.",
    "O pessoal da equipe vai verificar isso para você.",
    "Um vendedor vai te chamar por aqui.",
    "Vou passar sua pergunta para a equipe.",
    "Vou verificar com o vendedor e te aviso.",
    "Alguém da equipe vai te responder.",
])
def test_detecta_promessa_de_contato(texto):
    assert promete_contato_da_equipe(texto)


@pytest.mark.parametrize("texto", [
    "O Renegade está disponível. Quer ver fotos?",
    "Nosso horário no sábado é das 08:00 às 13:00.",
    "Se quiser, posso pedir para um vendedor falar com você. Quer?",
    "Não vou passar nada para a equipe sem você pedir.",
    "Atendo você pessoalmente por aqui mesmo.",
])
def test_nao_detecta_o_que_nao_e_promessa(texto):
    assert not promete_contato_da_equipe(texto)


# L2b: frases da bancada de 17/11 que a guarda deixou passar.
@pytest.mark.parametrize("texto", [
    "Entendi! Vou chamar alguém da equipe para te atender por aqui. Pode ser?",              # roteiro 04
    "Boa pergunta! vou chamar o pessoal da equipe para confirmar esse detalhe para você, pode ser?",  # 05
    "Vou pedir para um vendedor confirmar o laudo.",
    "Vou pedir pra equipe olhar isso.",
    "Vou passar para o pessoal confirmar.",
    "Vou passar para um vendedor.",
])
def test_l2b_detecta_vou_chamar_pedir_passar(texto):
    assert promete_contato_da_equipe(texto)


def test_l2b_pergunta_oferecendo_nao_e_promessa():
    assert not promete_contato_da_equipe("Quer que eu chame um vendedor?")
    assert not promete_contato_da_equipe("Posso chamar alguém da equipe para você?")


def test_l2b_vendedor_mostra_na_visita_nao_e_promessa():
    assert not promete_contato_da_equipe("O vendedor te mostra o carro na visita.")


def test_l2b_prompt_proibe_dizer_que_a_equipe_acompanha_a_conversa():
    from app.core.montagem import PASTA_PROMPTS
    base = (PASTA_PROMPTS / "base.md").read_text(encoding="utf-8")
    assert "Nunca diga que a equipe está acompanhando, lendo ou vendo a conversa" in base


def test_l2b_frase_da_bancada_abre_chamado_no_turno(duas_lojas):
    r = _turno(LOJA_A, "lead-l2b-04", "Vou chamar alguém da equipe para te atender por aqui. Pode ser?")
    assert r.handoff_aberto and len(_chamados(LOJA_A, "lead-l2b-04")) == 1
    r = _turno(LOJA_A, "lead-l2b-of", "Quer que eu chame um vendedor?")
    assert not r.handoff_aberto and _chamados(LOJA_A, "lead-l2b-of") == []


class GrafoFalso:
    def __init__(self, resposta):
        self.resposta = resposta

    def invoke(self, entrada, config=None):
        return {"messages": [HumanMessage(content=entrada["messages"][0].content),
                             AIMessage(content=self.resposta)]}


def _turno(loja_id, lead, resposta):
    from app.core.turno import executar_turno
    return asyncio.run(executar_turno(loja_id, "simulador", lead, "o carro tem laudo?",
                                      grafo=GrafoFalso(resposta)))


def _chamados(loja_id, lead):
    return _ler("SELECT motivo, estado FROM handoffs WHERE loja_id = ? AND lead_id = ?",
                (loja_id, lead))


PROMESSA = "Boa pergunta! Vou confirmar com a equipe e o pessoal vai falar com você por aqui."


def test_promessa_sem_chamado_abre_chamado_no_mesmo_turno(duas_lojas):
    r = _turno(LOJA_A, "lead-l2", PROMESSA)
    assert r.texto == PROMESSA                     # a resposta não muda
    assert r.handoff_aberto
    chamados = _chamados(LOJA_A, "lead-l2")
    assert len(chamados) == 1 and chamados[0]["estado"] == "aguardando_humano"
    assert _chamados(LOJA_B, "lead-l2") == []      # a loja B não vê nada


def test_resposta_sem_promessa_nao_abre_chamado(duas_lojas):
    r = _turno(LOJA_A, "lead-l2b", "O Civic tem laudo cautelar aprovado no cadastro. Quer ver fotos?")
    assert not r.handoff_aberto
    assert _chamados(LOJA_A, "lead-l2b") == []


def test_chamado_ja_aberto_nao_duplica(duas_lojas):
    from tools import acionar_handoff
    acionar_handoff.func(motivo="já aberto", resumo="r", lead_id="lead-l2c", loja_id=LOJA_A)
    _turno(LOJA_A, "lead-l2c", PROMESSA)
    chamados = _chamados(LOJA_A, "lead-l2c")
    assert len(chamados) == 1 and chamados[0]["motivo"] == "já aberto"


def test_mesmo_cliente_em_outra_loja_nao_herda_chamado(duas_lojas):
    from tools import acionar_handoff
    acionar_handoff.func(motivo="da loja A", resumo="r", lead_id="lead-l2d", loja_id=LOJA_A)
    _turno(LOJA_B, "lead-l2d", PROMESSA)
    assert len(_chamados(LOJA_B, "lead-l2d")) == 1
    assert _chamados(LOJA_A, "lead-l2d")[0]["motivo"] == "da loja A"

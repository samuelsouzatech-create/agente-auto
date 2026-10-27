"""
Separação do painel: cliente x operador (documento do analista). Duas lojas, sem rede.
Inclui o ponto 9: vendedor assume enquanto a IA pensa.
"""
import ast
import asyncio
import py_compile
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

import banco
from app import conhecimento, usuarios
from app.acesso import PainelSemLoja, loja_do_cliente
from app.config_tela import CAMPOS, campos_do, grupos_do
from app.core.turno import executar_turno
from app.estoque import OPCOES_CAMBIO, OPCOES_STATUS, adicionar_carro, listar_estoque
from app.handoff import assumir_conversa, listar_handoffs
from app.lojas import (
    CHAVES_DO_OPERADOR, ConfigInvalida, SemPermissao, carregar_loja, criar_loja,
    historico_config, salvar_config,
)
from app.mensagens import historico_do_lead, listar_conversas, listar_leads, salvar_mensagem
from app.resultados import OPCOES_RESULTADO, registrar_resultado, resultado_do_lead
from paginas.menu import CLIENTE, OPERADOR, arquivos
from tools import acionar_handoff

RAIZ = Path(__file__).resolve().parent.parent
PROIBIDOS_NO_CLIENTE = ("app.custos", "app.precos", "app.lojas_admin", "app.canais",
                        "paginas.operador_sessao")


@pytest.fixture
def loja_b():
    return criar_loja("Loja B")


# ============================================ regra no servidor
def test_cliente_nao_altera_modulo_nada_gravado(loja_b):
    for loja_id in (1, loja_b):
        antes = carregar_loja(loja_id)
        with pytest.raises(SemPermissao):
            salvar_config(loja_id, {"modulos.instagram": True}, "lojista", papel="cliente")
        depois = carregar_loja(loja_id)
        assert depois.get("modulos.instagram") is False
        assert depois.versao_config == antes.versao_config
        assert historico_config(loja_id) == []


def test_mudanca_misturada_do_cliente_e_recusada_inteira():
    with pytest.raises(SemPermissao):
        salvar_config(1, {"nome_agente": "Bia", "custos.teto_diario_llm": 50.0},
                      "lojista", papel="cliente")
    assert carregar_loja(1).get("nome_agente") == "Léo"


@pytest.mark.parametrize("chave", sorted(CHAVES_DO_OPERADOR))
def test_toda_chave_do_operador_e_recusada_para_o_cliente(chave):
    valor = {"custos.teto_diario_llm": 10.0, "remarketing.limite_mensal": 100,
             "instagram.limite_private_replies_h": 10}.get(chave, True)
    with pytest.raises(SemPermissao):
        salvar_config(1, {chave: valor}, "lojista", papel="cliente")


def test_operador_altera_e_fica_no_historico(loja_b):
    salvar_config(loja_b, {"modulos.instagram": True}, "Samuel", papel="operador")
    assert carregar_loja(loja_b).get("modulos.instagram") is True
    assert carregar_loja(1).get("modulos.instagram") is False
    ultimo = historico_config(loja_b)[0]
    assert (ultimo["chave"], ultimo["usuario"]) == ("modulos.instagram", "Samuel")


def test_cliente_altera_campo_do_cliente():
    salvar_config(1, {"financiamento.taxa_mensal": 0.022}, "lojista", papel="cliente")
    assert carregar_loja(1).get("financiamento.taxa_mensal") == 0.022


def test_papel_invalido_e_recusado():
    with pytest.raises(ConfigInvalida):
        salvar_config(1, {"nome_agente": "Bia"}, "x", papel="admin")


# ============================================ campos da tela
def test_campos_do_operador_batem_com_a_regra_do_servidor():
    assert {c.chave for c in CAMPOS if c.dono == "operador"} == set(CHAVES_DO_OPERADOR)
    assert all(c.dono in ("cliente", "operador") for c in CAMPOS)


def test_tela_do_cliente_nao_tem_campo_do_operador():
    chaves = {c.chave for c in campos_do("cliente")}
    assert not chaves & set(CHAVES_DO_OPERADOR)
    assert "Módulos" not in grupos_do("cliente")
    assert "Módulos" in grupos_do("operador")


# ============================================ LOJA_ID
@pytest.mark.parametrize("ambiente", [{}, {"LOJA_ID": ""}, {"LOJA_ID": "abc"},
                                      {"LOJA_ID": "0"}, {"LOJA_ID": "99"}])
def test_painel_do_cliente_sem_loja_valida_recusa(ambiente):
    with pytest.raises(PainelSemLoja):
        loja_do_cliente(ambiente)


def test_loja_desativada_recusa(loja_b):
    conexao = banco.conectar()
    conexao.execute("UPDATE lojas SET ativo = 0 WHERE id = ?", (loja_b,))
    conexao.commit()
    conexao.close()
    with pytest.raises(PainelSemLoja):
        loja_do_cliente({"LOJA_ID": str(loja_b)})
    assert loja_do_cliente({"LOJA_ID": " 1 "}) == 1


def test_entrada_do_cliente_exige_loja_e_nao_tem_seletor():
    fonte = (RAIZ / "painel.py").read_text(encoding="utf-8")
    assert "loja_do_cliente()" in fonte and "st.stop()" in fonte
    assert "escolher_loja" not in fonte and "operador_sessao" not in fonte


# ============================================ isolamento de dados
class IndiceFalso:
    def __init__(self):
        self.docs = {}

    def get(self, where):
        campo, valor = next(iter(where.items()))
        return {"ids": [i for i, (_, m) in self.docs.items() if m.get(campo) == valor]}

    def delete(self, ids):
        for i in ids:
            self.docs.pop(i, None)

    def add_texts(self, texts, metadatas, ids):
        for i, t, m in zip(ids, texts, metadatas):
            self.docs[i] = (t, m)


def test_com_loja_id_1_nada_da_loja_2_aparece(loja_b, monkeypatch):
    monkeypatch.setattr(conhecimento, "_indice", lambda: IndiceFalso())
    for loja_id, sufixo in ((1, "Um"), (loja_b, "Dois")):
        adicionar_carro(marca="Marca", modelo=f"Carro{sufixo}", ano=2020, km=1000, cor="Preto",
                        cambio=OPCOES_CAMBIO[0], preco=50000.0, status=OPCOES_STATUS[0],
                        fotos="", loja_id=loja_id)
        salvar_mensagem("5581", "cliente", f"oi da loja {sufixo}", canal="telegram", loja_id=loja_id)
        salvar_mensagem(f"so-{sufixo}", "cliente", "x", canal="telegram", loja_id=loja_id)
        acionar_handoff.func(motivo="m", resumo="r", lead_id=f"so-{sufixo}", loja_id=loja_id)
        usuarios.criar_usuario(loja_id, f"Vendedor{sufixo}", "vendedor")
        conhecimento.salvar_documento(loja_id, f"Doc{sufixo}", "texto")
        registrar_resultado(f"so-{sufixo}", OPCOES_RESULTADO[0], motivo="", vendedor="v",
                            loja_id=loja_id)

    loja = loja_do_cliente({"LOJA_ID": "1"})
    assert [c["modelo"] for c in listar_estoque(loja_id=loja, incluir_vendidos=True)] == ["CarroUm"]
    assert {c["lead_id"] for c in listar_conversas(loja)} == {"5581", "so-Um"}
    assert {l["lead_id"] for l in listar_leads(loja)} == {"5581", "so-Um"}
    assert [h["lead_id"] for h in listar_handoffs(loja_id=loja)] == ["so-Um"]
    assert [u["nome"] for u in usuarios.listar_usuarios(loja)] == ["VendedorUm"]
    assert [d["titulo"] for d in conhecimento.listar_documentos(loja)] == ["DocUm"]
    assert [m["conteudo"] for m in historico_do_lead("5581", loja)] == ["oi da loja Um"]
    assert historico_do_lead("so-Dois", loja) == []
    assert resultado_do_lead("so-Dois", loja_id=loja) is None


# ============================================ páginas
def _imports(caminho: Path) -> set[str]:
    nomes = set()
    for no in ast.walk(ast.parse(caminho.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            nomes |= {a.name for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes.add(no.module)
            nomes |= {f"{no.module}.{a.name}" for a in no.names}   # from app import custos
    return nomes


ARQUIVOS_CLIENTE = ["painel.py", "paginas/comum.py", "paginas/menu.py",
                    "paginas/form_config.py", *arquivos(CLIENTE)]


@pytest.mark.parametrize("arquivo", ARQUIVOS_CLIENTE)
def test_paginas_do_cliente_nao_importam_coisas_do_operador(arquivo):
    usados = _imports(RAIZ / arquivo)
    ruins = {n for n in usados for p in PROIBIDOS_NO_CLIENTE if n == p or n.startswith(p + ".")}
    assert not ruins, f"{arquivo} importa {ruins}"


def test_menus_nao_se_misturam():
    assert not set(arquivos(CLIENTE)) & set(arquivos(OPERADOR))
    assert {"paginas/custos.py", "paginas/lojas_canais.py", "paginas/plano.py"} == set(arquivos(OPERADOR))


@pytest.mark.parametrize("arquivo", arquivos(OPERADOR))
def test_telas_do_operador_se_protegem(arquivo):
    assert "exigir_operador()" in (RAIZ / arquivo).read_text(encoding="utf-8")


@pytest.mark.parametrize("arquivo", ["painel.py", "operador.py", "paginas/comum.py",
                                     "paginas/menu.py", "paginas/form_config.py",
                                     "paginas/operador_sessao.py", "paginas/plano.py",
                                     "paginas/configuracao.py", "paginas/custos.py",
                                     "paginas/lojas_canais.py"])
def test_arquivos_compilam(arquivo):
    py_compile.compile(str(RAIZ / arquivo), doraise=True)


# ============================================ ponto 9
class GrafoQueAssume:
    """Simula o vendedor clicando em Assumir enquanto a IA ainda pensa."""

    def invoke(self, entrada, config=None):
        assumir_conversa(entrada["lead_id"], "Carlos", loja_id=entrada["loja_id"])
        return {"messages": [*entrada["messages"], AIMessage(content="Resposta atrasada do Léo")]}


def test_vendedor_assume_enquanto_a_ia_pensa():
    r = asyncio.run(executar_turno(1, "telegram", "lead-corrida", "Entendi", grafo=GrafoQueAssume()))
    assert r.silenciado and r.texto is None
    assert [m["direcao"] for m in historico_do_lead("lead-corrida", 1)] == ["cliente"]

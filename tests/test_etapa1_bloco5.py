"""
Etapa 1, Bloco 5: telas de Configuração, Conhecimento, Usuários e Lojas/canais.
Testa a lógica (sem Streamlit) e garante que as páginas do painel compilam.
"""
import py_compile
from pathlib import Path

import pytest

from app import config_tela, conhecimento, lojas_admin, usuarios
from app.config_tela import campo, da_tela, mudancas_da_tela, para_tela
from app.lojas import EDITAVEIS, carregar_loja, criar_loja, historico_config, pendentes, salvar_config

RAIZ = Path(__file__).resolve().parent.parent


# ====================================================== Configuração
def test_toda_variavel_editavel_tem_campo_na_tela():
    assert {c.chave for c in config_tela.CAMPOS} == set(EDITAVEIS)


def test_todo_campo_tem_grupo_conhecido():
    assert all(c.grupo in config_tela.GRUPOS for c in config_tela.CAMPOS)


def test_ida_e_volta_da_tela_preserva_os_padroes():
    loja = carregar_loja(1)
    for c in config_tela.CAMPOS:
        valor = loja.get(c.chave)
        assert da_tela(c, para_tela(c, valor)) == valor, c.chave


def test_tela_sem_mudanca_nao_gera_mudanca():
    loja = carregar_loja(1)
    valores = {c.chave: para_tela(c, loja.get(c.chave)) for c in config_tela.CAMPOS}
    assert mudancas_da_tela(loja, valores) == ({}, [])


def test_confirmar_grupo_tira_a_marca_sem_mudar_valor():
    loja = carregar_loja(1)
    campos = [c for c in config_tela.CAMPOS if c.grupo == "Handoff"]
    valores = {c.chave: para_tela(c, loja.get(c.chave)) for c in campos}
    mudancas, _ = mudancas_da_tela(loja, valores, confirmar=True)
    salvar_config(1, mudancas, "teste")
    depois = carregar_loja(1)
    assert depois.get("handoff.reaviso_min") == 5
    assert not {c.chave for c in campos} & set(pendentes(depois))


def test_taxa_em_percentual_vira_fracao():
    taxa = campo("financiamento.taxa_mensal")
    assert da_tela(taxa, 2.5) == 0.025
    assert para_tela(taxa, 0.019) == 1.9


def test_listas_dias_e_opcionais():
    intervalos = campo("remarketing.intervalos_h")
    assert da_tela(intervalos, "48, 120 ,288") == [48, 120, 288]
    with pytest.raises(ValueError):
        da_tela(intervalos, "48, abc")
    limite = campo("remarketing.limite_mensal")
    assert da_tela(limite, "") is None
    assert da_tela(limite, "500") == 500
    posts = campo("instagram.posts_comentario")
    assert da_tela(posts, " Todos ") == "todos"
    assert da_tela(posts, "a1, b2") == ["a1", "b2"]
    assert da_tela(campo("remarketing.dias_envio"), ["Seg", "Sáb"]) == [0, 5]


def test_mudanca_real_salva_e_vai_para_o_historico():
    loja = carregar_loja(1)
    mudancas, erros = mudancas_da_tela(loja, {"financiamento.taxa_mensal": 2.2})
    assert erros == [] and mudancas == {"financiamento.taxa_mensal": 0.022}
    salvar_config(1, mudancas, "Samuel")
    assert carregar_loja(1).get("financiamento.taxa_mensal") == 0.022
    ultimo = historico_config(1)[0]
    assert ultimo["chave"] == "financiamento.taxa_mensal" and ultimo["usuario"] == "Samuel"


def test_erro_de_digitacao_vira_mensagem_com_rotulo():
    loja = carregar_loja(1)
    c = campo("remarketing.intervalos_h")
    mudancas, erros = mudancas_da_tela(loja, {c.chave: "48, x"})
    assert mudancas == {} and erros[0].startswith(c.rotulo)


def test_traduzir_erro_troca_chave_por_rotulo():
    msg = "remarketing.max_toques: precisa estar entre 1 e 3"
    assert config_tela.traduzir_erro(msg) == "Máximo de toques por lead: precisa estar entre 1 e 3"


# ====================================================== Usuários
def test_usuario_aparece_so_na_sua_loja():
    loja2 = criar_loja("Loja Dois")
    usuarios.criar_usuario(1, "Ana", "vendedor", contato_telegram="123456789")
    usuarios.criar_usuario(loja2, "Bruno", "gestor")
    assert [u["nome"] for u in usuarios.listar_usuarios(1)] == ["Ana"]
    assert [u["nome"] for u in usuarios.listar_usuarios(loja2)] == ["Bruno"]


def test_loja_nao_altera_usuario_de_outra():
    loja2 = criar_loja("Loja Dois")
    uid = usuarios.criar_usuario(1, "Ana", "vendedor")
    assert usuarios.definir_ativo(uid, loja2, False) is False
    assert usuarios.atualizar_usuario(uid, loja2, "Intruso", "gestor") is False
    assert usuarios.listar_usuarios(1)[0]["nome"] == "Ana"


def test_validacoes_de_usuario():
    for argumentos in [
        dict(loja_id=1, nome="", papel="vendedor"),
        dict(loja_id=1, nome="Ana", papel="operador"),
        dict(loja_id=1, nome="Ana", papel="vendedor", contato_telegram="@ana"),
        dict(loja_id=1, nome="Ana", papel="vendedor", contato_whatsapp="123"),
        dict(loja_id=99, nome="Ana", papel="vendedor"),
    ]:
        with pytest.raises(usuarios.UsuarioInvalido):
            usuarios.criar_usuario(**argumentos)


def test_whatsapp_fica_so_com_digitos():
    usuarios.criar_usuario(1, "Ana", "vendedor", contato_whatsapp="+55 (81) 99999-8888")
    assert usuarios.listar_usuarios(1)[0]["contato_whatsapp"] == "5581999998888"


def test_desativado_sai_da_lista_e_dos_avisos():
    uid = usuarios.criar_usuario(1, "Ana", "vendedor", contato_telegram="123456789")
    usuarios.criar_usuario(1, "Caio", "vendedor")
    assert [u["nome"] for u in usuarios.contatos_para_aviso(1)] == ["Ana"]
    usuarios.definir_ativo(uid, 1, False)
    assert usuarios.contatos_para_aviso(1) == []
    assert [u["nome"] for u in usuarios.listar_usuarios(1)] == ["Caio"]
    assert len(usuarios.listar_usuarios(1, incluir_inativos=True)) == 2


# ====================================================== Conhecimento
class IndiceFalso:
    """Imita o pedaço do Chroma que usamos: get(where), delete(ids), add_texts."""

    def __init__(self):
        self.docs = {}

    def get(self, where):
        campo_, valor = next(iter(where.items()))
        return {"ids": [i for i, (_, m) in self.docs.items() if m.get(campo_) == valor]}

    def delete(self, ids):
        for i in ids:
            self.docs.pop(i, None)

    def add_texts(self, texts, metadatas, ids):
        for i, t, m in zip(ids, texts, metadatas):
            self.docs[i] = (t, m)


@pytest.fixture
def indice(monkeypatch):
    falso = IndiceFalso()
    monkeypatch.setattr(conhecimento, "_indice", lambda: falso)
    return falso


def test_salvar_grava_e_indexa_com_a_loja(indice):
    doc = conhecimento.salvar_documento(1, "Troca", "Aceitamos troca com até 10 anos.")
    assert conhecimento.listar_documentos(1)[0]["titulo"] == "Troca"
    metas = [m for _, m in indice.docs.values()]
    assert metas and all(m["loja_id"] == 1 and m["documento_id"] == f"doc:{doc}" for m in metas)


def test_editar_substitui_os_pedacos_antigos(indice):
    doc = conhecimento.salvar_documento(1, "Garantia", "A" * 1200)
    assert len(indice.docs) > 1
    conhecimento.salvar_documento(1, "Garantia", "Garantia de 3 meses.", doc_id=doc)
    assert [t for t, _ in indice.docs.values()] == ["Garantia de 3 meses."]


def test_documentos_nao_cruzam_lojas(indice):
    loja2 = criar_loja("Loja Dois")
    d1 = conhecimento.salvar_documento(1, "Troca", "Loja 1 aceita troca.")
    conhecimento.salvar_documento(loja2, "Troca", "Loja 2 não aceita troca.")
    assert [d["texto"] for d in conhecimento.listar_documentos(loja2)] == ["Loja 2 não aceita troca."]
    with pytest.raises(LookupError):
        conhecimento.salvar_documento(loja2, "X", "y", doc_id=d1)
    assert conhecimento.apagar_documento(loja2, d1) is False
    assert len(conhecimento.listar_documentos(1)) == 1


def test_apagar_remove_do_banco_e_do_indice(indice):
    doc = conhecimento.salvar_documento(1, "Horário", "Seg a sáb, 9h às 18h.")
    assert conhecimento.apagar_documento(1, doc) is True
    assert conhecimento.listar_documentos(1) == [] and indice.docs == {}


def test_falha_ao_indexar_nao_perde_o_texto(monkeypatch):
    def quebrado():
        raise RuntimeError("sem chave da API")
    monkeypatch.setattr(conhecimento, "_indice", quebrado)
    with pytest.raises(conhecimento.ErroIndexacao):
        conhecimento.salvar_documento(1, "Troca", "Aceitamos troca.")
    assert conhecimento.listar_documentos(1)[0]["titulo"] == "Troca"


def test_documento_invalido(indice):
    with pytest.raises(conhecimento.DocumentoInvalido):
        conhecimento.salvar_documento(1, "", "texto")
    with pytest.raises(conhecimento.DocumentoInvalido):
        conhecimento.salvar_documento(1, "Título", "   ")


def test_importar_txts_respeita_loja_e_nao_sobrescreve(tmp_path, monkeypatch, indice):
    import ingestao_rag
    (tmp_path / "troca.txt").write_text("Loja 1 aceita troca.", encoding="utf-8")
    (tmp_path / "loja_7").mkdir()
    (tmp_path / "loja_7" / "x.txt").write_text("loja inexistente", encoding="utf-8")
    monkeypatch.setattr(ingestao_rag, "PASTA_CONHECIMENTO", str(tmp_path))

    assert ingestao_rag.importar_txts() == 1
    doc = conhecimento.listar_documentos(1)[0]
    conhecimento.salvar_documento(1, "troca", "Texto editado na tela.", doc_id=doc["id"])
    assert ingestao_rag.importar_txts() == 0
    assert conhecimento.listar_documentos(1)[0]["texto"] == "Texto editado na tela."


# ====================================================== Lojas
def test_renomear_loja():
    assert lojas_admin.renomear_loja(1, "Auto Center Recife") is True
    assert lojas_admin.listar_lojas()[0]["nome"] == "Auto Center Recife"
    assert carregar_loja(1).nome == "Auto Center Recife"
    with pytest.raises(ValueError):
        lojas_admin.renomear_loja(1, "   ")
    assert lojas_admin.renomear_loja(99, "X") is False


# ====================================================== Páginas
ARQUIVOS_DO_PAINEL = [
    "painel.py", "paginas/comum.py", "paginas/handoff.py", "paginas/estoque.py",
    "paginas/resultados.py", "paginas/configuracao.py", "paginas/conhecimento.py",
    "paginas/usuarios.py", "paginas/lojas_canais.py",
]


@pytest.mark.parametrize("arquivo", ARQUIVOS_DO_PAINEL)
def test_paginas_do_painel_compilam(arquivo):
    """Pega erro de colagem (indentação, parêntese) antes de abrir o Streamlit."""
    py_compile.compile(str(RAIZ / arquivo), doraise=True)

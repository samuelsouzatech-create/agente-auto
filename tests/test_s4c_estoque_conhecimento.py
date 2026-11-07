"""
S4c (Fase 3): Estoque e Conhecimento na Configuração do operador, e o O9.
- O9: a busca reabre o índice quando o arquivo muda (limpando o cache) e
  tenta de novo depois de erro;
- carros e documentos: Registro com o ator, conflito, Desfazer, duas lojas;
- nada de "vendido" manual; ingestao_rag.py sem loja padrão;
- a tela abre e grava (AppTest); as telas antigas continuam abrindo.
Tudo offline: índice falso, banco temporário do conftest.
"""
import importlib
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from banco import conectar
from app import conhecimento, estoque, lojas_admin
from app.ator import AtorInvalido, SemAtor, como, sem_ator
from app.config_assunto import DesfazerRecusado, NadaParaDesfazer
from app.estoque_conhecimento import (
    desfazer_ultima, documentos_da_loja, estoque_da_loja, o_que_desfazer, ultima_alteracao,
)
from app.registro_leitura import filtrar_registro
from app.registro_tela import linhas_do_registro

RAIZ = Path(__file__).resolve().parent.parent
TELA = RAIZ / "paginas" / "operador" / "configuracao.py"


class IndiceFalso:
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


@pytest.fixture(autouse=True)
def indice(monkeypatch):
    falso = IndiceFalso()
    monkeypatch.setattr(conhecimento, "_indice", lambda: falso)
    return falso


def _loja_b():
    return lojas_admin.criar_loja("Loja B", "Caruaru", "America/Recife", "veiculos")


def _detalhes(loja, acao):
    return [l["Detalhe"] for l in linhas_do_registro(filtrar_registro(loja, acao=acao),
                                                      com_loja=False)]


def _carro(loja=1, preco=62000.0):
    return estoque.adicionar_carro("Fiat", "Argo", 2021, 30000, "Prata", "Manual", preco,
                                   loja_id=loja)


def _editar(carro, loja=1, preco=59000.0, status="disponivel", esperado=None):
    return estoque.atualizar_carro(carro, "Fiat", "Argo", 2021, 30000, "Prata", "Manual", preco,
                                   status, "", loja_id=loja, esperado=esperado)


# ------------------------------------------------------------ O9

@pytest.fixture
def busca_falsa(monkeypatch, tmp_path):
    busca = importlib.import_module("tools.buscar_conhecimento")
    estado = {"aberturas": 0, "limpezas": 0, "falhar_primeira": False}

    class ChromaFalso:
        def __init__(self, **opcoes):
            estado["aberturas"] += 1
            self.falhar = estado["falhar_primeira"] and estado["aberturas"] == 1

        def similarity_search(self, pergunta, k, filter):
            if self.falhar:
                raise RuntimeError("Error finding id")
            return []

    def limpar():
        estado["limpezas"] += 1

    monkeypatch.setattr(busca, "PASTA_CHROMA", str(tmp_path))
    monkeypatch.setattr(busca, "Chroma", ChromaFalso)
    monkeypatch.setattr(busca, "GoogleGenerativeAIEmbeddings", lambda **k: None)
    monkeypatch.setattr(busca, "_limpar_cache_chroma", limpar)
    monkeypatch.setattr(busca, "_banco_conhecimento", None)
    monkeypatch.setattr(busca, "_assinatura_aberta", None)
    return busca, estado, tmp_path


def test_reabre_e_limpa_o_cache_quando_o_indice_muda(busca_falsa):
    busca, estado, pasta = busca_falsa
    arquivo = pasta / "chroma.sqlite3"
    arquivo.write_bytes(b"1")
    busca._get_banco_conhecimento()
    busca._get_banco_conhecimento()
    assert (estado["aberturas"], estado["limpezas"]) == (1, 0)
    arquivo.write_bytes(b"22")
    info = arquivo.stat()
    os.utime(arquivo, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))
    busca._get_banco_conhecimento()
    assert (estado["aberturas"], estado["limpezas"]) == (2, 1)


def test_busca_com_erro_reabre_e_tenta_de_novo(busca_falsa):
    busca, estado, _ = busca_falsa
    estado["falhar_primeira"] = True
    resposta = busca.buscar_conhecimento.func("troca", loja_id=1)
    assert resposta == "Não encontrei essa informação nas políticas da loja."
    assert estado["aberturas"] == 2


# ------------------------------------------------------------ estoque

def test_carro_cadastrar_e_alterar_no_registro():
    c = _carro()
    _editar(c)
    assert _detalhes(1, "cadastrar_carro") == ["Fiat Argo 2021 · Disponível · R$ 62.000,00"]
    assert _detalhes(1, "alterar_carro") == ["Fiat Argo 2021 · Preço: R$ 62.000,00 → R$ 59.000,00"]
    assert ultima_alteracao(1, "Estoque")["quem"] == "Teste"


def test_salvar_carro_sem_mudar_nao_registra():
    c = _carro()
    _editar(c, preco=62000.0)
    assert _detalhes(1, "alterar_carro") == []


def test_vendido_manual_continua_proibido():
    with pytest.raises(estoque.StatusInvalido):
        estoque.adicionar_carro("Fiat", "Argo", 2021, 1, "Prata", "Manual", 1.0,
                                status="vendido", loja_id=1)
    c = _carro()
    with pytest.raises(estoque.StatusInvalido):
        _editar(c, status="vendido")
    assert _detalhes(1, "alterar_carro") == []


def test_conflito_no_carro():
    c = _carro()
    visto = estoque_da_loja(1)[0]["versao"]
    _editar(c, preco=60000.0)
    with pytest.raises(estoque.CarroMudou):
        _editar(c, preco=55000.0, esperado=visto)
    assert estoque.buscar_carro(c, 1)["preco"] == 60000.0


def test_desfazer_volta_a_ultima_edicao_do_carro():
    c = _carro()
    _editar(c)
    assert "R$ 59.000,00 → R$ 62.000,00" in o_que_desfazer(1, "Estoque")["texto"]
    desfazer_ultima(1, "Estoque")
    assert estoque.buscar_carro(c, 1)["preco"] == 62000.0


def test_cadastro_nao_se_desfaz():
    _carro()
    assert o_que_desfazer(1, "Estoque") is None
    with pytest.raises(NadaParaDesfazer):
        desfazer_ultima(1, "Estoque")


def test_desfazer_carro_recusa_se_mudou_por_fora():
    c = _carro()
    _editar(c)
    conexao = conectar()
    try:
        conexao.execute("UPDATE estoque SET preco = 1 WHERE id = ?", (c,))
        conexao.commit()
    finally:
        conexao.close()
    with pytest.raises(DesfazerRecusado):
        desfazer_ultima(1, "Estoque")
    assert estoque.buscar_carro(c, 1)["preco"] == 1


def test_duas_lojas_no_estoque():
    b = _loja_b()
    cb = _carro(b)
    assert _editar(cb, loja=1) == "Carro não encontrado nesta loja."
    assert estoque_da_loja(1) == []
    with como("Ana", "cliente", "painel", loja_id=1):
        with pytest.raises(AtorInvalido):
            _carro(b)


def test_carro_sem_ator_nada_grava():
    with sem_ator(), pytest.raises(SemAtor):
        _carro()
    assert estoque.listar_estoque(1) == []


# ------------------------------------------------------------ conhecimento

def test_documento_criar_alterar_apagar_no_registro():
    d = conhecimento.salvar_documento(1, "Troca", "Aceitamos troca.")
    conhecimento.salvar_documento(1, "Troca", "Não aceitamos troca.", d)
    conhecimento.apagar_documento(1, d)
    assert _detalhes(1, "criar_documento") == ["Troca · criado"]
    assert _detalhes(1, "alterar_documento") == ["Troca · texto alterado"]
    assert _detalhes(1, "apagar_documento") == ["Troca · apagado"]
    assert ultima_alteracao(1, "Conhecimento")["quem"] == "Teste"


def test_conflito_no_documento():
    d = conhecimento.salvar_documento(1, "Troca", "Aceitamos troca.")
    visto = documentos_da_loja(1)[0]["versao"]
    conhecimento.salvar_documento(1, "Troca", "Texto da Ana.", d)
    with pytest.raises(conhecimento.DocumentoMudou):
        conhecimento.salvar_documento(1, "Troca", "Texto meu.", d, esperado=visto)
    with pytest.raises(conhecimento.DocumentoMudou):
        conhecimento.apagar_documento(1, d, esperado=visto)
    assert conhecimento.listar_documentos(1)[0]["texto"] == "Texto da Ana."


def test_desfazer_alteracao_volta_o_texto():
    d = conhecimento.salvar_documento(1, "Troca", "Aceitamos troca.")
    conhecimento.salvar_documento(1, "Troca", "Não aceitamos troca.", d)
    desfazer_ultima(1, "Conhecimento")
    assert conhecimento.listar_documentos(1)[0]["texto"] == "Aceitamos troca."


def test_desfazer_apagar_traz_o_documento_de_volta(indice):
    d = conhecimento.salvar_documento(1, "Troca", "Aceitamos troca.")
    conhecimento.apagar_documento(1, d)
    assert indice.docs == {}
    desfazer_ultima(1, "Conhecimento")
    docs = conhecimento.listar_documentos(1)
    assert [(x["titulo"], x["texto"]) for x in docs] == [("Troca", "Aceitamos troca.")]
    assert indice.docs


def test_duas_lojas_no_conhecimento(indice):
    b = _loja_b()
    conhecimento.salvar_documento(1, "A", "Loja 1.")
    d = conhecimento.salvar_documento(b, "B", "Loja B.")
    assert conhecimento.apagar_documento(1, d) is False
    assert [x["titulo"] for x in documentos_da_loja(1)] == ["A"]
    with como("Ana", "cliente", "painel", loja_id=1):
        with pytest.raises(AtorInvalido):
            conhecimento.salvar_documento(b, "X", "y")
    assert conhecimento.reindexar_loja(1) == 1
    assert {m["loja_id"] for _, m in indice.docs.values()} == {1, b}


# ------------------------------------------------------------ ingestao_rag

def test_ingestao_sem_loja_padrao():
    assert "LOJA_PADRAO" not in (RAIZ / "ingestao_rag.py").read_text(encoding="utf-8")


def test_ingestao_exige_a_loja():
    import ingestao_rag
    with pytest.raises(SystemExit):
        ingestao_rag.main([])


def test_txt_solto_nao_vai_para_loja_nenhuma(tmp_path, monkeypatch):
    import ingestao_rag
    (tmp_path / "solto.txt").write_text("sem loja", encoding="utf-8")
    (tmp_path / "loja_1").mkdir()
    (tmp_path / "loja_1" / "garantia.txt").write_text("90 dias.", encoding="utf-8")
    monkeypatch.setattr(ingestao_rag, "PASTA_CONHECIMENTO", str(tmp_path))
    assert ingestao_rag.soltos() == ["solto.txt"]
    assert ingestao_rag.importar_txts(1) == 1
    assert [d["titulo"] for d in conhecimento.listar_documentos(1)] == ["garantia"]
    with pytest.raises(ValueError):
        ingestao_rag.importar_txts(99)


# ------------------------------------------------------------ tela

@pytest.fixture
def nome_operador(monkeypatch):
    monkeypatch.setenv("OPERADOR_NOME", "Samuel Tela")


def _abrir(assunto):
    at = AppTest.from_file(str(TELA), default_timeout=30)
    at.session_state["_papel"] = "operador"
    at.session_state["loja_id"] = 1
    at.run()
    at.radio(key="config_assunto").set_value(assunto).run()
    assert not at.exception, at.exception
    return at


def test_tela_estoque_cadastra_carro(nome_operador):
    at = _abrir("Estoque")
    for rotulo, valor in (("Marca", "Fiat"), ("Modelo", "Argo"), ("Cor", "Prata")):
        next(t for t in at.text_input if str(t.label) == rotulo).set_value(valor)
    next(b for b in at.button if str(b.label) == "💾 Cadastrar carro").click().run()
    assert not at.exception, at.exception
    assert [c["titulo"] for c in estoque_da_loja(1)] == ["Fiat Argo 2020"]
    linhas = linhas_do_registro(filtrar_registro(1, acao="cadastrar_carro"), com_loja=False)
    assert linhas[0]["Quem"] == "Samuel Tela"


def test_tela_conhecimento_abre_com_documento(nome_operador):
    conhecimento.salvar_documento(1, "Troca", "Aceitamos troca.")
    at = _abrir("Conhecimento")
    assert any(s.value == "Conhecimento" for s in at.subheader)


def test_telas_novas_sem_texto_tecnico():
    for nome in ("paginas/operador/config_estoque.py", "paginas/operador/config_conhecimento.py",
                 "app/estoque_conhecimento.py"):
        texto = (RAIZ / nome).read_text(encoding="utf-8")
        for proibido in ("ingestao_rag", "reinicie", ".env", "python "):
            assert proibido not in texto, (nome, proibido)


def test_telas_antigas_continuam_abrindo(nome_operador):
    for arquivo in ("estoque.py", "conhecimento.py"):
        for papel in ("cliente", "operador"):
            at = AppTest.from_file(str(RAIZ / "paginas" / arquivo), default_timeout=30)
            at.session_state["_papel"] = papel
            at.session_state["_loja_cliente"] = 1
            at.session_state["loja_id"] = 1
            at.run()
            assert not at.exception, (arquivo, papel, at.exception)

"""
S7 (Fase 3): Base de clientes.
- A tela é só uma camada sobre app/importacao.py (que não muda): três
  indicadores, planilha modelo, arquivo, prévia sem gravar, confirmação.
- E2-2: aviso "nada é enviado" e declaração da LOJA antes do Importar;
  quem declarou e quando ficam gravados; sem declaração a importação continua.
- Histórico com Desfazer: pede confirmação (decisão 1B), vai para o
  Registro e não desfaz duas vezes.
- Lojas separadas e horário no fuso da loja.
Tudo offline. O campo de arquivo é trocado por um arquivo falso no teste.
"""
import ast
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from banco import conectar
from app.importacao import (
    ImportacaoInvalida, desfazer_importacao, importar, ler_planilha, listar_importacoes,
    resumo_da_base,
)
from app.lojas import carregar_loja, criar_loja
from app.relogio import hora_local
from paginas.menu import LOJA, OPERADOR, arquivos

RAIZ = Path(__file__).resolve().parent.parent
TELA = RAIZ / "paginas" / "operador" / "base_clientes.py"
HOJE = date(2026, 10, 30)
INSTANTE = datetime(2025, 3, 10, 15, 0, tzinfo=timezone.utc)

# Linha 2: contato com compra. Linha 3: compra sem data (aviso). Linha 4: sem telefone (recusada).
CSV = ("nome;telefone;carro;data_compra;pagamento;meses\n"
       "Ana Teste;(81) 99999-8888;Honda Civic 2019;15/03/2025;financiado;48\n"
       "Carlos Teste;(81) 98888-7777;Gol 2018;;;\n"
       "Sem Fone;;Onix 2020;10/01/2024;à vista;\n")


# ---------------------------------------------------------------- apoio

class ArquivoFalso:
    """Faz o papel do arquivo escolhido no campo de upload."""

    def __init__(self, texto, nome="base_teste.csv"):
        self.name = nome
        self._dados = texto.encode("utf-8-sig")

    def getvalue(self):
        return self._dados


def _um(sql, parametros=()):
    conexao = conectar()
    try:
        return conexao.execute(sql, parametros).fetchone()[0]
    finally:
        conexao.close()


def _linhas(sql, parametros=()):
    conexao = conectar()
    try:
        return [dict(l) for l in conexao.execute(sql, parametros).fetchall()]
    finally:
        conexao.close()


def _importar_direto(loja_id, usuario="Ana", arquivo="base_ana.csv", consentimento=False,
                     agora=None):
    previa = ler_planilha(CSV.encode("utf-8-sig"), hoje=HOJE)
    return importar(loja_id, previa, usuario=usuario, consentimento=consentimento,
                    arquivo=arquivo, agora=agora)


def _abrir(loja_id, monkeypatch, csv=None):
    monkeypatch.setenv("OPERADOR_NOME", "Teste")
    if csv is not None:
        monkeypatch.setattr(st, "file_uploader", lambda *a, **k: ArquivoFalso(csv))
    at = AppTest.from_file(str(TELA), default_timeout=30)
    at.session_state["_papel"] = "operador"
    at.session_state["loja_id"] = loja_id
    return at.run()


def _textos(at):
    blocos = list(at.info) + list(at.warning) + list(at.success) + list(at.error) + \
        list(at.caption) + list(at.markdown)
    return " ".join(str(b.value) for b in blocos)


def _tabelas(at):
    return [d.value for d in at.dataframe]


def _historico(at):
    return next((t for t in _tabelas(at) if "Quem importou" in t.columns), None)


def _metricas(at):
    return {m.label: str(m.value) for m in at.metric}


@pytest.fixture
def loja():
    return criar_loja("Loja S7")


@pytest.fixture
def outra():
    return criar_loja("Outra loja S7")


# ---------------------------------------------------------------- abrir

def test_tela_recusa_quem_nao_e_operador():
    at = AppTest.from_file(str(TELA), default_timeout=30).run()
    assert not at.exception
    assert any("só do operador" in e.value for e in at.error)
    assert len(at.title) == 0


def test_tela_abre_para_o_operador(loja, monkeypatch):
    at = _abrir(loja, monkeypatch)
    assert not at.exception, at.exception
    assert len(at.title) == 1 and "Base de clientes" in at.title[0].value


def test_tres_indicadores_da_base(loja, monkeypatch):
    _importar_direto(loja, consentimento=True)
    at = _abrir(loja, monkeypatch)
    m = _metricas(at)
    assert m["Contatos na base"] == "2"
    assert m["Com autorização"] == "2"
    assert m["Compras anteriores"] == "1"


def test_planilha_modelo_para_baixar(loja, monkeypatch):
    at = _abrir(loja, monkeypatch)
    assert len(at.get("download_button")) == 1
    fonte = TELA.read_text(encoding="utf-8")
    assert "importacao.MODELO_CSV" in fonte and "utf-8-sig" in fonte


def test_campo_para_escolher_o_arquivo(loja, monkeypatch):
    at = _abrir(loja, monkeypatch)
    assert len(at.get("file_uploader")) == 1


# ---------------------------------------------------------------- prévia

def test_previa_aparece_e_nao_grava(loja, monkeypatch):
    at = _abrir(loja, monkeypatch, CSV)
    assert not at.exception, at.exception
    assert any("Prévia" in s.value for s in at.subheader)
    m = _metricas(at)
    assert (m["Linhas lidas"], m["Contatos"], m["Compras"], m["Recusadas"]) == ("3", "2", "1", "1")
    assert resumo_da_base(loja) == {"contatos": 0, "com_consentimento": 0, "compras": 0}
    assert listar_importacoes(loja) == []


def test_previa_mostra_linhas_recusadas_com_motivo(loja, monkeypatch):
    at = _abrir(loja, monkeypatch, CSV)
    recusadas = next(t for t in _tabelas(at) if "Motivo" in t.columns)
    assert list(recusadas["Linha"]) == [4]
    assert "Sem telefone" in recusadas.to_string()


def test_previa_mostra_avisos(loja, monkeypatch):
    at = _abrir(loja, monkeypatch, CSV)
    avisos = next(t for t in _tabelas(at) if "Aviso" in t.columns)
    assert "Compra sem data" in avisos.to_string()


def test_planilha_invalida_mostra_erro_e_nao_quebra(loja, monkeypatch):
    at = _abrir(loja, monkeypatch, "nome;email\nAna;a@b.com\n")
    assert not at.exception, at.exception
    assert any("telefone" in e.value for e in at.error)
    assert not any("Prévia" in s.value for s in at.subheader)


# ---------------------------------------------------------------- confirmação (E2-2)

def test_aviso_nada_enviado_e_declaracao_da_loja(loja, monkeypatch):
    at = _abrir(loja, monkeypatch, CSV)
    assert any("Nada é enviado a ninguém nesta tela" in i.value for i in at.info)
    assert any("A loja declara" in w.value and "responsável" in w.value for w in at.warning)
    assert any("em nome da loja" in c.label for c in at.checkbox)


def test_importar_com_autorizacao_grava_quem_e_quando(loja, monkeypatch):
    at = _abrir(loja, monkeypatch, CSV)
    at.checkbox(key="s7_consentimento_0").check()
    at.button(key="s7_importar").click().run()
    assert not at.exception, at.exception
    assert any("Importação feita" in s.value for s in at.success)
    contatos = _linhas("SELECT * FROM contatos WHERE loja_id = ?", (loja,))
    assert len(contatos) == 2
    assert all(c["consentimento"] == 1 and c["consentimento_por"] == "Teste"
               and c["consentimento_em"] for c in contatos)
    imp = listar_importacoes(loja)[0]
    assert imp["usuario"] == "Teste" and imp["consentimento"] == 1
    assert imp["arquivo"] == "base_teste.csv"
    assert _um("SELECT pessoa FROM registro_acoes WHERE loja_id = ? AND acao = 'importar_base'",
               (loja,)) == "Teste"


def test_importar_sem_autorizacao_continua_possivel_e_nao_autoriza(loja, monkeypatch):
    at = _abrir(loja, monkeypatch, CSV)
    at.button(key="s7_importar").click().run()
    assert not at.exception, at.exception
    assert resumo_da_base(loja) == {"contatos": 2, "com_consentimento": 0, "compras": 1}
    contatos = _linhas("SELECT * FROM contatos WHERE loja_id = ?", (loja,))
    assert all(c["consentimento_por"] is None and c["consentimento_em"] is None for c in contatos)


def test_reimportar_sem_autorizacao_nao_tira_a_autorizacao(loja, monkeypatch):
    _importar_direto(loja, consentimento=True)
    at = _abrir(loja, monkeypatch, CSV)
    at.button(key="s7_importar").click().run()
    assert resumo_da_base(loja)["com_consentimento"] == 2


# ---------------------------------------------------------------- histórico e desfazer

def test_historico_mostra_as_importacoes_da_loja(loja, monkeypatch):
    _importar_direto(loja, usuario="Ana", arquivo="base_ana.csv", consentimento=True)
    at = _abrir(loja, monkeypatch)
    tabela = _historico(at)
    assert tabela is not None
    texto = tabela.to_string()
    assert "base_ana.csv" in texto and "Ana" in texto and "Declarada" in texto
    assert "Valendo" in texto


def test_desfazer_so_aparece_quando_pode(loja, monkeypatch):
    at = _abrir(loja, monkeypatch)
    assert "s7_desfazer" not in [b.key for b in at.button]
    r = _importar_direto(loja)
    at = _abrir(loja, monkeypatch)
    assert "s7_desfazer" in [b.key for b in at.button]
    desfazer_importacao(loja, r["importacao_id"])
    at = _abrir(loja, monkeypatch)
    assert "s7_desfazer" not in [b.key for b in at.button]
    assert "Desfeita" in _historico(at).to_string()


def test_desfazer_pede_confirmacao_vai_ao_registro_e_nao_repete(loja, monkeypatch):
    r = _importar_direto(loja)
    at = _abrir(loja, monkeypatch)
    assert at.button(key="s7_desfazer").disabled          # sem a caixinha: botão travado
    assert listar_importacoes(loja)[0]["desfeita_em"] is None
    at.checkbox(key="s7_desfazer_conf_0").check().run()
    at.button(key="s7_desfazer").click().run()
    assert not at.exception, at.exception
    assert any("Importação desfeita" in s.value for s in at.success)
    assert listar_importacoes(loja)[0]["desfeita_em"]
    assert resumo_da_base(loja)["contatos"] == 0
    assert "s7_desfazer" not in [b.key for b in at.button]
    assert _um("SELECT pessoa FROM registro_acoes WHERE loja_id = ? "
               "AND acao = 'desfazer_importacao'", (loja,)) == "Teste"
    with pytest.raises(ImportacaoInvalida):
        desfazer_importacao(loja, r["importacao_id"])


# ---------------------------------------------------------------- lojas e horário

def test_lojas_nao_se_misturam(loja, outra, monkeypatch):
    _importar_direto(loja, arquivo="base_da_loja_a.csv")
    at = _abrir(outra, monkeypatch)
    assert _metricas(at)["Contatos na base"] == "0"
    assert _historico(at) is None
    assert any("Nenhuma importação" in i.value for i in at.info)

    _importar_direto(outra, arquivo="base_da_loja_b.csv")
    at = _abrir(loja, monkeypatch)
    texto = _historico(at).to_string()
    assert "base_da_loja_a.csv" in texto and "base_da_loja_b.csv" not in texto
    at.checkbox(key="s7_desfazer_conf_0").check().run()
    at.button(key="s7_desfazer").click().run()
    assert listar_importacoes(outra)[0]["desfeita_em"] is None
    assert resumo_da_base(outra)["contatos"] == 2


def test_horario_no_fuso_da_loja(loja, monkeypatch):
    _importar_direto(loja, agora=INSTANTE)
    esperado = hora_local(carregar_loja(loja), INSTANTE).strftime("%d/%m/%Y %H:%M")
    assert esperado != "10/03/2025 15:00"                 # a loja não está no horário do banco
    at = _abrir(loja, monkeypatch)
    quando = list(_historico(at)["Quando"])
    assert quando == [esperado]
    assert "UTC" not in _textos(at)


# ---------------------------------------------------------------- nada é enviado

def test_nenhuma_mensagem_sai_pela_tela(loja, monkeypatch):
    at = _abrir(loja, monkeypatch, CSV)
    at.checkbox(key="s7_consentimento_0").check()
    at.button(key="s7_importar").click().run()
    assert resumo_da_base(loja)["contatos"] == 2
    assert _um("SELECT COUNT(*) FROM mensagens WHERE loja_id = ?", (loja,)) == 0
    assert _um("SELECT COUNT(*) FROM remarketing_envios WHERE loja_id = ?", (loja,)) == 0


def test_tela_nao_importa_nada_de_envio():
    arvore = ast.parse(TELA.read_text(encoding="utf-8"))
    modulos = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            modulos |= {a.name for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module:
            modulos.add(no.module)
    proibidos = ("envio", "channels", "jobs", "reativacao", "base_pos_venda", "whatsapp",
                 "telegram", "banco", "sqlite3", "csv")
    assert not [m for m in modulos if any(p in m for p in proibidos)], modulos


# ---------------------------------------------------------------- regras existentes

def test_tela_so_chama_a_importacao_que_ja_existe():
    fonte = TELA.read_text(encoding="utf-8")
    for funcao in ("importacao.resumo_da_base(", "importacao.ler_planilha(",
                   "importacao.importar(", "importacao.listar_importacoes(",
                   "importacao.desfazer_importacao("):
        assert funcao in fonte, funcao
    assert "conectar(" not in fonte and "registrar(" not in fonte
    assert "exigir_operador()" in fonte and "definir_ator_da_sessao()" in fonte


def test_tela_antiga_continua_no_menu():
    assert "paginas/importar_base.py" in arquivos(OPERADOR)
    assert "paginas/operador/base_clientes.py" in arquivos(LOJA)

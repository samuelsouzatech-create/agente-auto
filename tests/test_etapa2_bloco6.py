"""
Testes da Etapa 2, Bloco 6A: importação da base da loja por planilha.
Formatos reais (Excel com ;, acentos do Windows, datas variadas), prévia sem
gravar, reimportação sem duplicar, consentimento que só sobe, desfazer,
lojas separadas e o assistente reconhecendo o comprador importado.
"""
import py_compile
from datetime import date
from pathlib import Path

import pytest

import banco
from banco import conectar
from app import importacao
from app.importacao import (
    ImportacaoInvalida, PlanilhaInvalida, desfazer_importacao, importar, ler_planilha,
    resumo_da_base,
)
from app.lojas import criar_loja
from app.segmentos import modulo_do_segmento
from paginas.menu import OPERADOR, arquivos

RAIZ = Path(__file__).resolve().parent.parent
HOJE = date(2026, 10, 30)

CSV_EXCEL = (
    "Nome;Telefone;Veículo;Data da compra;Forma de pagamento;Parcelas\n"
    "Ana Souza;(81) 99999-8888;Honda Civic 2019;15/03/2025;Financiado;48x\n"
    "Carlos Lima;81 98888-7777;;;;\n"
    "Sem Fone;;Gol 2018;10/01/2024;à vista;\n"
    "Fixo;(81) 3333-4444;;;;\n"
)


def _ler(texto, codificacao="utf-8-sig"):
    return ler_planilha(texto.encode(codificacao), hoje=HOJE)


def _importar(texto=CSV_EXCEL, loja_id=1, consentimento=True, usuario="Samuel"):
    return importar(loja_id, _ler(texto), usuario=usuario, consentimento=consentimento,
                    arquivo="base.csv")


def _conta(tabela, loja_id=1):
    c = conectar()
    try:
        return c.execute(f"SELECT COUNT(*) FROM {tabela} WHERE loja_id = ?", (loja_id,)).fetchone()[0]
    finally:
        c.close()


def _contato(telefone, loja_id=1):
    c = conectar()
    try:
        return dict(c.execute("SELECT * FROM contatos WHERE loja_id = ? AND telefone = ?",
                              (loja_id, telefone)).fetchone())
    finally:
        c.close()


def _comprador():
    return modulo_do_segmento("veiculos", "comprador")


# ------------------------------------------------------------ migração

def test_migracao_v6_cria_as_tabelas():
    c = conectar()
    try:
        assert banco.versao_schema(c) == banco.VERSAO_SCHEMA >= 6
        tabelas = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        c.close()
    assert {"importacoes", "contatos", "compras_anteriores"} <= tabelas


# ------------------------------------------------------------ leitura

def test_le_planilha_do_excel_com_ponto_e_virgula_e_acento():
    p = _ler(CSV_EXCEL)
    assert p.colunas["telefone"] == "Telefone" and p.colunas["carro"] == "Veículo"
    assert p.colunas["data_compra"] == "Data da compra" and p.colunas["meses"] == "Parcelas"
    assert p.total_linhas == 4 and len(p.linhas) == 2
    assert [n for n, _ in p.recusadas] == [4, 5]
    ana = p.linhas[0]
    assert ana.telefone == "5581999998888" and ana.carro == "Honda Civic 2019"
    assert ana.data_compra == date(2025, 3, 15)
    assert (ana.pagamento, ana.meses) == ("financiado", 48)
    assert p.avisos == []


def test_virgula_e_acentos_do_windows():
    p = _ler("nome,celular,carro,data\nJosé,81999998888,Onix 2020,2025-06-01\n", "cp1252")
    l = p.linhas[0]
    assert (l.nome, l.carro, l.data_compra, l.pagamento) == ("José", "Onix 2020", date(2025, 6, 1), None)


def test_sem_coluna_de_telefone_recusa():
    with pytest.raises(PlanilhaInvalida, match="telefone"):
        _ler("nome;email\nAna;a@b.com\n")


def test_arquivo_vazio_recusa():
    with pytest.raises(PlanilhaInvalida):
        ler_planilha(b"", hoje=HOJE)


@pytest.mark.parametrize("texto, esperado", [
    ("15/03/2025", date(2025, 3, 15)),
    ("15/03/25", date(2025, 3, 15)),
    ("2025-03-15", date(2025, 3, 15)),
    ("15/03/2025 00:00:00", date(2025, 3, 15)),
    ("45731", date(2025, 3, 15)),          # data guardada como número no Excel
])
def test_formatos_de_data(texto, esperado):
    assert importacao._data(texto) == esperado


def test_compra_sem_data_e_data_no_futuro_viram_aviso():
    p = _ler("nome;telefone;carro;data\n"
             "Ana;81999998888;Civic;\n"
             "Bia;81988887777;Onix;01/01/2027\n"
             "Caio;81977776666;;10/10/2025\n")
    assert len(p.linhas) == 3 and p.compras == [] and len(p.avisos) == 3


def test_pagamento_desconhecido_entra_sem_forma():
    p = _ler("nome;telefone;carro;data;pagamento\nAna;81999998888;Civic;10/10/2025;cheque\n")
    assert len(p.compras) == 1 and p.compras[0].pagamento is None and len(p.avisos) == 1


def test_telefone_repetido_vira_um_contato():
    p = _ler("nome;telefone\nAna;(81) 99999-8888\n;81 99999 8888\n")
    assert len(p.linhas) == 2 and p.contatos() == {"5581999998888": "Ana"}


# ------------------------------------------------------------ gravação

def test_importar_grava_contatos_e_compras():
    r = _importar()
    assert (r["contatos_novos"], r["compras_novas"], r["recusadas"]) == (2, 1, 2)
    assert _conta("contatos") == 2 and _conta("compras_anteriores") == 1
    assert resumo_da_base(1) == {"contatos": 2, "com_consentimento": 2, "compras": 1}


def test_reimportar_nao_duplica_e_nao_apaga_nome_nem_consentimento():
    _importar()
    r = _importar("nome;telefone\n;81999998888\n", consentimento=False)
    assert (r["contatos_novos"], r["contatos_atualizados"]) == (0, 1)
    ana = _contato("5581999998888")
    assert ana["nome"] == "Ana Souza" and ana["consentimento"] == 1
    r = _importar()
    assert (r["compras_novas"], r["compras_repetidas"]) == (0, 1)
    assert _conta("contatos") == 2 and _conta("compras_anteriores") == 1


def test_consentimento_so_sobe_e_guarda_quem_confirmou():
    _importar(consentimento=False)
    assert _contato("5581999998888")["consentimento"] == 0
    _importar(consentimento=True, usuario="Samuel")
    ana = _contato("5581999998888")
    assert ana["consentimento"] == 1 and ana["consentimento_por"] == "Samuel"


def test_importar_exige_usuario_e_linhas():
    with pytest.raises(ImportacaoInvalida):
        _importar(usuario="  ")
    with pytest.raises(ImportacaoInvalida):
        _importar("nome;telefone\nX;123\n")


def test_loja_inexistente_e_recusada():
    with pytest.raises(ImportacaoInvalida):
        _importar(loja_id=99)
    assert _conta("importacoes", 99) == 0


def test_lojas_separadas():
    loja_b = criar_loja("Loja B")
    _importar(loja_id=loja_b)
    assert _conta("contatos") == 0 and _conta("contatos", loja_b) == 2
    assert _comprador().contexto_do_lead(1, "5581999998888", "whatsapp") == []
    assert len(_comprador().contexto_do_lead(loja_b, "5581999998888", "whatsapp")) == 1


def test_desfazer_importacao():
    r = _importar()
    assert desfazer_importacao(1, r["importacao_id"]) == {"contatos": 2, "compras": 1}
    assert _conta("contatos") == 0 and _conta("compras_anteriores") == 0
    with pytest.raises(ImportacaoInvalida, match="já foi desfeita"):
        desfazer_importacao(1, r["importacao_id"])


def test_desfazer_nao_apaga_contato_de_outra_importacao():
    _importar("nome;telefone\nCarlos Lima;81988887777\n")
    r = _importar()                     # Carlos atualizado, Ana nova
    desfazer_importacao(1, r["importacao_id"])
    assert _conta("contatos") == 1 and _contato("5581988887777")["nome"] == "Carlos Lima"


# ------------------------------------------------------------ assistente

def test_assistente_reconhece_comprador_importado():
    _importar()
    compras = _comprador().contexto_do_lead(1, "558199998888", "whatsapp")   # sem o 9
    assert compras == [{"descricao": "Honda Civic 2019", "data": date(2025, 3, 15),
                        "detalhe": "financiado em 48x"}]
    assert _comprador().contexto_do_lead(1, "558199998888", "telegram") == []


def test_venda_e_compra_importada_iguais_aparecem_uma_vez():
    c = conectar()
    try:
        carro = c.execute(
            "INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) "
            "VALUES (1, 'Honda', 'Civic', 2019, 48000, 'Branco', 'Automático', 98000, 'vendido')").lastrowid
        c.execute("INSERT INTO vendas (loja_id, lead_id, veiculo_id, data_venda, forma_pagamento) "
                  "VALUES (1, '5581999998888', ?, '2025-03-15', 'financiado')", (carro,))
        c.commit()
    finally:
        c.close()
    _importar()
    assert len(_comprador().contexto_do_lead(1, "5581999998888", "whatsapp")) == 1


# ------------------------------------------------------------ tela

def test_tela_de_importar_e_do_operador():
    assert "paginas/importar_base.py" in arquivos(OPERADOR)
    fonte = (RAIZ / "paginas/importar_base.py").read_text(encoding="utf-8")
    assert "exigir_operador()" in fonte
    py_compile.compile(str(RAIZ / "paginas/importar_base.py"), doraise=True)

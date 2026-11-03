"""
P2 do Plano Mestre: caminho único de venda.
- O estoque nunca grava 'vendido' (marcar_status, adicionar_carro, atualizar_carro).
- registrar_venda faz os 4 efeitos: venda, resultado, baixa no estoque e pós-venda.
- Só existe um botão de venda no Streamlit (paginas/conversas.py).
Tudo offline: banco temporário (conftest), sem IA, duas lojas.
"""
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from banco import conectar
from app import lojas, regua, vendas
from app.estoque import (
    OPCOES_STATUS, StatusInvalido, adicionar_carro, atualizar_carro, buscar_carro,
    listar_estoque, marcar_status,
)
from app.lojas import criar_loja
from app.resultados import resultado_do_lead

RAIZ = Path(__file__).resolve().parent.parent
AGORA = datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc)   # terça, 10:00 em Recife
ONTEM = date(2026, 11, 2)
LEAD = "5581999990000"


def _carro(loja_id, status="disponivel"):
    return adicionar_carro("Fiat", "Argo", 2021, 30000, "Prata", "Manual", 62000.0,
                           status=status, loja_id=loja_id)


def _vender(loja_id, carro_id, lead_id=LEAD):
    return vendas.registrar_venda(loja_id, lead_id, carro_id, ONTEM, "avista",
                                  vendedor="Ana", agora=AGORA)


def _status(carro_id, loja_id):
    return buscar_carro(carro_id, loja_id=loja_id)["status"]


@pytest.fixture
def loja_b():
    return criar_loja("Loja B")


# ---------------------------------------------------------------- estoque
def test_opcoes_de_situacao_sem_vendido():
    assert OPCOES_STATUS == ["disponivel", "reservado", "indisponivel"]


def test_marcar_status_recusa_vendido():
    carro = _carro(1)
    with pytest.raises(StatusInvalido, match="Registrar venda"):
        marcar_status(carro, "vendido", 1)
    assert _status(carro, 1) == "disponivel"


@pytest.mark.parametrize("situacao", ["disponivel", "reservado", "indisponivel"])
def test_marcar_status_aceita_as_tres_situacoes(situacao):
    carro = _carro(1)
    marcar_status(carro, situacao, 1)
    assert _status(carro, 1) == situacao


def test_marcar_status_recusa_situacao_desconhecida():
    carro = _carro(1)
    with pytest.raises(StatusInvalido):
        marcar_status(carro, "xyz", 1)
    assert _status(carro, 1) == "disponivel"


def test_reservado_e_indisponivel_saem_da_oferta_do_leo():
    from tools import consultar_estoque
    carro = _carro(1)
    for situacao in ("reservado", "indisponivel"):
        marcar_status(carro, situacao, 1)
        assert "Argo" not in consultar_estoque.invoke({"modelo": "Argo", "loja_id": 1})
    marcar_status(carro, "disponivel", 1)
    assert "Argo" in consultar_estoque.invoke({"modelo": "Argo", "loja_id": 1})


def test_carro_novo_nao_nasce_vendido():
    with pytest.raises(StatusInvalido):
        _carro(1, status="vendido")
    assert listar_estoque(1) == []


def test_editar_carro_nao_vira_vendido():
    carro = _carro(1)
    with pytest.raises(StatusInvalido):
        atualizar_carro(carro, "Fiat", "Argo", 2021, 30000, "Prata", "Manual", 62000.0,
                        "vendido", loja_id=1)
    assert _status(carro, 1) == "disponivel"


def test_carro_vendido_corrige_dados_mas_continua_vendido():
    carro = _carro(1)
    _vender(1, carro)
    atualizar_carro(carro, "Fiat", "Argo", 2021, 30000, "Prata", "Manual", 59000.0,
                    "vendido", loja_id=1)
    dados = buscar_carro(carro, loja_id=1)
    assert dados["status"] == "vendido" and dados["preco"] == 59000.0
    with pytest.raises(StatusInvalido):
        atualizar_carro(carro, "Fiat", "Argo", 2021, 30000, "Prata", "Manual", 59000.0,
                        "disponivel", loja_id=1)
    with pytest.raises(StatusInvalido):
        marcar_status(carro, "disponivel", 1)
    assert _status(carro, 1) == "vendido"


# ---------------------------------------------------------------- venda
def test_registrar_venda_faz_os_quatro_efeitos():
    lojas.salvar_config(1, {"modulos.pos_venda": True}, "teste")
    carro = _carro(1)
    r = _vender(1, carro)

    conexao = conectar()
    try:
        n_vendas = conexao.execute(
            "SELECT COUNT(*) FROM vendas WHERE loja_id = 1 AND lead_id = ? AND veiculo_id = ?",
            (LEAD, carro)).fetchone()[0]
    finally:
        conexao.close()
    assert n_vendas == 1                                              # 1. venda
    assert resultado_do_lead(LEAD, loja_id=1)["resultado"] == "comprou"  # 2. resultado
    assert _status(carro, 1) == "vendido"                             # 3. baixa no estoque
    assert r["pos_venda_ligado"] is True                              # 4. pós-venda
    assert any(e["estado"] == "agendado" for e in regua.execucoes_do_lead(1, LEAD))


def test_carro_vendido_sai_da_lista_de_oferta():
    carro = _carro(1)
    _vender(1, carro)
    assert carro not in [c["id"] for c in listar_estoque(1, incluir_vendidos=False)]


# ---------------------------------------------------------------- duas lojas
def test_venda_de_uma_loja_nao_afeta_a_outra(loja_b):
    carro_a, carro_b = _carro(1), _carro(loja_b)
    _vender(loja_b, carro_b)
    assert _status(carro_a, 1) == "disponivel"
    assert resultado_do_lead(LEAD, loja_id=1) is None
    assert resultado_do_lead(LEAD, loja_id=loja_b)["resultado"] == "comprou"
    with pytest.raises(vendas.VendaInvalida):
        _vender(1, carro_b)                       # carro de outra loja


def test_marcar_status_nao_atravessa_loja(loja_b):
    carro_b = _carro(loja_b)
    assert marcar_status(carro_b, "reservado", loja_id=1) == "Carro não encontrado nesta loja."
    assert _status(carro_b, loja_b) == "disponivel"


# ---------------------------------------------------------------- telas
def _telas() -> dict:
    arquivos = sorted((RAIZ / "paginas").rglob("*.py"))
    arquivos += [RAIZ / n for n in ("painel.py", "operador.py") if (RAIZ / n).exists()]
    return {p.relative_to(RAIZ).as_posix(): p.read_text(encoding="utf-8") for p in arquivos}


def test_so_existe_um_botao_de_venda_no_streamlit():
    telas = _telas()
    com_venda = sorted(nome for nome, texto in telas.items() if "registrar_venda(" in texto)
    assert com_venda == ["paginas/conversas.py"]
    assert telas["paginas/conversas.py"].count("registrar_venda(") == 1


def test_telas_nao_marcam_vendido_nem_resultado_a_mao():
    for nome, texto in _telas().items():
        assert not re.search(r"marcar_status\([^)]*vendido", texto), nome
        assert "registrar_resultado" not in texto, nome

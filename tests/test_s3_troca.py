"""
Bloco S3 (furo 8): a troca é atualizada, não duplicada; km 0 ou ausente
vira "não informado" e nunca apaga um km já conhecido; o vendedor vê
"km não informado", nunca "0 km". Tudo offline, banco temporário do conftest.
"""
from banco import conectar
from app.painel_leitura import cartao_do_lead
from tools import registrar_troca

LEAD = "5581988887777"


def _trocas(loja_id=1, lead=LEAD):
    conexao = conectar()
    try:
        return [dict(l) for l in conexao.execute(
            "SELECT modelo, ano, km, estado FROM trocas WHERE loja_id = ? AND lead_id = ? ORDER BY id",
            (loja_id, lead))]
    finally:
        conexao.close()


def _reg(modelo, ano, km, estado="bem conservado", lead=LEAD, loja_id=1):
    return registrar_troca.func(modelo, ano, km, estado, lead, loja_id=loja_id)


def test_sem_km_e_depois_com_km_fica_uma_linha():
    _reg("Gol", 2015, 0)
    texto = _reg("Gol", 2015, 90000)
    assert [t["km"] for t in _trocas()] == [90000]
    assert "atualizada" in texto and "90.000 km" in texto


def test_km_zero_nao_apaga_km_conhecido():
    _reg("Gol", 2015, 90000)
    _reg("Gol", 2015, 0)
    assert [t["km"] for t in _trocas()] == [90000]


def test_troca_nova_sem_km_fica_nao_informado():
    texto = _reg("Gol", 2015, 0)
    assert [t["km"] for t in _trocas()] == [None]
    assert "km não informado" in texto and " 0 km" not in texto


def test_dois_carros_diferentes_ficam_dois():
    _reg("Gol", 2015, 90000)
    _reg("Onix", 2019, 0)
    assert [(t["modelo"], t["km"]) for t in _trocas()] == [("Gol", 90000), ("Onix", None)]


def test_mesmo_ano_diferente_fica_dois():
    _reg("Gol", 2015, 90000)
    _reg("Gol", 2018, 40000)
    assert len(_trocas()) == 2


def test_maiuscula_e_acento_nao_duplicam():
    _reg("Doblò", 2016, 0)
    _reg(" doblo ", 2016, 110000)
    linhas = _trocas()
    assert len(linhas) == 1 and linhas[0]["km"] == 110000


def test_ano_desconhecido_e_completado_depois():
    _reg("Gol", 0, 0)
    _reg("Gol", 2015, 90000)
    assert _trocas() == [{"modelo": "Gol", "ano": 2015, "km": 90000, "estado": "bem conservado"}]


def test_estado_vazio_nao_apaga():
    _reg("Gol", 2015, 0, "bem conservado")
    _reg("Gol", 2015, 90000, "")
    assert _trocas()[0]["estado"] == "bem conservado"


def test_outra_loja_nao_mistura():
    _reg("Gol", 2015, 90000, loja_id=1)
    _reg("Gol", 2015, 0, loja_id=42)
    assert [t["km"] for t in _trocas(1)] == [90000]
    assert [t["km"] for t in _trocas(42)] == [None]


def test_cartao_mostra_km_nao_informado_e_depois_o_km():
    _reg("Gol", 2015, 0)
    assert cartao_do_lead(1, LEAD)["troca"] == "Gol 2015 · km não informado"
    _reg("Gol", 2015, 90000)
    assert cartao_do_lead(1, LEAD)["troca"] == "Gol 2015 · 90.000 km"


def test_cartao_com_linha_antiga_km_zero():
    conexao = conectar()
    try:
        conexao.execute("INSERT INTO trocas (loja_id, lead_id, modelo, ano, km, estado) "
                        "VALUES (1, ?, 'Gol', 2015, 0, '')", (LEAD,))
        conexao.commit()
    finally:
        conexao.close()
    troca = cartao_do_lead(1, LEAD)["troca"]
    assert troca == "Gol 2015 · km não informado" and "0 km" not in troca

"""
P3 do Plano Mestre: camada de apresentação (horário e nomes).
- Horário no fuso da loja: hoje/ontem/amanhã/dia da semana/data, virada de dia e de mês.
- Cliente pelo nome; sem nome, telefone formatado (só WhatsApp); duas lojas.
- Telas sem "UTC", sem "Lead: 5581..." e sem "(id 12)" em texto visível.
Tudo offline: banco temporário (conftest), sem IA.
Obs.: Recife e São Paulo têm o mesmo horário (UTC-3, sem horário de verão desde 2019).
Para provar o fuso, usamos também Manaus (UTC-4).
"""
import ast
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from banco import conectar
from app import lojas
from app.apresentacao import (
    SEM_HORA, data_para_tela, horario_iso_local, horario_para_tela, nome_do_canal,
    nome_do_cliente, nomes_dos_clientes,
)
from app.lojas import carregar_loja, criar_loja
from app.mensagens import salvar_mensagem
from app.telefone import formatar_telefone_br

RAIZ = Path(__file__).resolve().parent.parent
AGORA = datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc)   # terça, 10:00 em Recife


def _com_fuso(loja_id, fuso):
    lojas.salvar_config(loja_id, {"fuso": fuso}, "teste")
    return carregar_loja(loja_id)


@pytest.fixture
def recife():
    return _com_fuso(1, "America/Recife")


@pytest.fixture
def loja_b():
    return criar_loja("Loja B")


def _lead(loja_id, lead_id, nome):
    conexao = conectar()
    try:
        conexao.execute("INSERT INTO leads (lead_id, loja_id, nome) VALUES (?, ?, ?)",
                        (lead_id, loja_id, nome))
        conexao.commit()
    finally:
        conexao.close()


# ---------------------------------------------------------------- telefone
@pytest.mark.parametrize("entrada", ["5581998765432", "558198765432", "(81) 99876-5432"])
def test_formatar_telefone_celular(entrada):
    assert formatar_telefone_br(entrada) == "(81) 9 9876-5432"


@pytest.mark.parametrize("entrada", ["8838349362", "", None, "abc"])
def test_formatar_telefone_invalido_fica_vazio(entrada):
    assert formatar_telefone_br(entrada) == ""


# ---------------------------------------------------------------- horário
@pytest.mark.parametrize("banco_utc, esperado", [
    ("2026-11-03 12:00:00", "hoje 09:00"),
    ("2026-11-03 00:40:00", "ontem 21:40"),
    ("2026-11-04 13:00:00", "amanhã 10:00"),
    ("2026-10-30 18:00:00", "sex 15:00"),
    ("2026-10-31 15:00:00", "sáb 12:00"),          # fim de semana
    ("2026-11-01 13:00:00", "dom 10:00"),          # fim de semana
    ("2026-11-01 02:00:00", "sáb 23:00"),          # virada do mês: ainda 31/10 em Recife
    ("2026-10-20 18:10:00", "20/10 15:10"),
    ("2025-12-31 15:00:00", "31/12/2025 12:00"),
])
def test_horario_no_fuso_de_recife(recife, banco_utc, esperado):
    assert horario_para_tela(recife, banco_utc, agora=AGORA) == esperado


def test_virada_do_dia_depende_do_fuso(recife, loja_b):
    manaus = _com_fuso(loja_b, "America/Manaus")
    instante = "2026-11-03 03:30:00"
    assert horario_para_tela(recife, instante, agora=AGORA) == "hoje 00:30"
    assert horario_para_tela(manaus, instante, agora=AGORA) == "ontem 23:30"


def test_recife_e_sao_paulo_mostram_o_mesmo_horario(recife, loja_b):
    sao_paulo = _com_fuso(loja_b, "America/Sao_Paulo")
    assert horario_para_tela(recife, "2026-11-03 12:00:00", agora=AGORA) == "hoje 09:00"
    assert horario_para_tela(sao_paulo, "2026-11-03 12:00:00", agora=AGORA) == "hoje 09:00"


@pytest.mark.parametrize("valor", [None, "", "lixo", "2026-11-03"])
def test_horario_vazio_ou_invalido(recife, valor):
    assert horario_para_tela(recife, valor, agora=AGORA) == SEM_HORA


def test_horario_aceita_datetime_com_e_sem_fuso(recife):
    assert horario_para_tela(recife, datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc),
                             agora=AGORA) == "hoje 09:00"
    assert horario_para_tela(recife, datetime(2026, 11, 3, 12, 0), agora=AGORA) == "hoje 09:00"


def test_horario_iso_local_para_a_api(recife):
    assert horario_iso_local(recife, "2026-11-03 00:40:00") == "2026-11-02T21:40:00-03:00"
    assert horario_iso_local(recife, None) is None


@pytest.mark.parametrize("valor, esperado", [
    (date(2026, 11, 2), "02/11/2026"),
    ("2026-11-02", "02/11/2026"),
    (datetime(2026, 11, 2, 15, 0), "02/11/2026"),
    (None, SEM_HORA),
])
def test_data_para_tela(valor, esperado):
    assert data_para_tela(valor) == esperado


def test_nome_do_canal():
    assert nome_do_canal("whatsapp") == "WhatsApp"
    assert nome_do_canal(None) == SEM_HORA


# ---------------------------------------------------------------- nomes
def test_lead_com_nome_aparece_pelo_nome():
    _lead(1, "5581998765432", "Juliana Souza")
    assert nome_do_cliente(1, "5581998765432") == "Juliana Souza"


def test_lead_sem_nome_no_whatsapp_mostra_telefone_formatado():
    salvar_mensagem("558198765432", "cliente", "oi", canal="whatsapp", loja_id=1)
    assert nome_do_cliente(1, "558198765432") == "(81) 9 9876-5432"


def test_chat_do_telegram_nao_vira_telefone():
    salvar_mensagem("8198765432", "cliente", "oi", canal="telegram", loja_id=1)
    assert nome_do_cliente(1, "8198765432") == "Cliente sem nome (…5432)"


def test_nome_da_base_importada_quando_o_lead_nao_tem_nome():
    conexao = conectar()
    try:
        conexao.execute("INSERT INTO contatos (loja_id, telefone, nome) VALUES (1, ?, ?)",
                        ("5581998765432", "Carlos Lima"))
        conexao.commit()
    finally:
        conexao.close()
    salvar_mensagem("558198765432", "cliente", "oi", canal="whatsapp", loja_id=1)
    assert nome_do_cliente(1, "558198765432") == "Carlos Lima"


def test_duas_lojas_com_o_mesmo_telefone(loja_b):
    _lead(1, "5581998765432", "Ana")
    salvar_mensagem("5581998765432", "cliente", "oi", canal="whatsapp", loja_id=loja_b)
    assert nome_do_cliente(1, "5581998765432") == "Ana"
    assert nome_do_cliente(loja_b, "5581998765432") == "(81) 9 9876-5432"


def test_nomes_em_lote_devolve_todos_os_pedidos():
    _lead(1, "5581998765432", "Ana")
    nomes = nomes_dos_clientes(1, ["5581998765432", "xyz"])
    assert nomes == {"5581998765432": "Ana", "xyz": "Cliente sem nome (…xyz)"}
    assert nomes_dos_clientes(1, []) == {}


def test_nome_do_cliente_exige_a_loja():
    with pytest.raises(TypeError):
        nome_do_cliente("5581998765432")


# ---------------------------------------------------------------- telas
def _textos_das_telas():
    """Todos os textos (strings) das telas, sem os docstrings (que ninguém vê)."""
    arquivos = sorted((RAIZ / "paginas").rglob("*.py"))
    arquivos += [RAIZ / n for n in ("painel.py", "operador.py") if (RAIZ / n).exists()]
    saida = []
    for caminho in arquivos:
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        docstrings = set()
        for no in ast.walk(arvore):
            if (isinstance(no, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and no.body and isinstance(no.body[0], ast.Expr)
                    and isinstance(no.body[0].value, ast.Constant)):
                docstrings.add(id(no.body[0].value))
        for no in ast.walk(arvore):
            if isinstance(no, ast.Constant) and isinstance(no.value, str) and id(no) not in docstrings:
                saida.append((caminho.relative_to(RAIZ).as_posix(), no.value))
    return saida


def test_telas_sem_utc_visivel():
    achados = [(arquivo, texto) for arquivo, texto in _textos_das_telas() if "UTC" in texto]
    assert not achados, achados


def test_telas_sem_lead_cru_nem_id():
    achados = [(arquivo, texto) for arquivo, texto in _textos_das_telas()
               if "Lead: " in texto or "(id " in texto]
    assert not achados, achados

"""
P6d do Plano Mestre: quem age vem do .env e o Registro tem uma leitura só.
- OPERADOR_NOME é obrigatório; PAINEL_NOME tem padrão;
- a leitura junta registro_acoes, pausas_envio e config_historico, sem repetir;
- mais nova primeiro, com limite; cada loja vê só o que é dela;
- evento sem loja só aparece na leitura de sistema;
- o campo "Seu nome" sumiu das telas.
Tudo offline, banco temporário do conftest (ator "Teste", operador, painel).
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import bloqueios, logs, pausa
from app.identidade import PADRAO_PAINEL, SemNomeOperador, nome_do_operador, nome_do_painel
from app.lojas import criar_loja, salvar_config
from app.registro import ACOES_RELEVANTES, EVENTOS_DE_SISTEMA, registrar
from app.registro_leitura import (
    MAX_LIMITE, ROTULOS, ler_eventos_de_sistema, ler_registro, rotulo,
)

RAIZ = Path(__file__).resolve().parent.parent
LEAD = "5581999990000"


# ------------------------------------------------------------ identidade

def test_operador_vem_do_env():
    assert nome_do_operador({"OPERADOR_NOME": "  Samuel   Souza "}) == "Samuel Souza"


def test_sem_operador_no_env_para_com_instrucao():
    for ambiente in ({}, {"OPERADOR_NOME": "   "}):
        with pytest.raises(SemNomeOperador, match="OPERADOR_NOME"):
            nome_do_operador(ambiente)


def test_operador_com_nome_grande_demais():
    with pytest.raises(SemNomeOperador):
        nome_do_operador({"OPERADOR_NOME": "x" * 81})


def test_painel_tem_padrao():
    assert nome_do_painel({}) == PADRAO_PAINEL == "Equipe da loja"


def test_painel_usa_o_nome_do_env():
    assert nome_do_painel({"PAINEL_NOME": " Auto   Center "}) == "Auto Center"


# ------------------------------------------------------------ leitura

def test_junta_as_tres_fontes_sem_repetir():
    pausa.pausar(1, usuario="Ana", papel="cliente")
    bloqueios.bloquear(1, LEAD, "todos", None, "Ana")
    salvar_config(1, {"cidade": "Recife"}, "Samuel")
    itens = ler_registro(1)
    assert sorted(i["acao"] for i in itens) == ["bloquear_envio", "pausar_envios",
                                                "salvar_configuracao"]
    por = {i["acao"]: i for i in itens}
    assert (por["pausar_envios"]["pessoa"], por["pausar_envios"]["fonte"]) == ("Ana", "pausas_envio")
    assert (por["bloquear_envio"]["pessoa"], por["bloquear_envio"]["fonte"]) == ("Teste", "registro_acoes")
    cfg = por["salvar_configuracao"]
    assert (cfg["pessoa"], cfg["alvo"], cfg["antes"], cfg["depois"]) == ("Samuel", "config:cidade", "", "Recife")
    assert cfg["rotulo"] == "Mudou configuração"


def test_mais_recente_primeiro_e_rotulo_desconhecido():
    registrar("teste_antigo", 1, None, {"n": 1}, agora=datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
    registrar("teste_novo", 1, None, {"n": 2}, agora=datetime(2026, 2, 1, 12, tzinfo=timezone.utc))
    itens = ler_registro(1)
    assert [i["acao"] for i in itens] == ["teste_novo", "teste_antigo"]
    assert itens[0]["rotulo"] == "teste_novo" == rotulo("teste_novo")
    assert itens[0]["depois"] == {"n": 2}


def test_limite():
    for k in range(5):
        registrar(f"teste_{k}", 1, None, {"k": k})
    assert len(ler_registro(1, limite=3)) == 3
    assert len(ler_registro(1, limite=0)) == 1
    assert MAX_LIMITE == 500


def test_lojas_separadas():
    loja2 = criar_loja("Loja 2")
    bloqueios.bloquear(loja2, LEAD, "todos", None, "Ana")
    assert ler_registro(1) == []
    assert [i["acao"] for i in ler_registro(loja2)] == ["bloquear_envio"]


def test_sem_loja_falha():
    with pytest.raises(ValueError):
        ler_registro(None)


def test_evento_de_sistema_nao_aparece_na_loja():
    logs.registrar_canal_desconhecido("telegram", "123")
    assert ler_registro(1) == []
    eventos = ler_eventos_de_sistema()
    assert [e["acao"] for e in eventos] == ["mensagem_canal_sem_cadastro"]
    assert eventos[0]["pessoa"] == "Sistema"
    assert eventos[0]["depois"] == {"tipo_canal": "telegram", "id_externo": "123"}


def test_toda_acao_tem_rotulo():
    assert set(ACOES_RELEVANTES) | set(EVENTOS_DE_SISTEMA) <= set(ROTULOS)


def test_leitura_so_le():
    texto = (RAIZ / "app" / "registro_leitura.py").read_text(encoding="utf-8")
    for proibido in ("INSERT", "UPDATE", "DELETE", ".commit("):
        assert proibido not in texto


def test_arquivos_novos_de_app_sem_streamlit():
    for nome in ("identidade.py", "registro_leitura.py"):
        texto = (RAIZ / "app" / nome).read_text(encoding="utf-8")
        assert "import streamlit" not in texto


# ------------------------------------------------------------ telas

def test_campo_seu_nome_sumiu():
    for caminho in (RAIZ / "paginas" / "comum.py", RAIZ / "operador.py", RAIZ / "painel.py"):
        texto = caminho.read_text(encoding="utf-8")
        assert "campo_nome" not in texto
        assert "Seu nome" not in texto


def test_entradas_mostram_quem_esta_agindo():
    for nome in ("operador.py", "painel.py"):
        texto = (RAIZ / nome).read_text(encoding="utf-8")
        assert "mostrar_quem_esta_agindo()" in texto
        assert texto.index("definir_ator_da_sessao()") < texto.index("navegacao.run()")

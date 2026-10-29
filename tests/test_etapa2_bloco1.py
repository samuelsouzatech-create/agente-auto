"""
Testes da Etapa 2, Bloco 1. Todos offline, com duas lojas.

Provam: migração v5 (tabelas novas, loja obrigatória, unicidades); janela de
24 h com margem de 10 min, por loja e por canal; modelos de mensagem validados
(o texto testado é o que vai para a Meta); status de aprovação por loja;
enviar_template pela credencial da loja certa; segmentos descobertos pelas
pastas, com um segmento mínimo que não recebe nada de carro.
"""
import asyncio
import json
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from app import segmentos, templates
from app.chaves import LojaNaoInformada
from app.janela import janela_aberta
from app.lojas import ConfigInvalida, carregar_loja, criar_loja
from app.relogio import para_banco

AGORA = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)
VALORES = {"nome": "Ana", "agente": "Léo", "loja": "Auto Teste", "carro": "Honda Civic 2019"}
FERRAMENTAS_DE_CARRO = {"consultar_estoque", "detalhes_veiculo", "simular_financiamento",
                        "registrar_troca", "enviar_fotos"}
SEGMENTO_TESTE = "teste_min"
PROMPT_TESTE = "PERSONA DE TESTE: você marca horários numa barbearia."
FERRAMENTAS_TESTE = '''
from langchain_core.tools import tool


@tool
def ver_agenda(loja_id: int) -> str:
    """Mostra os  horários livres da barbearia."""
    return f"Agenda da loja {loja_id}: 10h e 15h livres."


FERRAMENTAS = [ver_agenda]
FERRAMENTAS_DE_MODULO = {}
'''


# ---------------------------------------------------------------- apoio

def _executar(sql, parametros=()):
    con = banco.conectar()
    try:
        cur = con.execute(sql, parametros)
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def _msg(loja_id, lead_id, direcao, quando, canal="whatsapp"):
    _executar("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
              "VALUES (?, ?, ?, ?, 'x', ?)", (lead_id, loja_id, canal, direcao, para_banco(quando)))


@pytest.fixture
def loja_b():
    return criar_loja("Loja B")


@pytest.fixture
def pasta_segmentos(tmp_path, monkeypatch):
    """Cópia de segmentos/ numa pasta temporária + o segmento mínimo de teste."""
    destino = tmp_path / "segmentos"
    shutil.copytree(segmentos.RAIZ / "segmentos", destino)
    minimo = destino / SEGMENTO_TESTE
    minimo.mkdir()
    (minimo / "prompt.md").write_text(PROMPT_TESTE, encoding="utf-8")
    (minimo / "ferramentas.py").write_text(FERRAMENTAS_TESTE, encoding="utf-8")
    monkeypatch.setattr(segmentos, "PASTA_SEGMENTOS", destino)
    return destino


# ---------------------------------------------------------------- migração v5

def test_migracao_v5_cria_tabelas_e_e_idempotente():
    banco.criar_tabelas()
    banco.criar_tabelas()
    con = banco.conectar()
    assert banco.versao_schema(con) == 5
    tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    for t in ("remarketing_envios", "vendas", "reguas", "regua_passos",
              "regua_execucoes", "modelos_loja", "interesse_veiculo"):
        assert t in tabelas


def test_migracao_v5_pode_rodar_de_novo():
    con = banco.conectar()
    con.execute("PRAGMA user_version = 4")
    con.commit()
    con.close()
    banco.migrar()                      # não pode quebrar
    con = banco.conectar()
    assert banco.versao_schema(con) == 5
    con.close()


def test_tabelas_novas_exigem_loja():
    with pytest.raises(sqlite3.IntegrityError):
        _executar("INSERT INTO remarketing_envios (lead_id, canal, toque, estado) "
                  "VALUES ('5581', 'whatsapp', 1, 'simulado')")


def test_mesmo_toque_nao_se_repete_mas_lojas_sao_independentes(loja_b):
    sql = ("INSERT INTO remarketing_envios (loja_id, lead_id, canal, toque, estado) "
           "VALUES (?, '5581', 'whatsapp', 1, 'simulado')")
    _executar(sql, (1,))
    _executar(sql, (loja_b,))
    with pytest.raises(sqlite3.IntegrityError):
        _executar(sql, (1,))


def test_uma_regua_ativa_por_loja(loja_b):
    sql = "INSERT INTO reguas (loja_id, tipo, ativa) VALUES (?, 'pos_venda', ?)"
    _executar(sql, (1, 1))
    _executar(sql, (1, 0))          # inativa: histórico, pode
    _executar(sql, (loja_b, 1))
    with pytest.raises(sqlite3.IntegrityError):
        _executar(sql, (1, 1))


# ---------------------------------------------------------------- janela

@pytest.mark.parametrize("horas, minutos, esperado", [
    (23, 49, True), (23, 51, False), (24, 1, False),
])
def test_janela_com_margem_de_10_minutos(horas, minutos, esperado):
    _msg(1, "5581", "cliente", AGORA - timedelta(hours=horas, minutes=minutos))
    assert janela_aberta(1, "5581", "whatsapp", AGORA) is esperado


def test_mensagem_do_leo_ou_vendedor_nao_reabre():
    _msg(1, "5581", "cliente", AGORA - timedelta(hours=30))
    _msg(1, "5581", "leo", AGORA - timedelta(hours=1))
    _msg(1, "5581", "vendedor", AGORA - timedelta(minutes=5))
    assert janela_aberta(1, "5581", "whatsapp", AGORA) is False


def test_sem_mensagem_do_cliente_janela_fechada():
    assert janela_aberta(1, "5581", "whatsapp", AGORA) is False


def test_telegram_sempre_aberta_e_canal_desconhecido_fechado():
    assert janela_aberta(1, "777", "telegram", AGORA) is True
    assert janela_aberta(1, "777", "pombo_correio", AGORA) is False


def test_duas_lojas_mesmo_telefone_janelas_independentes(loja_b):
    _msg(1, "5581", "cliente", AGORA - timedelta(hours=2))
    _msg(loja_b, "5581", "cliente", AGORA - timedelta(hours=30))
    assert janela_aberta(1, "5581", "whatsapp", AGORA) is True
    assert janela_aberta(loja_b, "5581", "whatsapp", AGORA) is False


def test_janela_exige_loja():
    with pytest.raises(LojaNaoInformada):
        janela_aberta(None, "5581", "whatsapp", AGORA)


# ---------------------------------------------------------------- modelos

def test_modelos_de_veiculos_carregam_e_sao_validos():
    modelos = templates.carregar_modelos("veiculos")
    assert "retomada_interesse" in modelos and "pos_venda_agradecimento" in modelos
    for m in modelos.values():
        assert m.categoria in templates.CATEGORIAS
        assert set(m.variaveis) <= set(templates.VARIAVEIS)


def test_preencher_e_falta_de_variavel():
    m = templates.modelo_do_segmento("veiculos", "retomada_interesse")
    texto = templates.preencher(m, VALORES)
    assert "Ana" in texto and "Honda Civic 2019" in texto and "{" not in texto
    with pytest.raises(templates.ValoresFaltando):
        templates.preencher(m, {"nome": "Ana"})


def test_parametro_tem_quebra_de_linha_limpa():
    m = templates.modelo_do_segmento("veiculos", "retomada_geral")
    params = templates.parametros_meta(m, {**VALORES, "nome": "Ana\n  Maria"})
    assert {"type": "text", "parameter_name": "nome", "text": "Ana Maria"} in params


def test_corpo_de_criacao_usa_parametros_nomeados():
    m = templates.modelo_do_segmento("veiculos", "retomada_interesse")
    corpo = templates.corpo_de_criacao(m, templates.exemplos_do_segmento("veiculos"))
    assert corpo["parameter_format"] == "named" and corpo["category"] == "marketing"
    assert "{{nome}}" in corpo["components"][0]["text"]


@pytest.mark.parametrize("item", [
    {"nome": "Maiuscula", "categoria": "marketing", "texto": "Oi"},
    {"nome": "x", "categoria": "promocao", "texto": "Oi"},
    {"nome": "x", "categoria": "marketing", "texto": "Oi {cpf}, tudo bem?"},
    {"nome": "x", "categoria": "marketing", "texto": "{nome}, tudo bem?"},
])
def test_modelo_fora_das_regras_e_recusado(item):
    with pytest.raises(templates.ModeloInvalido):
        templates._validar(item, "pt_BR", "teste")


def test_status_por_loja_e_categoria_efetiva(loja_b):
    assert not templates.modelo_aprovado(1, "retomada_interesse")
    templates.registrar_status(1, "retomada_interesse", "aprovado", categoria_efetiva="utilidade")
    assert templates.modelo_aprovado(1, "retomada_interesse")
    assert not templates.modelo_aprovado(loja_b, "retomada_interesse")
    m = templates.modelo_do_segmento("veiculos", "retomada_interesse")
    assert templates.categoria_para_custo(1, m) == "utilidade"
    assert templates.categoria_para_custo(loja_b, m) == "marketing"


def test_status_de_modelo_inexistente_e_recusado():
    with pytest.raises(templates.ModeloInexistente):
        templates.registrar_status(1, "nao_existe", "aprovado")


# ---------------------------------------------------------------- envio de modelo

def test_enviar_template_sai_pela_credencial_da_loja_certa(monkeypatch, loja_b):
    import app.api.enviar_whatsapp as ew
    from app.canais import cadastrar_canal
    from app.credenciais import credencial_whatsapp
    from app.channels.whatsapp import CanalWhatsApp

    monkeypatch.setenv("WA_TOKEN_A", "token-a")
    monkeypatch.setenv("WA_TOKEN_B", "token-b")
    cadastrar_canal(1, "whatsapp", "PNID_A", "WA_TOKEN_A")
    cadastrar_canal(loja_b, "whatsapp", "PNID_B", "WA_TOKEN_B")
    assert credencial_whatsapp(loja_b).phone_number_id == "PNID_B"

    enviados = []

    async def postar_falso(loja_id, corpo, descricao, para):
        enviados.append((credencial_whatsapp(loja_id).phone_number_id, corpo))
        return ew.ResultadoEnvio(ok=True, id_externo="wamid.1")

    monkeypatch.setattr(ew, "_postar_detalhado", postar_falso)
    m = templates.modelo_do_segmento("veiculos", "retomada_interesse")
    r = asyncio.run(CanalWhatsApp(loja_b).enviar_template("5581", m, VALORES))

    assert r.ok
    numero, corpo = enviados[0]
    assert numero == "PNID_B"
    assert corpo["type"] == "template" and corpo["template"]["name"] == "retomada_interesse"
    nomes = {p["parameter_name"] for p in corpo["template"]["components"][0]["parameters"]}
    assert nomes == {"nome", "agente", "loja", "carro"}


def test_enviar_template_sem_variavel_nem_chama_a_meta(monkeypatch):
    import app.api.enviar_whatsapp as ew
    chamadas = []

    async def postar_falso(*a, **k):
        chamadas.append(a)

    monkeypatch.setattr(ew, "_postar_detalhado", postar_falso)
    m = templates.modelo_do_segmento("veiculos", "retomada_interesse")
    r = asyncio.run(ew.enviar_template_whatsapp("5581", m, {"nome": "Ana"}, loja_id=1))
    assert not r.ok and chamadas == []


def test_resultado_reconhece_janela_fechada():
    from app.resultado_envio import ResultadoEnvio
    assert ResultadoEnvio(ok=False, codigo_erro=131047).janela_fechada
    assert not ResultadoEnvio(ok=False, codigo_erro=100).janela_fechada


# ---------------------------------------------------------------- segmentos

def test_segmentos_vem_das_pastas(pasta_segmentos):
    assert segmentos.segmentos_disponiveis() == sorted(["veiculos", SEGMENTO_TESTE])
    (pasta_segmentos / "sem_prompt").mkdir()           # pasta sem prompt.md não conta
    assert "sem_prompt" not in segmentos.segmentos_disponiveis()


def test_segmento_minimo_nao_recebe_nada_de_carro(pasta_segmentos):
    from app.core.montagem import ferramentas_da_loja, montar_prompt
    loja_t = criar_loja("Barbearia", segmento=SEGMENTO_TESTE)
    lt, l1 = carregar_loja(loja_t), carregar_loja(1)

    nomes_t = {f.name for f in ferramentas_da_loja(lt)}
    assert "ver_agenda" in nomes_t
    assert not (nomes_t & FERRAMENTAS_DE_CARRO)
    prompt_t = montar_prompt(lt, ferramentas_da_loja(lt), AGORA)
    assert PROMPT_TESTE in prompt_t and "ficha do carro" not in prompt_t

    nomes_1 = {f.name for f in ferramentas_da_loja(l1)}
    assert FERRAMENTAS_DE_CARRO <= nomes_1 and "ver_agenda" not in nomes_1


def test_loja_com_segmento_inexistente_e_recusada(pasta_segmentos):
    with pytest.raises(ConfigInvalida, match="não existe"):
        criar_loja("Clínica", segmento="clinica")
    with pytest.raises(segmentos.SegmentoInexistente):
        segmentos.pasta_do_segmento("clinica")

"""
Revisão da Etapa 1 (parecer do analista). Todos offline.
Canal desativado, loja obrigatória, credenciais por loja, checagem fixa de
parada, trava do runner, opção de espera e prompts relidos sem reiniciar.
"""
import asyncio
import os
from datetime import datetime
from types import SimpleNamespace

import fakeredis
import pytest
from langchain_core.messages import AIMessage

import banco
from app import config, lojas
from app.canais import cadastrar_canal, desativar_canal, resolver_loja
from app.chaves import LojaNaoInformada, chave_redis, thread_id
from app.core import montagem
from app.credenciais import SemCredencial, credencial_whatsapp, token_telegram
from app.interesse import pode_contatar, situacao_do_lead
from app.jobs.trava import TravaRunner
from app.pedido_parada import pediu_para_parar, registrar_se_pediu_parada

LOJA_B = 42
AGORA = datetime(2026, 10, 27, 15, 0)


@pytest.fixture
def loja_b():
    conexao = banco.conectar()
    conexao.execute("INSERT OR IGNORE INTO lojas (id, nome, segmento, config) "
                    "VALUES (?, 'Auto Bia', 'veiculos', '{}')", (LOJA_B,))
    conexao.commit()
    conexao.close()
    lojas.limpar_cache()
    return LOJA_B


def _importar_agente():
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.setdefault("GOOGLE_API_KEY", "chave-falsa-so-para-importar")
    import app.core.agent as agent
    return agent


class GrafoFalso:
    def invoke(self, entrada, config=None):
        return {"messages": [*entrada["messages"], AIMessage(content="Tudo bem, desculpa o incômodo!")]}


# ------------------------------------------------ canal desativado
def test_canal_desativado_nao_cai_na_loja_1(loja_b):
    cadastrar_canal(LOJA_B, "whatsapp", "PNID_B")
    desativar_canal("whatsapp", "PNID_B")
    assert resolver_loja("whatsapp", "PNID_B") is None
    assert resolver_loja("whatsapp", "OUTRO") is None
    assert resolver_loja("telegram", "123") == 1        # tipo nunca cadastrado: transição


# ------------------------------------------------ loja obrigatória
def test_sem_loja_da_erro():
    for loja in (None, 0, "abc", True):
        with pytest.raises(LojaNaoInformada):
            chave_redis("lock", loja, "5581")
    with pytest.raises(LojaNaoInformada):
        thread_id(None, "whatsapp", "5581")


def test_agente_sem_loja_da_erro():
    agent = _importar_agente()
    with pytest.raises(LojaNaoInformada):
        agent._loja_do_estado({"lead_id": "x"})


# ------------------------------------------------ credenciais por loja
def test_whatsapp_usa_numero_e_token_da_loja(monkeypatch, loja_b):
    monkeypatch.setattr(config, "WHATSAPP_PHONE_NUMBER_ID", "PNID_1")
    monkeypatch.setattr(config, "WHATSAPP_TOKEN", "tok1")
    monkeypatch.setenv("WHATSAPP_TOKEN_LOJA2", "tokB")
    cadastrar_canal(1, "whatsapp", "PNID_1")
    cadastrar_canal(LOJA_B, "whatsapp", "PNID_B", "WHATSAPP_TOKEN_LOJA2")
    c1, cb = credencial_whatsapp(1), credencial_whatsapp(LOJA_B)
    assert (c1.phone_number_id, c1.token) == ("PNID_1", "tok1")
    assert (cb.phone_number_id, cb.token) == ("PNID_B", "tokB")
    assert "tokB" not in repr(cb)


def test_sem_credencial_nada_sai_pelo_numero_errado(monkeypatch, loja_b):
    monkeypatch.setattr(config, "WHATSAPP_PHONE_NUMBER_ID", "PNID_1")
    monkeypatch.setattr(config, "WHATSAPP_TOKEN", "tok1")
    cadastrar_canal(LOJA_B, "whatsapp", "PNID_B")             # sem token_ref
    with pytest.raises(SemCredencial):
        credencial_whatsapp(LOJA_B)
    with pytest.raises(SemCredencial):
        credencial_whatsapp(1)        # já existe WhatsApp cadastrado e a loja 1 não tem


def test_modo_transicao_usa_o_env(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_PHONE_NUMBER_ID", "PNID_1")
    monkeypatch.setattr(config, "WHATSAPP_TOKEN", "tok1")
    assert credencial_whatsapp(1).phone_number_id == "PNID_1"
    with pytest.raises(SemCredencial):
        credencial_whatsapp(LOJA_B)


def test_envio_sai_pelo_numero_da_loja(monkeypatch, loja_b):
    import app.api.enviar_whatsapp as ew
    monkeypatch.setenv("WHATSAPP_TOKEN_LOJA2", "tokB")
    cadastrar_canal(LOJA_B, "whatsapp", "PNID_B", "WHATSAPP_TOKEN_LOJA2")
    chamadas = []

    class ClienteFalso:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            chamadas.append((url, headers["Authorization"]))
            return SimpleNamespace(status_code=200, text="")

    monkeypatch.setattr(ew.httpx, "AsyncClient", lambda timeout=30: ClienteFalso())
    assert asyncio.run(ew.enviar_texto_whatsapp("5581", "oi", loja_id=LOJA_B))
    [(url, autorizacao)] = chamadas
    assert "/PNID_B/messages" in url and autorizacao == "Bearer tokB"


def test_token_ref_nao_aceita_o_token(loja_b):
    with pytest.raises(ValueError):
        cadastrar_canal(LOJA_B, "telegram", "123", "123:ABC")


def test_telegram_usa_o_bot_da_loja(monkeypatch, loja_b):
    monkeypatch.setattr(config, "TELEGRAM_TOKEN", "111:AAA")
    monkeypatch.setenv("TG_LOJA_B", "222:BBB")
    cadastrar_canal(1, "telegram", "111")
    cadastrar_canal(LOJA_B, "telegram", "222", "TG_LOJA_B")
    assert token_telegram(1) == "111:AAA"
    assert token_telegram(LOJA_B) == "222:BBB"
    monkeypatch.setenv("TG_LOJA_B", "333:CCC")                # token de outro bot
    with pytest.raises(SemCredencial):
        token_telegram(LOJA_B)


# ------------------------------------------------ checagem fixa de parada
@pytest.mark.parametrize("texto", [
    "Para de me mandar mensagem", "não me mande mais mensagens, por favor",
    "me tira dessa lista", "Não me ligue mais", "não quero mais receber propaganda",
    "pode me descadastrar", "PARE DE ME CHAMAR", "não entrem mais em contato",
])
def test_pedido_claro_e_reconhecido(texto):
    assert pediu_para_parar(texto)


@pytest.mark.parametrize("texto", [
    "não me manda mais foto do civic, manda do corolla", "para de brincadeira, quanto é o onix?",
    "quero receber o carro sábado", "não liga mais pra isso não", "obrigado, agora não",
    "não tenho interesse", "tem lista de espera pro corolla?",
])
def test_conversa_normal_nao_e_pedido_de_parada(texto):
    assert pediu_para_parar(texto) is None


def test_pedido_no_turno_grava_sem_depender_da_ia():
    from app.core.turno import executar_turno
    r = asyncio.run(executar_turno(1, "simulador", "lead-p", "por favor, para de me mandar mensagem",
                                   grafo=GrafoFalso()))
    assert r.texto                                        # o assistente responde normalmente
    assert situacao_do_lead(1, "lead-p")["situacao"] == "nao_contatar"
    assert not pode_contatar(1, "lead-p")


def test_pedido_vale_mesmo_com_vendedor_no_comando():
    from app.core.turno import executar_turno
    from app.handoff import assumir_handoff
    from tools import acionar_handoff
    acionar_handoff.func(motivo="m", resumo="r", lead_id="lead-v", loja_id=1)
    assumir_handoff("lead-v", "Ana", loja_id=1)
    r = asyncio.run(executar_turno(1, "simulador", "lead-v", "me tira da lista", grafo=GrafoFalso()))
    assert r.silenciado and not pode_contatar(1, "lead-v")


def test_pedido_vale_so_na_loja_da_conversa(loja_b):
    assert registrar_se_pediu_parada(LOJA_B, "5581", "não me mande mais mensagem")
    assert not pode_contatar(LOJA_B, "5581") and pode_contatar(1, "5581")


# ------------------------------------------------ trava do runner
def _redis(servidor):
    return fakeredis.FakeRedis(server=servidor, decode_responses=True)


def test_trava_deixa_um_runner_so():
    servidor = fakeredis.FakeServer()
    a, b = TravaRunner(_redis(servidor)), TravaRunner(_redis(servidor))
    assert a.adquirir() and not b.adquirir()
    assert a.renovar() and not b.renovar()
    a.liberar()
    assert b.adquirir()


def test_segundo_runner_sai_e_o_primeiro_libera_ao_terminar(monkeypatch):
    from app.jobs import runner
    servidor = fakeredis.FakeServer()
    monkeypatch.setattr(runner, "cliente_redis_sincrono", lambda: _redis(servidor))
    outro = TravaRunner(_redis(servidor))
    assert outro.adquirir()
    assert runner.main(["--uma-vez"]) == 1
    outro.liberar()
    assert runner.main(["--uma-vez"]) == 0
    assert TravaRunner(_redis(servidor)).adquirir()      # liberou ao terminar


def test_runner_sem_redis_nao_liga(monkeypatch):
    from app.jobs import runner

    def redis_fora():
        raise ConnectionError("fora do ar")
    monkeypatch.setattr(runner, "cliente_redis_sincrono", redis_fora)
    assert runner.main(["--uma-vez"]) == 1


# ------------------------------------------------ opção de espera
def _loja_com(opcao):
    lojas.salvar_config(1, {"atendimento.aguardando_vendedor": opcao}, "teste", papel="cliente")
    return lojas.carregar_loja(1)


def _nomes(loja, em_espera=True):
    return {f.name for f in montagem.ferramentas_da_loja(loja, em_espera=em_espera)}


def test_opcao_de_espera_muda_ferramentas_e_prompt():
    loja = _loja_com("conversar")
    assert "simular_financiamento" in _nomes(loja)
    prompt = montagem.montar_prompt(loja, montagem.ferramentas_da_loja(loja, True), AGORA, em_espera=True)
    assert "inclusive simulações" in prompt

    loja = _loja_com("meio_termo")
    assert "simular_financiamento" not in _nomes(loja) and "consultar_estoque" in _nomes(loja)

    loja = _loja_com("esperar")
    assert _nomes(loja) <= montagem.FERRAMENTAS_DA_ESPERA_QUIETA
    prompt = montagem.montar_prompt(loja, montagem.ferramentas_da_loja(loja, True), AGORA, em_espera=True)
    assert "UMA frase curta" in prompt
    assert "consultar_estoque" in _nomes(loja, em_espera=False)     # fora da espera, tudo normal


# ------------------------------------------------ prompts relidos
def test_prompt_e_relido_quando_o_arquivo_muda(tmp_path):
    arquivo = tmp_path / "teste.md"
    arquivo.write_text("versão 1", encoding="utf-8")
    assert montagem._ler_arquivo(str(arquivo)) == "versão 1"
    arquivo.write_text("versão 2", encoding="utf-8")
    info = arquivo.stat()
    os.utime(arquivo, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))
    assert montagem._ler_arquivo(str(arquivo)) == "versão 2"



# --- Ajuste da validação: frases ambíguas de "lista" e dois pedidos que passavam ---
import pytest as _pytest
from app.pedido_parada import pediu_para_parar as _pediu


@_pytest.mark.parametrize("frase", [
    "me tira da lista", "tira-me da lista", "Por favor, me remova da lista",
    "chega de mensagem, parem", "não quero que vocês me chamem mais",
])
def test_pedido_de_parada_claro_e_pego(frase):
    assert _pediu(frase)


@_pytest.mark.parametrize("frase", [
    "tira da lista o Gol", "me tira da lista de espera do Corolla",
    "não quero que vocês me mandem mais fotos desse", "chega de conversa, quero fechar",
])
def test_conversa_normal_nao_vira_pedido_de_parada(frase):
    assert not _pediu(frase)

"""
P7b do Plano Mestre: a porta de entrada da loja em teste.
- loja em teste: só número de teste e simulador são atendidos;
- quem não é número de teste: silêncio, nada gravado, IA não chamada,
  evento no Registro (ator Sistema), erro no Registro não derruba;
- respostas prontas (mídia, áudio) também respeitam a porta;
- WhatsApp: número com ou sem o 9 é o mesmo;
- depois de colocar no ar, atende todo mundo;
- script do operador cadastra número e coloca no ar com --sim.
Tudo offline, banco temporário do conftest (ator "Teste", operador, painel).
"""
import asyncio
import importlib
import importlib.util
import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from banco import conectar
from app.estado_loja import cadastrar_numero_de_teste, colocar_no_ar, estado_da_loja, pode_responder
from app.lojas import criar_loja
from app.mensagens import historico_do_lead
from app.registro import EVENTOS_DE_SISTEMA
from app.registro_leitura import ROTULOS, ler_registro

RAIZ = Path(__file__).resolve().parent.parent
EVENTO = "mensagem_recusada_loja_em_teste"

_spec = importlib.util.spec_from_file_location("script_estado_loja", RAIZ / "scripts" / "estado_loja.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)


def importar(nome):
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.setdefault("GOOGLE_API_KEY", "chave-falsa-so-para-importar")
    return importlib.import_module(nome)


class GrafoFalso:
    def __init__(self, texto="Oi!"):
        self.texto, self.chamadas = texto, []

    def invoke(self, entrada, config=None):
        self.chamadas.append(entrada)
        return {"messages": [HumanMessage(content=entrada["messages"][0].content),
                             AIMessage(content=self.texto)]}


def _um(sql, parametros=()):
    conexao = conectar()
    try:
        return conexao.execute(sql, parametros).fetchone()[0]
    finally:
        conexao.close()


def _eventos(loja_id):
    conexao = conectar()
    try:
        return [dict(l) for l in conexao.execute(
            "SELECT * FROM registro_acoes WHERE acao = ? AND loja_id = ?", (EVENTO, loja_id))]
    finally:
        conexao.close()


def _turno(loja_id, canal, lead, texto="oi", grafo=None):
    turno = importar("app.core.turno")
    return asyncio.run(turno.executar_turno(loja_id, canal, lead, texto, grafo=grafo or GrafoFalso()))


@pytest.fixture
def redis_falso(monkeypatch):
    import fakeredis
    import app.redis_cliente as rc
    import app.redis_debounce as rd
    import app.redis_lock as rl
    import app.redis_atraso as ra
    falso = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    for modulo in (rc, rd, rl, ra):
        monkeypatch.setattr(modulo, "redis_cliente", falso)
    monkeypatch.setattr(rd, "DEBOUNCE_SEGUNDOS", 0.1)
    monkeypatch.setattr(ra, "ATRASO_ATIVO", (0, 0))
    monkeypatch.setattr(ra, "ATRASO_AUSENTE", (0, 0))
    return falso


# ------------------------------------------------------------ porta fechada

def test_loja_em_teste_ignora_quem_nao_e_numero_de_teste():
    loja2 = criar_loja("Loja 2")
    grafo = GrafoFalso()
    r = _turno(loja2, "telegram", "777", grafo=grafo)
    assert r.silenciado and r.texto is None
    assert grafo.chamadas == []                                  # IA nem foi chamada
    assert historico_do_lead("777", loja2) == []                 # nada gravado
    assert _um("SELECT COUNT(*) FROM uso_custos WHERE loja_id = ?", (loja2,)) == 0


def test_recusa_vai_para_o_registro_da_loja():
    loja2 = criar_loja("Loja 2")
    _turno(loja2, "telegram", "777")
    [e] = _eventos(loja2)
    assert (e["pessoa"], e["papel"], e["origem"], e["alvo"]) == (
        "Sistema", "sistema", "webhook", "telegram:777")
    assert [i["rotulo"] for i in ler_registro(loja2)] == ["Mensagem recusada (loja em teste)"]


def test_evento_esta_na_lista_e_tem_rotulo():
    assert EVENTO in EVENTOS_DE_SISTEMA and EVENTO in ROTULOS


def test_erro_no_registro_nao_derruba(monkeypatch):
    import app.registro as registro

    def quebrado(*a, **k):
        raise RuntimeError("Registro fora")
    monkeypatch.setattr(registro, "registrar", quebrado)
    loja2 = criar_loja("Loja 2")
    r = _turno(loja2, "telegram", "777")
    assert r.silenciado and historico_do_lead("777", loja2) == []


def test_erro_ao_ler_o_estado_fecha_a_porta(monkeypatch):
    turno = importar("app.core.turno")

    def quebrado(*a, **k):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(turno, "pode_responder", quebrado)
    r = asyncio.run(turno.executar_turno(1, "telegram", "777", "oi", grafo=GrafoFalso()))
    assert r.silenciado and historico_do_lead("777", 1) == []


def test_loja_que_nao_existe_fica_fechada():
    r = _turno(999, "telegram", "777")
    assert r.silenciado


# ------------------------------------------------------------ porta aberta

def test_numero_de_teste_e_atendido():
    loja2 = criar_loja("Loja 2")
    cadastrar_numero_de_teste(loja2, "telegram", "777", "Samuel")
    r = _turno(loja2, "telegram", "777")
    assert r.texto == "Oi!"
    assert [m["direcao"] for m in historico_do_lead("777", loja2)] == ["cliente", "leo"]
    assert _eventos(loja2) == []


def test_numero_de_teste_de_outra_loja_nao_abre():
    loja2, loja3 = criar_loja("Loja 2"), criar_loja("Loja 3")
    cadastrar_numero_de_teste(loja2, "telegram", "777")
    assert _turno(loja3, "telegram", "777").silenciado


def test_whatsapp_sem_o_9_e_atendido():
    loja2 = criar_loja("Loja 2")
    cadastrar_numero_de_teste(loja2, "whatsapp", "(81) 99999-0000")
    assert _turno(loja2, "whatsapp", "558199990000").texto == "Oi!"     # como o WhatsApp manda
    assert _turno(loja2, "whatsapp", "558188880000").silenciado


def test_simulador_sempre_atendido():
    loja2 = criar_loja("Loja 2")
    assert _turno(loja2, "simulador", "qualquer").texto == "Oi!"


def test_loja_no_ar_atende_todo_mundo():
    assert _turno(1, "telegram", "888").texto == "Oi!"


def test_depois_de_colocar_no_ar_atende():
    loja2 = criar_loja("Loja 2")
    assert _turno(loja2, "telegram", "777").silenciado
    colocar_no_ar(loja2)
    assert _turno(loja2, "telegram", "777").texto == "Oi!"


# ------------------------------------------------------------ respostas prontas

def test_midia_e_audio_respeitam_a_porta():
    turno = importar("app.core.turno")
    loja2 = criar_loja("Loja 2")
    assert turno.turno_midia_nao_suportada(loja2, "whatsapp", "5581", "image").silenciado
    assert turno.turno_audio_falhou(loja2, "telegram", "777").silenciado
    assert historico_do_lead("5581", loja2) == [] and historico_do_lead("777", loja2) == []
    cadastrar_numero_de_teste(loja2, "telegram", "777")
    assert turno.turno_audio_falhou(loja2, "telegram", "777").texto == turno.MENSAGEM_AUDIO_FALHOU


# ------------------------------------------------------------ canais

def test_whatsapp_em_teste_nao_envia_nem_marca_lida(monkeypatch, redis_falso):
    wh = importar("app.api.webhook")
    loja2 = criar_loja("Loja 2")
    enviadas, marcadas = [], []

    async def resposta(numero, texto, atraso=0, **kw):
        enviadas.append(texto)

    async def marcar(id_mensagem, digitando=False, **kw):
        marcadas.append(id_mensagem)
        return True

    monkeypatch.setattr(wh, "enviar_resposta_humanizada", resposta)
    monkeypatch.setattr(wh.canal_whatsapp, "marcar_lida", marcar)
    monkeypatch.setattr(wh, "agente_grafo", GrafoFalso())
    wh._ultima_recebida[(loja2, "5581")] = "wamid.X"
    asyncio.run(wh.processar_mensagem("5581", "oi", None, loja2))
    assert enviadas == [] and marcadas == []


def test_telegram_em_teste_nao_responde(monkeypatch, redis_falso):
    tb = importar("app.api.telegram_bot")
    loja2 = criar_loja("Loja 2")
    monkeypatch.setattr(tb, "agente_grafo", GrafoFalso())
    assert asyncio.run(tb.processar_texto("777", "oi", loja_id=loja2)) == (None, [])


# ------------------------------------------------------------ script do operador

def test_script_cadastra_numero_e_pede_confirmacao_para_ir_ao_ar(monkeypatch):
    monkeypatch.setenv("OPERADOR_NOME", "Samuel")
    loja2 = criar_loja("Loja 2")
    assert script.main(["numero", str(loja2), "telegram", "555", "Samuel"]) == 0
    assert pode_responder(loja2, "telegram", "555")
    assert script.main(["no-ar", str(loja2)]) == 1                 # sem --sim: não muda
    assert estado_da_loja(loja2) == "em_teste"
    assert script.main(["no-ar", str(loja2), "--sim"]) == 0
    assert estado_da_loja(loja2) == "no_ar"
    assert _um("SELECT pessoa FROM registro_acoes WHERE acao = 'colocar_no_ar'") == "Samuel"


def test_script_sem_operador_no_env_nao_age(monkeypatch):
    monkeypatch.delenv("OPERADOR_NOME", raising=False)
    loja2 = criar_loja("Loja 2")
    assert script.main(["no-ar", str(loja2), "--sim"]) == 1
    assert estado_da_loja(loja2) == "em_teste"


def test_script_listar_funciona_sem_operador(monkeypatch, capsys):
    monkeypatch.delenv("OPERADOR_NOME", raising=False)
    assert script.main(["listar"]) == 0
    assert "loja 1" in capsys.readouterr().out

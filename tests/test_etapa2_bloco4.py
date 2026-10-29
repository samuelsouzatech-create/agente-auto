"""
Testes da Etapa 2, Bloco 4: a resposta do cliente reabre a conversa.
O assistente sabe da retomada que mandou; IA não promete o que não fez;
teto de 3 falhas; lead pulado não ocupa vaga. Tudo offline.
"""
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from banco import conectar
from app import lojas
from app.custos import Uso
from app.jobs import remarketing as rmk
from app.relogio import para_banco
from app.resultado_envio import ResultadoEnvio
from app.retomada import resumo_respostas, retomada_recente
from app.templates import registrar_status

AGORA = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)   # terça, 09:00 em Recife
TEXTO_IA = "Oi! Conseguiu pensar no Corolla? Se quiser, marco um horário para você ver de perto."


class EnviadorFalso:
    def __init__(self, ok=True):
        self.ok, self.textos, self.modelos = ok, [], []

    def _r(self):
        return ResultadoEnvio(ok=self.ok, id_externo="x1" if self.ok else "",
                              detalhe="" if self.ok else "Chat not found")

    async def texto(self, loja_id, canal, lead_id, texto):
        self.textos.append(texto)
        return self._r()

    async def modelo(self, loja_id, lead_id, modelo, valores):
        self.modelos.append(modelo.nome)
        return self._r()


def redator(texto=TEXTO_IA):
    return lambda loja, lead_id, canal, toque, dados, historico: (texto, Uso(100, 20, 0))


def _ligar(loja_id=1):
    lojas.salvar_config(loja_id, {"modulos.remarketing": True,
                                  "remarketing.limite_mensal": 50}, "teste")


def _mensagem(lead_id, canal, direcao, quando, texto="oi", loja_id=1):
    c = conectar()
    c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
              "VALUES (?, ?, ?, ?, ?, ?)", (lead_id, loja_id, canal, direcao, texto, para_banco(quando)))
    c.commit()
    c.close()


def _conversa(lead_id, canal="telegram"):
    _mensagem(lead_id, canal, "cliente", AGORA - timedelta(hours=72), "quanto tá o Corolla?")
    _mensagem(lead_id, canal, "leo", AGORA - timedelta(hours=71), "R$ 135.000")


def _lead(lead_id, nome):
    c = conectar()
    c.execute("INSERT INTO leads (lead_id, loja_id, nome) VALUES (?, 1, ?)", (lead_id, nome))
    c.commit()
    c.close()


def _envios():
    c = conectar()
    linhas = [dict(l) for l in c.execute(
        "SELECT * FROM remarketing_envios WHERE loja_id = 1 ORDER BY lead_id, toque").fetchall()]
    c.close()
    return linhas


def _rodar(agora=AGORA, **kw):
    kw.setdefault("pausa_s", 0)
    kw.setdefault("redator", redator())
    kw.setdefault("enviador", EnviadorFalso())
    kw.setdefault("envio_real", False)
    return rmk.rodar_remarketing(agora, **kw)


def _enviar_retomada(lead_id="111"):
    _ligar()
    _conversa(lead_id)
    _rodar(envio_real=True)


# ---------------------------------------------------------------- texto da IA
def test_ia_que_diz_que_ja_fez_vira_reserva():
    _ligar()
    _conversa("111")
    env = EnviadorFalso()
    _rodar(envio_real=True, enviador=env,
           redator=redator("Oi! Consegui separar aqui umas fotos do Civic, quer ver?"))
    assert "separar" not in env.textos[0]
    assert json.loads(_envios()[0]["contexto"])["origem"] == "reserva"


def test_texto_bom_da_ia_passa():
    assert rmk._limpar_texto(TEXTO_IA) == TEXTO_IA


# ---------------------------------------------------------------- teto de falhas
def test_tres_falhas_bloqueiam_e_param_de_tentar():
    _ligar()
    _conversa("111")
    env = EnviadorFalso(ok=False)
    _rodar(envio_real=True, enviador=env)                                   # 1ª
    _rodar(AGORA + timedelta(hours=7), envio_real=True, enviador=env)       # 2ª
    _rodar(AGORA + timedelta(days=1), envio_real=True, enviador=env)        # 3ª
    e = _envios()[0]
    assert (e["estado"], e["motivo_bloqueio"]) == ("bloqueado", "falhas_repetidas")
    assert json.loads(e["contexto"])["tentativas"] == 3
    _rodar(AGORA + timedelta(days=2), envio_real=True, enviador=env)
    assert len(env.textos) == 3


def test_modelo_aprovado_depois_volta_a_tentar():
    _ligar()
    _lead("5581", "Ana Souza")
    _conversa("5581", canal="whatsapp")
    env = EnviadorFalso()
    _rodar(envio_real=True, enviador=env)
    assert _envios()[0]["motivo_bloqueio"] == "modelo_nao_aprovado"
    registrar_status(1, "retomada_geral", "aprovado")
    _rodar(AGORA + timedelta(hours=7), envio_real=True, enviador=env)
    assert env.modelos == ["retomada_geral"]
    assert _envios()[0]["estado"] == "enviado"


# ---------------------------------------------------------------- vagas da rodada
def test_pulados_nao_ocupam_vaga():
    _ligar()
    for lead in ("111", "222", "333"):
        _conversa(lead)
    r1 = _rodar(max_por_loja=2)
    r2 = _rodar(max_por_loja=2)
    assert r1["simulado"] == 2 and r2["simulado"] == 1
    assert len(_envios()) == 3


# ---------------------------------------------------------------- retomada no contexto
def test_retomada_recente_devolve_o_texto():
    _enviar_retomada()
    r = retomada_recente(1, "111", "telegram", AGORA + timedelta(hours=1))
    assert r["texto"] == TEXTO_IA and r["toque"] == 1
    assert r["enviado_em"] == AGORA


def test_retomada_antiga_sai_do_contexto():
    _enviar_retomada()
    assert retomada_recente(1, "111", "telegram", AGORA + timedelta(days=4)) is None


def test_simulacao_nao_entra_no_contexto():
    _ligar()
    _conversa("111")
    _rodar()                                       # só simula
    assert retomada_recente(1, "111", "telegram", AGORA + timedelta(hours=1)) is None


def test_retomada_e_por_canal_e_por_loja():
    _enviar_retomada()
    agora = AGORA + timedelta(hours=1)
    assert retomada_recente(1, "111", "whatsapp", agora) is None
    loja2 = lojas.criar_loja("Loja 2")
    assert retomada_recente(loja2, "111", "telegram", agora) is None


def test_prompt_ganha_a_camada_da_retomada():
    from app.core.montagem import ferramentas_da_loja, montar_prompt
    loja = lojas.carregar_loja(1)
    agora = (AGORA + timedelta(hours=1)).astimezone(ZoneInfo("America/Recife"))
    retomada = {"toque": 1, "texto": TEXTO_IA, "enviado_em": AGORA}
    com = montar_prompt(loja, ferramentas_da_loja(loja), agora, retomada=retomada)
    sem = montar_prompt(loja, ferramentas_da_loja(loja), agora)
    assert "RETOMADA QUE VOCÊ MANDOU" in com and TEXTO_IA in com
    assert "em 03/11 às 09:00" in com                 # no horário da loja
    assert "RETOMADA QUE VOCÊ MANDOU" not in sem


def test_agente_le_a_retomada_do_banco():
    from app.core.agent import _retomada_da_conversa
    _enviar_retomada()
    estado = {"lead_id": "111", "canal": "telegram", "loja_id": 1}
    r = _retomada_da_conversa(estado, 1, AGORA + timedelta(hours=1))
    assert r["texto"] == TEXTO_IA


def test_agente_sem_lead_segue_normal():
    from app.core.agent import _retomada_da_conversa
    assert _retomada_da_conversa({"loja_id": 1}, 1, AGORA) is None


# ---------------------------------------------------------------- taxa de resposta
def test_resumo_de_respostas():
    _enviar_retomada()
    desde = AGORA - timedelta(days=1)
    ate = AGORA + timedelta(days=1)
    assert resumo_respostas(1, desde, ate) == {"enviados": 1, "respondidos": 0, "taxa": 0.0}
    _mensagem("111", "telegram", "cliente", AGORA + timedelta(hours=2), "opa, ainda tenho interesse")
    assert resumo_respostas(1, desde, ate) == {"enviados": 1, "respondidos": 1, "taxa": 1.0}

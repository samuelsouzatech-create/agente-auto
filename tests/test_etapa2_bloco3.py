"""
Testes da Etapa 2, Bloco 3: job de remarketing. Tudo offline:
IA falsa (RedatorFalso), envio falso (EnviadorFalso), relógio fixo.
"""
import json
from datetime import datetime, timedelta, timezone

from banco import conectar
from app import lojas
from app.custos import Uso
from app.jobs import remarketing as rmk
from app.relogio import para_banco
from app.resultado_envio import ResultadoEnvio
from app.templates import registrar_status

AGORA = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)   # terça, 09:00 em Recife
TEXTO_IA = "Oi! Conseguiu pensar no Corolla? Se quiser, separo um horário para você ver de perto."


# ---------------------------------------------------------------- apoio
class EnviadorFalso:
    def __init__(self, ok=True, codigo=None):
        self.ok, self.codigo = ok, codigo
        self.textos, self.modelos = [], []

    def _resultado(self):
        return ResultadoEnvio(ok=self.ok, id_externo="x1" if self.ok else "",
                              codigo_erro=self.codigo, detalhe="" if self.ok else "recusado")

    async def texto(self, loja_id, canal, lead_id, texto):
        self.textos.append((loja_id, canal, lead_id, texto))
        return self._resultado()

    async def modelo(self, loja_id, lead_id, modelo, valores):
        self.modelos.append((loja_id, lead_id, modelo.nome, dict(valores)))
        return self._resultado()


class RedatorFalso:
    def __init__(self, texto=TEXTO_IA, erro=None):
        self.texto, self.erro, self.chamadas = texto, erro, 0

    def __call__(self, loja, lead_id, canal, toque, dados, historico):
        self.chamadas += 1
        if self.erro:
            raise self.erro
        return self.texto, Uso(120, 30, 0)


def _ligar(loja_id=1, limite=50):
    lojas.salvar_config(loja_id, {"modulos.remarketing": True,
                                  "remarketing.limite_mensal": limite}, "teste")


def _mensagem(lead_id, canal, direcao, quando, texto="oi", loja_id=1):
    c = conectar()
    c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
              "VALUES (?, ?, ?, ?, ?, ?)", (lead_id, loja_id, canal, direcao, texto, para_banco(quando)))
    c.commit()
    c.close()


def _conversa(lead_id, canal="telegram", loja_id=1, ha=timedelta(hours=72)):
    _mensagem(lead_id, canal, "cliente", AGORA - ha, "quanto tá o Corolla?", loja_id)
    _mensagem(lead_id, canal, "leo", AGORA - ha + timedelta(minutes=1), "R$ 135.000", loja_id)


def _lead(lead_id, nome, loja_id=1):
    c = conectar()
    c.execute("INSERT INTO leads (lead_id, loja_id, nome) VALUES (?, ?, ?)", (lead_id, loja_id, nome))
    c.commit()
    c.close()


def _carro_de_interesse(lead_id, status="disponivel", loja_id=1):
    c = conectar()
    cur = c.execute("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) "
                    "VALUES (?, 'Toyota', 'Corolla', 2021, 32000, 'Preto', 'Automático', 135000, ?)",
                    (loja_id, status))
    c.execute("INSERT INTO interesse_veiculo (loja_id, lead_id, veiculo_id) VALUES (?, ?, ?)",
              (loja_id, lead_id, cur.lastrowid))
    c.commit()
    c.close()


def _consulta(sql, parametros=()):
    c = conectar()
    linhas = [dict(l) for l in c.execute(sql, parametros).fetchall()]
    c.close()
    return linhas


def _envios(loja_id=1):
    return _consulta("SELECT * FROM remarketing_envios WHERE loja_id = ? ORDER BY toque", (loja_id,))


def _rodar(agora=AGORA, **kw):
    kw.setdefault("pausa_s", 0)
    kw.setdefault("redator", RedatorFalso())
    kw.setdefault("enviador", EnviadorFalso())
    kw.setdefault("envio_real", False)
    return rmk.rodar_remarketing(agora, **kw)


# ---------------------------------------------------------------- modo
def test_modo_padrao_e_simulacao(monkeypatch):
    monkeypatch.delenv("REMARKETING_ENVIO_REAL", raising=False)
    assert rmk.envio_real_ligado() is False
    monkeypatch.setenv("REMARKETING_ENVIO_REAL", "1")
    assert rmk.envio_real_ligado() is True


def test_modulo_desligado_nao_faz_nada():
    _conversa("111")
    r = _rodar()
    assert _envios() == []
    assert sum(r.values()) == 0


# ---------------------------------------------------------------- simulação
def test_simulacao_grava_o_texto_e_nao_envia():
    _ligar()
    _conversa("111")
    red, env = RedatorFalso(), EnviadorFalso()
    r = _rodar(redator=red, enviador=env)
    assert r["simulado"] == 1 and env.textos == []
    e = _envios()[0]
    assert (e["estado"], e["toque"], e["categoria"]) == ("simulado", 1, "livre")
    assert json.loads(e["contexto"])["texto"] == TEXTO_IA
    assert _consulta("SELECT tipo FROM uso_custos WHERE loja_id = 1") == [{"tipo": "remarketing_simulado"}]
    assert _consulta("SELECT 1 FROM mensagens WHERE autor = 'remarketing'") == []


def test_simulacao_nao_repete_no_ciclo_seguinte():
    _ligar()
    _conversa("111")
    red = RedatorFalso()
    _rodar(redator=red)
    r2 = _rodar(redator=red)
    assert red.chamadas == 1 and r2["pulado"] == 1


# ---------------------------------------------------------------- envio real (Telegram)
def test_envio_real_pelo_telegram():
    _ligar()
    _conversa("111")
    env = EnviadorFalso()
    r = _rodar(envio_real=True, enviador=env)
    assert r["enviado"] == 1
    assert env.textos == [(1, "telegram", "111", TEXTO_IA)]
    e = _envios()[0]
    assert e["estado"] == "enviado" and e["enviado_em"]
    conversa = _consulta("SELECT direcao, conteudo FROM mensagens WHERE autor = 'remarketing'")
    assert conversa == [{"direcao": "leo", "conteudo": TEXTO_IA}]
    custo = _consulta("SELECT tipo, tokens_entrada, msgs_servico FROM uso_custos WHERE loja_id = 1")
    assert custo == [{"tipo": "remarketing", "tokens_entrada": 120, "msgs_servico": 0}]


def test_simulado_vira_enviado_quando_liga_o_envio():
    _ligar()
    _conversa("111")
    _rodar()
    _rodar(envio_real=True)
    envios = _envios()
    assert len(envios) == 1 and envios[0]["estado"] == "enviado"


def test_depois_de_enviado_espera_o_intervalo_e_manda_o_toque_2():
    _ligar()
    _conversa("111")
    env = EnviadorFalso()
    _rodar(envio_real=True, enviador=env)
    _rodar(AGORA + timedelta(hours=1), envio_real=True, enviador=env)
    assert len(env.textos) == 1
    _rodar(AGORA + timedelta(days=6), envio_real=True, enviador=env)   # segunda-feira
    assert len(env.textos) == 2
    assert [e["toque"] for e in _envios()] == [1, 2]


def test_cliente_respondeu_nao_recebe_mais():
    _ligar()
    _conversa("111")
    env = EnviadorFalso()
    _rodar(envio_real=True, enviador=env)
    _mensagem("111", "telegram", "cliente", AGORA + timedelta(hours=2), "opa, ainda tenho interesse")
    _rodar(AGORA + timedelta(days=6), envio_real=True, enviador=env)
    assert len(env.textos) == 1


# ---------------------------------------------------------------- WhatsApp (modelo)
def test_whatsapp_janela_fechada_usa_modelo_na_simulacao():
    _ligar()
    _lead("5581", "Ana Souza")
    _conversa("5581", canal="whatsapp")
    red = RedatorFalso()
    _rodar(redator=red)
    e = _envios()[0]
    assert (e["estado"], e["modelo"], e["categoria"]) == ("simulado", "retomada_geral", "marketing")
    texto = json.loads(e["contexto"])["texto"]
    assert "Ana" in texto and "Léo" in texto and "Loja 1" in texto
    assert red.chamadas == 0


def test_modelo_nao_aprovado_nao_sai():
    _ligar()
    _lead("5581", "Ana Souza")
    _conversa("5581", canal="whatsapp")
    env = EnviadorFalso()
    _rodar(envio_real=True, enviador=env)
    e = _envios()[0]
    assert (e["estado"], e["motivo_bloqueio"]) == ("bloqueado", "modelo_nao_aprovado")
    assert env.modelos == []


def test_modelo_aprovado_sai_e_registra_custo_da_meta():
    _ligar()
    _lead("5581", "Ana Souza")
    _conversa("5581", canal="whatsapp")
    registrar_status(1, "retomada_geral", "aprovado")
    env = EnviadorFalso()
    _rodar(envio_real=True, enviador=env)
    assert env.modelos[0][2] == "retomada_geral" and env.modelos[0][3]["nome"] == "Ana"
    assert _envios()[0]["estado"] == "enviado"
    custo = _consulta("SELECT tipo, msgs_marketing FROM uso_custos WHERE loja_id = 1")
    assert custo == [{"tipo": "remarketing", "msgs_marketing": 1}]


def test_sem_nome_nao_manda_modelo():
    _ligar()
    _conversa("5581", canal="whatsapp")
    _rodar()
    e = _envios()[0]
    assert (e["estado"], e["motivo_bloqueio"]) == ("bloqueado", "faltam_dados")


def test_carro_de_interesse_disponivel_usa_retomada_interesse():
    _ligar()
    _lead("5581", "Ana Souza")
    _conversa("5581", canal="whatsapp")
    _carro_de_interesse("5581")
    _rodar()
    e = _envios()[0]
    assert e["modelo"] == "retomada_interesse"
    assert "Toyota Corolla 2021" in json.loads(e["contexto"])["texto"]


def test_carro_vendido_usa_retomada_geral():
    _ligar()
    _lead("5581", "Ana Souza")
    _conversa("5581", canal="whatsapp")
    _carro_de_interesse("5581", status="vendido")
    _rodar()
    assert _envios()[0]["modelo"] == "retomada_geral"


# ---------------------------------------------------------------- texto da IA
def test_ia_falhou_usa_texto_reserva():
    _ligar()
    _conversa("111")
    env = EnviadorFalso()
    _rodar(envio_real=True, enviador=env, redator=RedatorFalso(erro=RuntimeError("fora do ar")))
    assert "Léo aqui, da Loja 1" in env.textos[0][3]
    assert json.loads(_envios()[0]["contexto"])["origem"] == "reserva"


def test_texto_com_cara_de_robo_vira_reserva():
    _ligar()
    _conversa("111")
    env = EnviadorFalso()
    _rodar(envio_real=True, enviador=env,
           redator=RedatorFalso("Oi! Se não quiser mais mensagens, responda SAIR."))
    assert "SAIR" not in env.textos[0][3]


# ---------------------------------------------------------------- falhas
def test_falha_no_envio_so_repete_depois_de_6h():
    _ligar()
    _conversa("111")
    env = EnviadorFalso(ok=False)
    _rodar(envio_real=True, enviador=env)
    _rodar(AGORA + timedelta(hours=1), envio_real=True, enviador=env)
    assert len(env.textos) == 1
    _rodar(AGORA + timedelta(hours=7), envio_real=True, enviador=env)
    assert len(env.textos) == 2
    e = _envios()[0]
    assert (e["estado"], e["motivo_bloqueio"]) == ("falhou", "erro_no_envio")


def test_recusa_por_janela_fechada_vira_motivo():
    _ligar()
    _conversa("111")
    _rodar(envio_real=True, enviador=EnviadorFalso(ok=False, codigo=131047))
    assert _envios()[0]["motivo_bloqueio"] == "janela_fechada"


# ---------------------------------------------------------------- quem não recebe
def test_conversa_com_vendedor_nao_recebe():
    _ligar()
    _conversa("111")
    c = conectar()
    c.execute("INSERT INTO handoffs (lead_id, loja_id, estado) VALUES ('111', 1, 'aguardando_humano')")
    c.commit()
    c.close()
    _rodar(envio_real=True)
    assert _envios() == []


def test_limite_por_rodada():
    _ligar()
    for lead in ("111", "222", "333"):
        _conversa(lead)
    r = _rodar(max_por_loja=2)
    assert r["simulado"] == 2


def test_lojas_separadas():
    _ligar()
    loja2 = lojas.criar_loja("Loja 2")          # remarketing desligado
    _conversa("111")
    _conversa("999", loja_id=loja2)
    _rodar()
    assert len(_envios(1)) == 1 and _envios(loja2) == []


def test_erro_numa_loja_nao_para_as_outras(monkeypatch):
    loja2 = lojas.criar_loja("Loja 2")
    _ligar(1)
    _ligar(loja2)
    _conversa("111")
    original = rmk.elegiveis

    def elegiveis_com_defeito(loja_id, agora):
        if loja_id == loja2:
            raise RuntimeError("defeito")
        return original(loja_id, agora)

    monkeypatch.setattr(rmk, "elegiveis", elegiveis_com_defeito)
    _rodar(lojas=[loja2, 1])
    assert len(_envios(1)) == 1


# ---------------------------------------------------------------- runner e linha de comando
def test_runner_chama_o_remarketing(monkeypatch):
    from app.jobs import runner
    chamadas = []

    def falso():
        chamadas.append(1)
        return dict.fromkeys(rmk.ESTADOS, 0)

    monkeypatch.setattr(runner, "rodar_ciclo", lambda: {"handoffs": 0, "gastos": 0})
    monkeypatch.setattr(runner, "rodar_remarketing", falso)
    assert runner.main(["--sem-trava", "--uma-vez"]) == 0
    assert chamadas == [1]


def test_runner_sem_remarketing(monkeypatch):
    from app.jobs import runner
    chamadas = []
    monkeypatch.setattr(runner, "rodar_ciclo", lambda: {"handoffs": 0, "gastos": 0})
    monkeypatch.setattr(runner, "rodar_remarketing", lambda: chamadas.append(1))
    assert runner.main(["--sem-trava", "--uma-vez", "--sem-remarketing"]) == 0
    assert chamadas == []


def test_linha_de_comando_so_simula(monkeypatch, capsys):
    _ligar()
    _conversa("111")
    monkeypatch.setattr(rmk, "escrever_com_ia", RedatorFalso())
    assert rmk.main(["--loja", "1", "--agora", "2026-11-03T09:00"]) == 0
    saida = capsys.readouterr().out
    assert "SIMULAÇÃO" in saida and "111" in saida
    assert _envios()[0]["estado"] == "simulado"

"""
Testes da Etapa 2, Bloco 8 (fechamento): carro vendido oferece um parecido
ou sai da fila; limite do mês acabou avisa gestor e operador. Tudo offline.
"""
import json
from datetime import datetime, timedelta, timezone

from banco import conectar
from app import avisos, lojas
from app.custos import Uso
from app.jobs import remarketing as rmk
from app.relogio import para_banco
from app.resultado_envio import ResultadoEnvio

AGORA = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)   # terça, 09:00 em Recife


class EnviadorFalso:
    def __init__(self):
        self.textos, self.modelos = [], []

    async def texto(self, loja_id, canal, lead_id, texto):
        self.textos.append((loja_id, canal, lead_id, texto))
        return ResultadoEnvio(ok=True, id_externo="x1")

    async def modelo(self, loja_id, lead_id, modelo, valores):
        self.modelos.append((loja_id, lead_id, modelo.nome, dict(valores)))
        return ResultadoEnvio(ok=True, id_externo="x1")


class RedatorFalso:
    def __init__(self, erro=None):
        self.erro, self.dados = erro, None

    def __call__(self, loja, lead_id, canal, toque, dados, historico):
        self.dados = dict(dados)
        if self.erro:
            raise self.erro
        return "Oi! Quer ver de perto essa opção?", Uso(100, 20, 0)


def _ligar(loja_id=1, limite=50):
    lojas.salvar_config(loja_id, {"modulos.remarketing": True,
                                  "remarketing.limite_mensal": limite}, "teste")


def _mensagem(lead_id, canal, direcao, quando, loja_id=1):
    c = conectar()
    c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
              "VALUES (?, ?, ?, ?, 'oi', ?)", (lead_id, loja_id, canal, direcao, para_banco(quando)))
    c.commit()
    c.close()


def _conversa(lead_id, canal="telegram", loja_id=1):
    _mensagem(lead_id, canal, "cliente", AGORA - timedelta(hours=72), loja_id)
    _mensagem(lead_id, canal, "leo", AGORA - timedelta(hours=71), loja_id)


def _lead(lead_id, nome, loja_id=1):
    c = conectar()
    c.execute("INSERT INTO leads (lead_id, loja_id, nome) VALUES (?, ?, ?)", (lead_id, loja_id, nome))
    c.commit()
    c.close()


def _carro(marca, modelo, ano, preco, status="disponivel", loja_id=1):
    c = conectar()
    cur = c.execute("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) "
                    "VALUES (?, ?, ?, ?, 30000, 'Prata', 'Automático', ?, ?)",
                    (loja_id, marca, modelo, ano, preco, status))
    c.commit()
    c.close()
    return cur.lastrowid


def _interesse_vendido(lead_id, loja_id=1):
    carro_id = _carro("Toyota", "Corolla", 2021, 135000, "vendido", loja_id)
    c = conectar()
    c.execute("INSERT INTO interesse_veiculo (loja_id, lead_id, veiculo_id) VALUES (?, ?, ?)",
              (loja_id, lead_id, carro_id))
    c.commit()
    c.close()


def _envios(loja_id=1):
    c = conectar()
    linhas = [dict(l) for l in c.execute(
        "SELECT * FROM remarketing_envios WHERE loja_id = ? ORDER BY lead_id, toque", (loja_id,))]
    c.close()
    return linhas


def _rodar(agora=AGORA, **kw):
    kw.setdefault("pausa_s", 0)
    kw.setdefault("redator", RedatorFalso())
    kw.setdefault("enviador", EnviadorFalso())
    kw.setdefault("envio_real", False)
    return rmk.rodar_remarketing(agora, **kw)


# ---------------------------------------------------------------- carro vendido
def test_vendido_sem_parecido_bloqueia_e_nao_envia():
    _ligar()
    _lead("5581", "Ana Souza")
    _conversa("5581", canal="whatsapp")
    _interesse_vendido("5581")
    env = EnviadorFalso()
    _rodar(envio_real=True, enviador=env)
    e = _envios()[0]
    assert (e["estado"], e["motivo_bloqueio"]) == ("bloqueado", "carro_vendido")
    assert env.modelos == [] and env.textos == []


def test_vendido_com_parecido_usa_modelo_de_alternativa():
    _ligar()
    _lead("5581", "Ana Souza")
    _conversa("5581", canal="whatsapp")
    _interesse_vendido("5581")
    alt = _carro("Toyota", "Corolla", 2020, 128000)
    _carro("Honda", "Civic", 2020, 130000)
    _rodar()
    e = _envios()[0]
    assert (e["estado"], e["modelo"]) == ("simulado", "retomada_alternativa")
    contexto = json.loads(e["contexto"])
    assert "Toyota Corolla 2020" in contexto["texto"]
    assert contexto["alternativa_de"] == "Toyota Corolla 2021"
    assert e["veiculo_id"] == alt


def test_parecido_fora_da_faixa_de_preco_nao_conta():
    _ligar()
    _lead("5581", "Ana Souza")
    _conversa("5581", canal="whatsapp")
    _interesse_vendido("5581")
    _carro("Fiat", "Uno", 2015, 40000)
    _rodar()
    assert _envios()[0]["motivo_bloqueio"] == "carro_vendido"


def test_parecido_de_outra_loja_nao_conta():
    loja2 = lojas.criar_loja("Loja 2")
    _ligar()
    _lead("5581", "Ana Souza")
    _conversa("5581", canal="whatsapp")
    _interesse_vendido("5581")
    _carro("Toyota", "Corolla", 2020, 130000, loja_id=loja2)
    _rodar()
    assert _envios()[0]["motivo_bloqueio"] == "carro_vendido"


def test_ia_recebe_o_vendido_e_a_alternativa():
    _ligar()
    _conversa("111")
    _interesse_vendido("111")
    _carro("Honda", "Civic", 2021, 140000)
    red = RedatorFalso()
    _rodar(redator=red)
    assert red.dados["alternativa"] == "Honda Civic 2021"
    prompt = rmk._prompt_redator(lojas.carregar_loja(1), 1, red.dados, [])
    assert "JÁ FOI VENDIDO" in prompt and "Honda Civic 2021" in prompt


def test_texto_reserva_oferece_a_alternativa():
    _ligar()
    _conversa("111")
    _interesse_vendido("111")
    _carro("Honda", "Civic", 2021, 140000)
    env = EnviadorFalso()
    _rodar(envio_real=True, enviador=env, redator=RedatorFalso(erro=RuntimeError("fora do ar")))
    texto = env.textos[0][3]
    assert "vendido" in texto and "Honda Civic 2021" in texto


# ---------------------------------------------------------------- limite do mês
def test_limite_acabou_avisa_gestor_e_operador(monkeypatch):
    chamadas = []
    monkeypatch.setattr(avisos, "avisar_uma_vez",
                        lambda loja_id, tipo, ref, destinos, texto:
                        chamadas.append((loja_id, tipo, ref, texto)) or {"concluido": True})
    _ligar(limite=1)
    _conversa("111")
    _conversa("222")
    _rodar(envio_real=True)                 # gasta a única vaga
    assert chamadas == []
    _rodar(envio_real=True)                 # a outra pessoa fica barrada pelo limite
    assert len(chamadas) == 1
    loja_id, tipo, ref, texto = chamadas[0]
    assert (loja_id, tipo, ref) == (1, "limite_mensal", "loja:1:2026-11")
    assert "limite de 1" in texto


def test_com_vagas_nao_avisa(monkeypatch):
    chamadas = []
    monkeypatch.setattr(avisos, "avisar_uma_vez", lambda *a, **k: chamadas.append(a))
    _ligar(limite=10)
    _conversa("111")
    _rodar(envio_real=True)
    assert chamadas == []

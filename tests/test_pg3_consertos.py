"""
PG3 (Maratona Postgres): defeitos achados pelo teste de carga, com teste offline (suíte normal).

1. Com 10 lojas ao mesmo tempo, o Redis dava "MaxConnectionsError": o pool padrão da biblioteca
   (100 conexões) dá ERRO na hora quando está cheio, e a mensagem do cliente se perdia. Agora o
   pool ESPERA uma conexão livre.
2. Quando o buffer do debounce voltava vazio, o Léo rodava um turno com mensagem vazia. Agora
   buffer vazio não vira turno.
"""
import asyncio

import fakeredis.aioredis
import redis.asyncio as redis

import app.redis_cliente as rc
import app.redis_debounce as debounce


def test_redis_espera_conexao_livre_em_vez_de_dar_erro():
    pool = rc.redis_cliente.connection_pool
    assert isinstance(pool, redis.BlockingConnectionPool)
    assert pool.max_connections == rc.REDIS_MAX_CONEXOES >= 100
    assert pool.timeout == rc.REDIS_ESPERA_S > 0


def test_pool_cheio_espera_e_nao_perde_o_pedido():
    """Com 2 conexões e 30 pedidos ao mesmo tempo, todos terminam (esperando a vez)."""
    falso = fakeredis.aioredis.FakeRedis(decode_responses=True)
    pool = redis.BlockingConnectionPool(max_connections=2, timeout=5,
                                        connection_class=falso.connection_pool.connection_class,
                                        **falso.connection_pool.connection_kwargs)
    cliente = redis.Redis(connection_pool=pool)

    async def rodar():
        await asyncio.gather(*(cliente.rpush("fila", str(i)) for i in range(30)))
        return await cliente.llen("fila")

    assert asyncio.run(rodar()) == 30


class _BufferQueSome:
    """Redis de verdade (falso, em memória), mas o buffer some antes de o dono ler
    (expirou ou se perdeu): a hora continua lá, a lista não."""

    def __init__(self):
        self.real = fakeredis.aioredis.FakeRedis(decode_responses=True)

    def __getattr__(self, nome):
        return getattr(self.real, nome)

    async def rpush(self, chave, valor):
        return 0                                  # a mensagem não fica na lista


def test_buffer_vazio_nao_vira_turno(monkeypatch):
    monkeypatch.setattr(debounce, "redis_cliente", _BufferQueSome())
    monkeypatch.setattr(debounce, "DEBOUNCE_SEGUNDOS", 0)
    assert asyncio.run(debounce.acumular_e_esperar("5581999998888", "oi", loja_id=1)) is None


def test_buffer_com_texto_continua_igual(monkeypatch):
    falso = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(debounce, "redis_cliente", falso)
    monkeypatch.setattr(debounce, "DEBOUNCE_SEGUNDOS", 0)
    assert asyncio.run(debounce.acumular_e_esperar("5581999998888", "oi tudo bem", loja_id=1)) == "oi tudo bem"


class _MensagemNoMeio:
    """Redis falso que, logo depois de o dono da rajada esvaziar o buffer, deixa chegar a
    próxima mensagem do mesmo cliente (a ordem que perdia mensagem no teste de carga)."""

    def __init__(self, real, quando_esvaziar):
        self.real = real
        self.quando_esvaziar = quando_esvaziar
        self.disparou = False

    def __getattr__(self, nome):
        return getattr(self.real, nome)

    def pipeline(self, *a, **k):
        passo = self.real.pipeline(*a, **k)
        original = passo.execute
        gancho = self

        async def execute(*aa, **kk):
            resultado = await original(*aa, **kk)
            if not gancho.disparou:
                gancho.disparou = True
                await gancho.quando_esvaziar()
            return resultado
        passo.execute = execute
        return passo


def test_mensagem_que_chega_quando_o_dono_termina_nao_se_perde(monkeypatch):
    real = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(debounce, "DEBOUNCE_SEGUNDOS", 0.2)
    lead, resultados = "5581999998888", {}

    async def rodar():
        async def chega_a_proxima():
            # a mensagem 2 chega e grava a hora dela ANTES de o dono terminar
            resultados["m2"] = asyncio.create_task(debounce.acumular_e_esperar(lead, "m2", loja_id=1))
            await asyncio.sleep(0.05)

        monkeypatch.setattr(debounce, "redis_cliente", _MensagemNoMeio(real, chega_a_proxima))
        resultados["m1"] = await debounce.acumular_e_esperar(lead, "m1", loja_id=1)
        resultados["m2"] = await resultados["m2"]

    asyncio.run(rodar())
    assert resultados["m1"] == "m1"
    assert resultados["m2"] == "m2"               # antes do conserto: None (mensagem perdida)

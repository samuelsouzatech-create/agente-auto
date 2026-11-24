"""
E2-1 (Plano Mestre, Fase 4): limite DIÁRIO da reativação por loja.

O limite mensal e o lote de 500 já existiam; faltava o do dia. Agora a reativação conta os
envios do dia local da loja e para no limite (remarketing.limite_diario_reativacao). O resto
fica na fila, na mesma ordem, para o dia seguinte. Vale também na simulação.
Tudo offline: o envio é um falso.
"""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from banco import conectar
from app import reativacao, templates
from app.config_tela import CAMPOS_AVULSOS_DO_ASSUNTO, PLANO_E_LIMITES
from app.importacao import importar, ler_planilha
from app.jobs.reativacao import rodar_reativacao
from app.reativacao import usados_no_dia
from app.lojas import CHAVES_DO_OPERADOR, carregar_loja, criar_loja, salvar_config
from app.painel_envios import uso_diario_reativacao
from app.relogio import para_banco

HOJE = date(2026, 10, 30)
SEXTA = datetime(2026, 10, 30, 13, 0, tzinfo=timezone.utc)     # 10h no Recife
SABADO = SEXTA + timedelta(days=1)


class EnviadorFalso:
    def __init__(self):
        self.chamadas = []

    async def modelo(self, loja_id, lead_id, modelo, valores):
        self.chamadas.append((loja_id, lead_id))
        return SimpleNamespace(ok=True, detalhe="")


def _base(n: int) -> str:
    linhas = ["nome;telefone"] + [f"Cliente {i};8198{i:07d}" for i in range(1, n + 1)]
    return "\n".join(linhas) + "\n"


def _preparar(loja_id=1, *, contatos=10, diario=3, mensal=1000):
    salvar_config(loja_id, {"modulos.remarketing": True, "remarketing.limite_mensal": mensal,
                            "remarketing.limite_diario_reativacao": diario}, "Samuel")
    importar(loja_id, ler_planilha(_base(contatos).encode("utf-8"), hoje=HOJE), usuario="Samuel",
             consentimento=True, arquivo="base.csv")
    for nome in (reativacao.MODELO_CLIENTE, reativacao.MODELO_CONTATO):
        templates.registrar_status(loja_id, nome, "aprovado")
    reativacao.montar_fila(loja_id, usuario="Samuel", agora=SEXTA, maximo=min(contatos, 500))


def _rodar(agora=SEXTA, *, real=True, lojas=(1,), enviador=None, rodadas=1):
    total = {}
    for _ in range(rodadas):
        t = rodar_reativacao(agora, envio_real=real, enviador=enviador or EnviadorFalso(),
                             pausa_s=0, lojas=list(lojas))
        for k, v in t.items():
            total[k] = total.get(k, 0) + v
    return total


def _telefones(estado, loja_id=1):
    c = conectar()
    try:
        return [l[0] for l in c.execute(
            "SELECT telefone FROM reativacao WHERE loja_id = ? AND estado = ? ORDER BY id",
            (loja_id, estado)).fetchall()]
    finally:
        c.close()


def test_campo_novo_e_do_operador_com_valor_inicial_baixo():
    assert "remarketing.limite_diario_reativacao" in CHAVES_DO_OPERADOR
    assert "remarketing.limite_diario_reativacao" in CAMPOS_AVULSOS_DO_ASSUNTO[PLANO_E_LIMITES]
    assert carregar_loja(1).get("remarketing.limite_diario_reativacao") == 30


def test_limite_3_com_10_na_fila_manda_3_hoje_e_3_amanha_na_mesma_ordem():
    _preparar(diario=3)
    na_fila = _telefones("na_fila")
    assert len(na_fila) == 10
    assert _rodar(rodadas=4)["enviado"] == 3               # várias rodadas no mesmo dia: só 3
    assert _telefones("enviado") == na_fila[:3]
    assert _rodar(SABADO, rodadas=4)["enviado"] == 3
    assert _telefones("enviado") == na_fila[:6]
    assert _telefones("na_fila") == na_fila[6:]


def test_limite_0_nao_envia_nada():
    _preparar(diario=0)
    enviador = EnviadorFalso()
    assert _rodar(enviador=enviador).get("enviado", 0) == 0
    assert enviador.chamadas == []


def test_a_virada_do_dia_respeita_o_fuso_da_loja():
    _preparar(diario=3)
    c = conectar()
    try:
        # 01:00 UTC do sábado = 22:00 de sexta no Recife: conta para a SEXTA.
        c.execute("UPDATE reativacao SET estado = 'enviado', enviado_em = ? WHERE id = "
                  "(SELECT MIN(id) FROM reativacao WHERE loja_id = 1)",
                  (para_banco(datetime(2026, 10, 31, 1, 0, tzinfo=timezone.utc)),))
        c.commit()
    finally:
        c.close()
    loja = carregar_loja(1)
    assert usados_no_dia(loja, SEXTA, real=True) == 1
    assert usados_no_dia(loja, SABADO, real=True) == 0
    assert _rodar()["enviado"] == 2                         # sexta: só cabem mais 2


def test_duas_lojas_com_limites_diferentes():
    loja_b = criar_loja("Loja B")
    _preparar(1, diario=2)
    _preparar(loja_b, diario=5)
    _rodar(lojas=(1, loja_b), rodadas=3)
    assert len(_telefones("enviado", 1)) == 2
    # A loja B ainda está "em teste" (P7): sai em simulação, e o limite dela vale igual.
    assert len(_telefones("simulado", loja_b)) == 5
    assert len(_telefones("na_fila", loja_b)) == 5


def test_simulacao_tambem_respeita_o_limite():
    _preparar(diario=4)
    enviador = EnviadorFalso()
    assert _rodar(real=False, enviador=enviador, rodadas=3)["simulado"] == 4
    assert enviador.chamadas == []
    assert len(_telefones("na_fila")) == 6


def test_o_limite_mensal_continua_valendo_junto():
    _preparar(diario=10, mensal=2)
    assert _rodar(rodadas=3)["enviado"] == 2


def test_base_de_600_contatos_nao_passa_do_limite_do_dia():
    _preparar(contatos=600, diario=30)
    reativacao.montar_fila(1, usuario="Samuel", agora=SEXTA, maximo=100)   # o resto da base
    assert len(_telefones("na_fila")) == 600
    enviador = EnviadorFalso()
    # O relógio roda a cada 5 min: 10 horas de envio no mesmo dia.
    for minutos in range(0, 600, 5):
        rodar_reativacao(SEXTA + timedelta(minutes=minutos), envio_real=True, enviador=enviador,
                         pausa_s=0, lojas=[1])
    assert len(enviador.chamadas) == 30
    assert uso_diario_reativacao(1, SEXTA) == {"usados": 30, "limite": 30}

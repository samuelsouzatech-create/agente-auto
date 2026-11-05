"""
S6 (Fase 3): Mensagens automáticas.
- A fotografia da loja e o avaliar() decidem IGUAL, para todos os motivos.
- A reconferência do robô passa pela mesma decisão (não uma cópia).
- Sem consulta por cliente: 50 e 500 clientes fazem o mesmo número de consultas.
- "No mês": uma consulta agrupada por tipo; mostra só o que ficou gravado.
Tudo offline, com duas lojas.
"""
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from banco import conectar
from app import elegibilidade as el
from app import lojas
from app import mensagens_automaticas as ma
from app.interesse import registrar_situacao
from app.lojas import criar_loja, salvar_config
from app.relogio import para_banco

RAIZ = Path(__file__).resolve().parent.parent
AGORA = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)      # terça, 12h em Recife
NOITE = datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc)       # terça, 22h em Recife
LIGADO = {"modulos.remarketing": True, "remarketing.limite_mensal": 100}
L = "5581999990001"


# ---------------------------------------------------------------- apoio

def _sql(sql, parametros=()):
    c = conectar()
    try:
        c.execute(sql, parametros)
        c.commit()
    finally:
        c.close()


def _msg(loja_id, lead, direcao, horas, canal="whatsapp"):
    _sql("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
         "VALUES (?, ?, ?, ?, 'x', ?)",
         (lead, loja_id, canal, direcao, para_banco(AGORA - timedelta(hours=horas))))


def _conversa(loja_id, lead=L, horas=49, canal="whatsapp"):
    _msg(loja_id, lead, "cliente", horas, canal)
    _msg(loja_id, lead, "leo", horas, canal)


def _toque(loja_id, lead, toque, horas, estado="enviado", canal="whatsapp"):
    quando = para_banco(AGORA - timedelta(hours=horas))
    _sql("INSERT INTO remarketing_envios (loja_id, lead_id, canal, toque, estado, enviado_em, "
         "criado_em) VALUES (?, ?, ?, ?, ?, ?, ?)",
         (loja_id, lead, canal, toque, estado, quando if estado == "enviado" else None, quando))


def _bloqueio(loja_id, lead, tipo, passo):
    _sql("INSERT INTO bloqueios_envio (loja_id, lead_id, tipo, passo, criado_por, criado_em) "
         "VALUES (?, ?, ?, ?, 'Ana', ?)", (loja_id, lead, tipo, passo, para_banco(AGORA)))


def _loja_nova(config=None):
    nova = criar_loja("Outra loja S6")
    if config:
        salvar_config(nova, config, "teste")
    return nova


@pytest.fixture
def loja():
    nova = criar_loja("Loja S6")
    salvar_config(nova, LIGADO, "teste")
    return nova


# ---------------------------------------------------------------- um cenário por motivo
# Cada função monta o caso e devolve (loja, cliente, canal, hora).

def _c_elegivel(lj):
    _conversa(lj)
    return lj, L, "whatsapp", AGORA


def _c_elegivel_telegram(lj):
    _conversa(lj, canal="telegram")
    return lj, L, "telegram", AGORA


def _c_loja_inativa(lj):
    _conversa(lj)
    _sql("UPDATE lojas SET ativo = 0 WHERE id = ?", (lj,))
    lojas.limpar_cache()
    return lj, L, "whatsapp", AGORA


def _c_modulo_desligado(lj):
    nova = _loja_nova()
    _conversa(nova)
    return nova, L, "whatsapp", AGORA


def _c_limite_nao_definido(lj):
    nova = _loja_nova({"modulos.remarketing": True})
    _conversa(nova)
    return nova, L, "whatsapp", AGORA


def _c_canal_sem_envio(lj):
    _conversa(lj, canal="instagram")
    return lj, L, "instagram", AGORA


def _c_nao_contatar(lj):
    _conversa(lj)
    registrar_situacao(lj, L, "nao_contatar", motivo="teste")
    return lj, L, "whatsapp", AGORA


def _c_sem_interesse(lj):
    _conversa(lj)
    registrar_situacao(lj, L, "sem_interesse", motivo="teste")
    return lj, L, "whatsapp", AGORA


def _c_pediu_tempo(lj):
    _conversa(lj)
    registrar_situacao(lj, L, "pediu_tempo", dias=10, hoje=date(2026, 11, 1))
    return lj, L, "whatsapp", AGORA


def _c_ja_comprou(lj):
    _conversa(lj)
    _sql("INSERT INTO resultados (lead_id, loja_id, resultado) VALUES (?, ?, 'comprou')", (L, lj))
    return lj, L, "whatsapp", AGORA


def _c_teto_atingido(lj):
    _msg(lj, L, "cliente", 1000)
    for n, horas in ((1, 900), (2, 700), (3, 400)):
        _toque(lj, L, n, horas)
    return lj, L, "whatsapp", AGORA


def _c_bloqueado_toque(lj):
    _conversa(lj)
    _bloqueio(lj, L, "remarketing", 1)
    return lj, L, "whatsapp", AGORA


def _c_bloqueado_todos(lj):
    _conversa(lj)
    _bloqueio(lj, L, "todos", None)
    return lj, L, "whatsapp", AGORA


def _c_com_vendedor(lj):
    _conversa(lj)
    _sql("INSERT INTO handoffs (loja_id, lead_id, estado) VALUES (?, ?, 'humano_assumiu')", (lj, L))
    return lj, L, "whatsapp", AGORA


def _c_carencia(lj):
    _conversa(lj)
    assumido = para_banco(AGORA - timedelta(days=2))
    _sql("INSERT INTO handoffs (lead_id, loja_id, motivo, estado, vendedor, criado_em, "
         "assumido_em, encerrado_em) VALUES (?, ?, 'teste', 'encerrado', 'Ana', ?, ?, ?)",
         (L, lj, assumido, assumido, assumido))
    return lj, L, "whatsapp", AGORA


def _c_sem_conversa(lj):
    _msg(lj, L, "leo", 100)
    return lj, L, "whatsapp", AGORA


def _c_respondeu(lj):
    _msg(lj, L, "cliente", 100)
    _toque(lj, L, 1, 60)
    _msg(lj, L, "cliente", 50)
    return lj, L, "whatsapp", AGORA


def _c_aguardando_intervalo(lj):
    _conversa(lj, horas=47)
    return lj, L, "whatsapp", AGORA


def _c_limite_mensal(lj):
    salvar_config(lj, {"remarketing.limite_mensal": 1}, "teste")
    _toque(lj, "outro", 1, 1)
    _conversa(lj)
    return lj, L, "whatsapp", AGORA


def _c_fora_do_horario(lj):
    _conversa(lj)
    return lj, L, "whatsapp", NOITE


CENARIOS = {
    "elegivel": ("elegivel", _c_elegivel),
    "elegivel_telegram": ("elegivel", _c_elegivel_telegram),
    "loja_inativa": ("loja_inativa", _c_loja_inativa),
    "modulo_desligado": ("modulo_desligado", _c_modulo_desligado),
    "limite_nao_definido": ("limite_nao_definido", _c_limite_nao_definido),
    "canal_sem_envio": ("canal_sem_envio", _c_canal_sem_envio),
    "nao_contatar": ("nao_contatar", _c_nao_contatar),
    "sem_interesse": ("sem_interesse", _c_sem_interesse),
    "pediu_tempo": ("pediu_tempo", _c_pediu_tempo),
    "ja_comprou": ("ja_comprou", _c_ja_comprou),
    "teto_atingido": ("teto_atingido", _c_teto_atingido),
    "bloqueado_toque": ("bloqueado_pela_loja", _c_bloqueado_toque),
    "bloqueado_todos": ("bloqueado_pela_loja", _c_bloqueado_todos),
    "com_vendedor": ("com_vendedor", _c_com_vendedor),
    "carencia": ("carencia", _c_carencia),
    "sem_conversa": ("sem_conversa", _c_sem_conversa),
    "respondeu": ("respondeu", _c_respondeu),
    "aguardando_intervalo": ("aguardando_intervalo", _c_aguardando_intervalo),
    "limite_mensal": ("limite_mensal", _c_limite_mensal),
    "fora_do_horario": ("fora_do_horario", _c_fora_do_horario),
}


def test_os_cenarios_cobrem_todos_os_motivos():
    assert {motivo for motivo, _ in CENARIOS.values()} == set(el.ROTULOS)


@pytest.mark.parametrize("nome", sorted(CENARIOS))
def test_fotografia_e_avaliar_decidem_igual(loja, nome):
    motivo, montar = CENARIOS[nome]
    loja_id, lead, canal, agora = montar(loja)
    sozinho = el.avaliar(loja_id, lead, canal, agora)
    pela_foto = el.decidir(el.fotografia(loja_id, agora), lead, canal)
    assert sozinho.motivo == motivo
    assert pela_foto == sozinho          # todos os campos: toque, próximo, janela


def test_lista_inteira_bate_com_avaliar_um_por_um(loja):
    _conversa(loja, "A", horas=100)
    _conversa(loja, "B", horas=60)
    registrar_situacao(loja, "B", "nao_contatar", motivo="teste")
    _conversa(loja, "C", horas=70, canal="telegram")
    _conversa(loja, "D", horas=80)
    _sql("INSERT INTO handoffs (loja_id, lead_id, estado) VALUES (?, 'D', 'aguardando_humano')", (loja,))
    lista = el.candidatos(loja, AGORA)
    assert [d.lead_id for d in lista] == ["A", "D", "C", "B"]
    assert lista == [el.avaliar(loja, d.lead_id, d.canal, AGORA) for d in lista]


def test_fotografia_nao_mistura_lojas(loja):
    outra = _loja_nova(LIGADO)
    _conversa(loja)
    _conversa(outra)
    registrar_situacao(loja, L, "nao_contatar", motivo="teste")
    _conversa(outra, "so_na_outra")
    assert el.decidir(el.fotografia(outra, AGORA), L, "whatsapp").motivo == "elegivel"
    assert el.decidir(el.fotografia(loja, AGORA), L, "whatsapp").motivo == "nao_contatar"
    assert ("so_na_outra", "whatsapp") not in el.fotografia(loja, AGORA).conversas


# ---------------------------------------------------------------- reconferência do robô

def test_reconferencia_do_robo_usa_a_decisao_compartilhada(loja, monkeypatch):
    from app.jobs.remarketing import processar_lead
    _conversa(loja)
    chamadas = []
    original = el._decidir

    def espia(*args):
        chamadas.append(type(args[-1]).__name__)
        return original(*args)

    monkeypatch.setattr(el, "_decidir", espia)
    d = el.decidir(el.fotografia(loja, AGORA), L, "whatsapp")
    assert d.elegivel
    _bloqueio(loja, L, "todos", None)                        # marcou depois da fila
    estado = processar_lead(lojas.carregar_loja(loja), d, AGORA, real=False,
                            redator=None, enviador=None)
    assert estado == "pulado"
    assert chamadas == ["_FonteFoto", "_FonteBanco"]


def test_regra_existe_uma_vez_so():
    fonte = (RAIZ / "app" / "elegibilidade.py").read_text(encoding="utf-8")
    assert fonte.count("def _decidir(") == 1
    job = (RAIZ / "app" / "jobs" / "remarketing.py").read_text(encoding="utf-8")
    assert "d = avaliar(loja.id, decisao.lead_id, decisao.canal, agora)" in job


# ---------------------------------------------------------------- sem consulta por cliente

class _Contador:
    def __init__(self):
        self.n = 0

    def __call__(self, sql):
        if sql.lstrip().upper().startswith(("SELECT", "WITH")):
            self.n += 1


def _consultas(monkeypatch, funcao):
    contador = _Contador()
    original = sqlite3.connect

    def conectar_contando(*args, **kwargs):
        conexao = original(*args, **kwargs)
        conexao.set_trace_callback(contador)
        return conexao

    monkeypatch.setattr(sqlite3, "connect", conectar_contando)
    try:
        funcao()
    finally:
        monkeypatch.setattr(sqlite3, "connect", original)
    return contador.n


def _muitos(loja_id, quantos, inicio=0):
    linhas = []
    for i in range(inicio, inicio + quantos):
        lead = f"55819{i:08d}"
        quando = para_banco(AGORA - timedelta(hours=49 + i % 7))
        linhas += [(lead, loja_id, "whatsapp", "cliente", "oi", quando),
                   (lead, loja_id, "whatsapp", "leo", "oi", quando)]
    c = conectar()
    try:
        c.executemany("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
                      "VALUES (?, ?, ?, ?, ?, ?)", linhas)
        c.commit()
    finally:
        c.close()


def test_50_ou_500_clientes_fazem_as_mesmas_consultas(loja, monkeypatch):
    _muitos(loja, 50)
    el.candidatos(loja, AGORA)                                # aquece o cache da loja
    com_50 = _consultas(monkeypatch, lambda: el.candidatos(loja, AGORA))
    _muitos(loja, 450, inicio=50)
    com_500 = _consultas(monkeypatch, lambda: el.candidatos(loja, AGORA))
    assert len(el.candidatos(loja, AGORA)) == 500
    assert 0 < com_50 == com_500 <= 25


def test_tela_agora_com_500_clientes_tem_poucas_consultas(loja, monkeypatch):
    _muitos(loja, 500)
    ma.situacao_agora(loja, AGORA)
    assert _consultas(monkeypatch, lambda: ma.situacao_agora(loja, AGORA)) <= 60


# ---------------------------------------------------------------- telas e dados

def test_agora_mostra_motivo_e_nome_sem_numero_cru(loja):
    _conversa(loja, L)
    _conversa(loja, "5581999990002")
    registrar_situacao(loja, "5581999990002", "nao_contatar", motivo="teste")
    r = ma.situacao_agora(loja, AGORA)
    assert r["podem_agora"] == 1 and r["itens"][0]["pode"]
    assert {x["situacao"] for x in r["resumo"]} == {el.ROTULOS["elegivel"], el.ROTULOS["nao_contatar"]}
    assert all(i["lead_id"] not in i["cliente"] for i in r["itens"])


def _rm(loja_id, lead, estado, motivo, horas):
    quando = para_banco(AGORA - timedelta(hours=horas))
    _sql("INSERT INTO remarketing_envios (loja_id, lead_id, canal, toque, estado, motivo_bloqueio, "
         "enviado_em, criado_em) VALUES (?, ?, 'whatsapp', 1, ?, ?, ?, ?)",
         (loja_id, lead, estado, motivo, quando if estado == "enviado" else None, quando))


def test_no_mes_agrupa_por_tipo_resultado_e_motivo(loja):
    _rm(loja, "a", "simulado", None, 2)
    _rm(loja, "b", "simulado", None, 3)
    _rm(loja, "c", "bloqueado", "modelo_nao_aprovado", 4)
    _rm(loja, "d", "enviado", None, 5)
    _rm(loja, "e", "simulado", None, 24 * 40)                 # mês passado: não conta
    _rm(1, "f", "simulado", None, 2)                          # outra loja: não conta
    _sql("INSERT INTO reativacao (loja_id, contato_id, telefone, lote, meses_inativo, criado_por, "
         "estado, motivo, atualizado_em) VALUES (?, 1, '5581988887777', 'x', 6, 'S', 'cancelado', "
         "'nao_contatar', ?)", (loja, para_banco(AGORA - timedelta(hours=1))))
    r = ma.gravado_no_mes(loja, AGORA)
    linhas = {(l["tipo"], l["estado"], l["motivo"]): l["quantidade"] for l in r["linhas"]}
    assert linhas[("remarketing", "simulado", "")] == 2
    assert linhas[("remarketing", "bloqueado", "Modelo ainda não aprovado pela Meta nesta loja")] == 1
    assert linhas[("remarketing", "enviado", "")] == 1
    assert linhas[("reativacao", "cancelado", "Pediu para não ser procurado")] == 1
    assert r["totais"] == {"remarketing": 4, "pos_venda": 0, "reativacao": 1}


def test_no_mes_uma_consulta_por_tipo_nao_por_cliente(loja, monkeypatch):
    for i in range(5):
        _rm(loja, f"x{i}", "simulado", None, 2)
    ma.gravado_no_mes(loja, AGORA)
    poucos = _consultas(monkeypatch, lambda: ma.gravado_no_mes(loja, AGORA))
    for i in range(200):
        _rm(loja, f"y{i}", "bloqueado", "faltam_dados", 3)
    muitos = _consultas(monkeypatch, lambda: ma.gravado_no_mes(loja, AGORA))
    assert 3 <= poucos == muitos


def test_tela_abre_e_avisa_que_no_mes_e_so_o_gravado(loja):
    from streamlit.testing.v1 import AppTest
    _conversa(loja)
    at = AppTest.from_file(str(RAIZ / "paginas" / "operador" / "mensagens_automaticas.py"),
                           default_timeout=30)
    at.session_state["_papel"] = "operador"
    at.session_state["loja_id"] = loja
    at.run()
    assert not at.exception, at.exception
    assert any("ficou gravado" in c.value for c in at.caption)


def test_tela_e_dados_nao_falam_com_o_banco_nem_com_os_jobs():
    tela = (RAIZ / "paginas" / "operador" / "mensagens_automaticas.py").read_text(encoding="utf-8")
    assert "conectar" not in tela and "import banco" not in tela
    dados = (RAIZ / "app" / "mensagens_automaticas.py").read_text(encoding="utf-8")
    assert "streamlit" not in dados and "app.jobs" not in dados


def test_tela_antiga_continua_e_o_plano_manda_remover_no_s10():
    from paginas.menu import CLIENTE, arquivos
    assert "paginas/envios.py" in arquivos(CLIENTE)
    plano = (RAIZ / "docs" / "plano_mestre.md").read_text(encoding="utf-8")
    assert "Obrigatório no S10 (anotado no S6" in plano

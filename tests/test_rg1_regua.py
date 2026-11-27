"""
RG1 (Maratona 5): revisão da régua (remarketing e pós-venda). OFFLINE: redator falso, envio falso,
relógio fixo, duas lojas (ou dez, no teste da rodada longa).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from app import lojas, regua, vendas
from app.ator import como
from app.custos import Uso
from app.elegibilidade import ATRASO_MAXIMO, avaliar
from app.estado_loja import colocar_no_ar
from app.jobs import pos_venda as pv
from app.jobs import remarketing as rmk
from app.lojas import criar_loja
from app.relogio import para_banco
from app.resultado_envio import ResultadoEnvio
from banco import conectar

AGORA = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)      # terça, 09:00 em Recife


def _sql(sql, args=()):
    c = conectar()
    cur = c.execute(sql, args)
    novo = cur.lastrowid
    if novo is None and "RETURNING" in sql:
        novo = cur.fetchone()[0]
    c.commit()
    c.close()
    return novo


def _ler(sql, args=()):
    c = conectar()
    try:
        return [dict(l) for l in c.execute(sql, args).fetchall()]
    finally:
        c.close()


class Enviador:
    def __init__(self):
        self.textos, self.modelos = [], []

    async def texto(self, loja_id, canal, lead_id, texto):
        self.textos.append((loja_id, lead_id, texto))
        return ResultadoEnvio(ok=True, id_externo="x")

    async def modelo(self, loja_id, lead_id, modelo, valores):
        self.modelos.append((loja_id, lead_id, modelo.nome))
        return ResultadoEnvio(ok=True, id_externo="y")


def _redator(loja, lead_id, canal, toque, dados, historico):
    return "Oi! Conseguiu pensar no carro? Se quiser, separo um horário para você ver de perto.", Uso(100, 20, 0)


def _ligar(loja_id):
    lojas.salvar_config(loja_id, {"modulos.remarketing": True, "remarketing.limite_mensal": 500}, "teste")


def _conversa(loja_id, lead_id, ha=timedelta(hours=72), canal="telegram"):
    for direcao, desloca in (("cliente", 0), ("leo", 1)):
        _sql("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) VALUES (?, ?, ?, ?, 'x', ?)",
             (lead_id, loja_id, canal, direcao, para_banco(AGORA - ha + timedelta(minutes=desloca))))


# ================================================================== 1. relógio: trava e sinal no meio da rodada
class TravaComRelogio:
    """Trava falsa com um relógio falso: vence se ficar mais de TTL sem renovar."""

    def __init__(self, relogio, ttl=90):
        self.relogio, self.ttl = relogio, ttl
        self.vence_em = relogio["agora"] + ttl
        self.renovacoes, self.venceu = [], False
        self.cliente = object()

    def renovar(self):
        if self.relogio["agora"] > self.vence_em:
            self.venceu = True
        self.vence_em = self.relogio["agora"] + self.ttl
        self.renovacoes.append(self.relogio["agora"])
        return True


def test_rodada_longa_nao_deixa_a_trava_vencer_nem_o_sinal_parar(monkeypatch):
    """10 lojas, fila cheia (10 por loja), envio real (falso), 3 s de pausa por envio e um redator
    lento (2 s). Antes: ~500 s sem renovar a trava de 90 s. Agora: renova a cada cliente."""
    from app.jobs import batimento, runner
    relogio = {"agora": 0.0}
    monkeypatch.setattr(rmk.time, "sleep", lambda s: relogio.__setitem__("agora", relogio["agora"] + s))

    def redator_lento(*a):
        relogio["agora"] += 2.0
        return _redator(*a)
    sinais = []
    monkeypatch.setattr(batimento, "marcar_giro", lambda cliente, agora=None: sinais.append(relogio["agora"]) or True)
    ids = [1] + [criar_loja(f"Loja RG1 {i}") for i in range(9)]
    for loja_id in ids:
        colocar_no_ar(loja_id)
        _ligar(loja_id)
        for n in range(12):
            _conversa(loja_id, f"55819{loja_id:02d}{n:06d}")
    trava = TravaComRelogio(relogio)
    totais = rmk.rodar_remarketing(AGORA, envio_real=True, redator=redator_lento, enviador=Enviador(),
                                   lojas=ids, vivo=runner.manter_vivo(trava))
    assert totais["enviado"] == 100                                   # 10 lojas x 10 (limite da rodada)
    assert relogio["agora"] >= 100 * (rmk.PAUSA_ENTRE_ENVIOS_S + 2)   # ~500 s de rodada
    assert not trava.venceu
    maior_buraco = max(b - a for a, b in zip([0.0] + trava.renovacoes, trava.renovacoes))
    assert maior_buraco < trava.ttl
    assert len(sinais) == len(trava.renovacoes) >= 100


def test_tempo_de_uma_rodada_cheia_com_10_lojas_so_de_pausas(monkeypatch):
    """PASSO 0 (f): só as pausas de uma rodada cheia = 10 lojas x 10 envios x 3 s = 300 s."""
    pausas = []
    monkeypatch.setattr(rmk.time, "sleep", lambda s: pausas.append(s))
    ids = [1] + [criar_loja(f"Loja P {i}") for i in range(9)]
    for loja_id in ids:
        colocar_no_ar(loja_id)
        _ligar(loja_id)
        for n in range(10):
            _conversa(loja_id, f"55818{loja_id:02d}{n:06d}")
    rmk.rodar_remarketing(AGORA, envio_real=True, redator=_redator, enviador=Enviador(), lojas=ids)
    assert sum(pausas) == 300


def test_pos_venda_e_reativacao_tambem_avisam_que_estao_vivos():
    from app.jobs import reativacao
    chamadas = []
    lojas.salvar_config(1, {"modulos.pos_venda": True, "modulos.remarketing": True,
                            "remarketing.limite_mensal": 100}, "teste")
    pv.rodar_pos_venda(AGORA, lojas=[1], vivo=lambda: chamadas.append("pv"))
    reativacao.rodar_reativacao(AGORA, lojas=[1], vivo=lambda: chamadas.append("rv"))
    assert "pv" in chamadas                        # a cada loja (mesmo sem nada vencido)


def test_trava_perdida_no_meio_para_o_job():
    from app.jobs import runner

    class Perdida:
        cliente = object()

        def renovar(self):
            return False
    with pytest.raises(runner.TravaPerdida):
        runner.manter_vivo(Perdida())()


# ================================================================== 2. régua trocada, passo desligado, venda desfeita
def _carro(loja_id=1):
    return _sql("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) VALUES "
                "(?, 'Honda', 'Civic', 2019, 50000, 'Prata', 'Automático', 98000, 'disponivel') RETURNING id", (loja_id,))


def _venda(lead="5581955550001", loja_id=1, dia=date(2026, 11, 2)):
    _sql("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo) VALUES (?, ?, 'telegram', 'cliente', 'oi')",
         (lead, loja_id))
    _sql("INSERT INTO leads (lead_id, loja_id, nome) VALUES (?, ?, 'Ana Souza') ON CONFLICT DO NOTHING", (lead, loja_id))
    with como("Teste", "cliente", "painel", loja_id):
        return vendas.registrar_venda(loja_id, lead, _carro(loja_id), dia, "avista", vendedor="Vendedor Um",
                                      agora=datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc))


def _execucoes(lead="5581955550001"):
    return {l["passo"]: (l["estado"], l["motivo"]) for l in _ler(
        "SELECT p.nome AS passo, e.estado, e.motivo FROM regua_execucoes e JOIN regua_passos p ON p.id = e.passo_id "
        "WHERE e.lead_id = ?", (lead,))}


def _ligar_pos_venda(loja_id=1):
    lojas.salvar_config(loja_id, {"modulos.pos_venda": True}, "teste")


def test_regua_trocada_cancela_o_que_ja_estava_agendado():
    _ligar_pos_venda()
    _venda()
    assert _execucoes()["agradecimento"][0] == "agendado"
    regua.copiar_regua_modelo(1, "essencial")                         # a loja trocou de régua
    pv.rodar_pos_venda(datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc), lojas=[1], envio_real=True, enviador=Enviador())
    assert _execucoes()["agradecimento"] == ("cancelado", "regua_trocada")


def test_passo_desligado_cancela_na_hora_de_enviar():
    _ligar_pos_venda()
    _venda()
    atual = regua.regua_ativa(1)
    passo = next(p for p in atual["passos"] if p["nome"] == "agradecimento")
    regua.ligar_passo(1, passo["id"], False)
    pv.rodar_pos_venda(datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc), lojas=[1], envio_real=True, enviador=Enviador())
    assert _execucoes()["agradecimento"] == ("cancelado", "passo_desligado")


def test_venda_desfeita_cancela_todo_o_pos_venda_dela():
    _ligar_pos_venda()
    _venda()
    _sql("DELETE FROM vendas WHERE lead_id = '5581955550001'")       # a venda sumiu (o Léo não tem "desfazer")
    pv.rodar_pos_venda(datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc), lojas=[1], envio_real=True, enviador=Enviador())
    estados = _execucoes()
    assert estados and all(e == ("cancelado", "venda_desfeita") for nome, e in estados.items()
                           if nome not in ("troca_financiado",)), estados


def test_venda_desfeita_na_loja_a_nao_mexe_na_loja_b():
    b = criar_loja("Loja B Régua")
    colocar_no_ar(b)
    _ligar_pos_venda()
    _ligar_pos_venda(b)
    _venda("5581955550001", 1)
    _venda("5581955550002", b)
    _sql("DELETE FROM vendas WHERE loja_id = 1")
    pv.rodar_pos_venda(datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc), lojas=[1, b], envio_real=True, enviador=Enviador())
    assert _execucoes("5581955550002")["agradecimento"][0] in ("enviado", "simulado")


# ================================================================== 3. nome do perfil do WhatsApp
def _payload_wa(nome, numero="5581966660001", texto="oi"):
    return {"object": "whatsapp_business_account", "entry": [{"id": "x", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"phone_number_id": "phone-rg1"},
        "contacts": [{"profile": {"name": nome}, "wa_id": numero}],
        "messages": [{"from": numero, "id": f"wamid.{nome}{texto}", "timestamp": "1764000000", "type": "text",
                      "text": {"body": texto}}]}}]}]}


def test_canal_le_o_nome_do_perfil():
    from app.channels.whatsapp import CanalWhatsApp
    [m] = CanalWhatsApp().ler_webhook(_payload_wa("Maria Silva"))
    assert m.nome_perfil == "Maria Silva"


def test_nome_do_perfil_entra_so_se_a_ficha_esta_sem_nome():
    from app.nome_do_perfil import gravar_nome_do_perfil
    assert gravar_nome_do_perfil(1, "5581966660001", "Maria Silva")
    assert _ler("SELECT nome FROM leads WHERE lead_id = '5581966660001'") == [{"nome": "Maria Silva"}]
    _sql("UPDATE leads SET nome = 'Maria Aparecida' WHERE lead_id = '5581966660001'")   # o cliente disse
    assert not gravar_nome_do_perfil(1, "5581966660001", "Mari ✨")
    assert _ler("SELECT nome FROM leads WHERE lead_id = '5581966660001'") == [{"nome": "Maria Aparecida"}]


@pytest.mark.parametrize("perfil, esperado", [("Maria Silva", "Maria Silva"), ("~ João 🚗", "João"),
                                               ("🔥🔥", ""), ("81999998888", ""), ("Loja do Zé - 81999998888", "")])
def test_nome_do_perfil_limpo(perfil, esperado):
    from app.nome_do_perfil import limpar_nome_do_perfil
    assert limpar_nome_do_perfil(perfil) == esperado


def test_webhook_grava_o_nome_do_perfil_na_loja_certa(monkeypatch):
    import hashlib
    import hmac
    from fastapi.testclient import TestClient
    import app.api.webhook as wa
    from app import canais
    b = criar_loja("Loja B Perfil")
    canais.cadastrar_canal(1, "whatsapp", "phone-rg1", "WA_TOKEN_RG1")
    monkeypatch.setattr(wa, "WHATSAPP_APP_SECRET", "segredo-rg1")

    async def nada(*a, **k):
        return None
    monkeypatch.setattr(wa, "processar_mensagem", nada)
    monkeypatch.setattr(wa, "ja_processada", lambda *a: _falso())
    corpo = json.dumps(_payload_wa("Maria Silva")).encode()
    assinatura = "sha256=" + hmac.new(b"segredo-rg1", corpo, hashlib.sha256).hexdigest()
    assert TestClient(wa.app).post("/webhook", content=corpo, headers={"X-Hub-Signature-256": assinatura}).status_code == 200
    assert _ler("SELECT loja_id, nome FROM leads WHERE lead_id = '5581966660001'") == [{"loja_id": 1, "nome": "Maria Silva"}]
    assert b


async def _falso():
    return False


# ================================================================== 4. retomada atrasada
def test_toque_atrasado_mais_de_3_dias_nao_sai():
    _ligar(1)
    colocar_no_ar(1)
    _conversa(1, "5581977770001", ha=timedelta(hours=48) + ATRASO_MAXIMO + timedelta(days=1))
    d = avaliar(1, "5581977770001", "telegram", AGORA)
    assert (d.elegivel, d.motivo) == (False, "atrasado")
    _conversa(1, "5581977770002", ha=timedelta(hours=48) + timedelta(days=2))          # 2 dias atrasado: ainda sai
    assert avaliar(1, "5581977770002", "telegram", AGORA).elegivel


def test_esperar_a_carencia_nao_conta_como_atraso():
    _ligar(1)
    colocar_no_ar(1)
    _conversa(1, "5581977770003", ha=timedelta(days=10))
    fim = para_banco(AGORA - timedelta(days=8))
    _sql("INSERT INTO handoffs (lead_id, loja_id, motivo, estado, vendedor, criado_em, assumido_em, encerrado_em) "
         "VALUES ('5581977770003', 1, 'x', 'encerrado', 'Ana', ?, ?, ?)", (fim, fim, fim))
    # carência de 7 dias acabou ontem: o toque sai hoje (não é atraso)
    assert avaliar(1, "5581977770003", "telegram", AGORA).elegivel


def test_cliente_que_volta_a_falar_recomeca_a_conta():
    _ligar(1)
    colocar_no_ar(1)
    _conversa(1, "5581977770004", ha=timedelta(days=20))
    assert avaliar(1, "5581977770004", "telegram", AGORA).motivo == "atrasado"
    _conversa(1, "5581977770004", ha=timedelta(hours=49))
    assert avaliar(1, "5581977770004", "telegram", AGORA).elegivel


# ================================================================== 5. trava por cliente no remarketing
def test_cliente_sendo_atendido_fica_para_a_proxima_rodada():
    from app.redis_lock import adquirir_lock_sincrono, liberar_lock_sincrono
    _ligar(1)
    colocar_no_ar(1)
    _conversa(1, "5581988880001")
    _conversa(1, "5581988880002")
    token = adquirir_lock_sincrono("5581988880001", loja_id=1)          # o atendimento pegou este cliente
    assert token
    try:
        env = Enviador()
        totais = rmk.rodar_remarketing(AGORA, envio_real=True, redator=_redator, enviador=env, lojas=[1],
                                       pausa_s=0, max_por_loja=1)
        assert [l for _, l, _ in env.textos] == ["5581988880002"]      # pulou o ocupado, sem gastar a vaga
        assert totais["pulado"] >= 1 and totais["erro"] == 0
    finally:
        liberar_lock_sincrono("5581988880001", token, loja_id=1)
    env = Enviador()
    rmk.rodar_remarketing(AGORA, envio_real=True, redator=_redator, enviador=env, lojas=[1], pausa_s=0)
    assert [l for _, l, _ in env.textos] == ["5581988880001"]          # na rodada seguinte, sai


def test_a_trava_e_a_mesma_do_atendimento():
    import asyncio
    from app.redis_lock import adquirir_lock, adquirir_lock_sincrono, liberar_lock
    token = adquirir_lock_sincrono("5581988880009", loja_id=1)
    try:
        assert asyncio.run(adquirir_lock("5581988880009", loja_id=1)) is None
    finally:
        from app.redis_lock import liberar_lock_sincrono
        liberar_lock_sincrono("5581988880009", token, loja_id=1)
    assert adquirir_lock_sincrono("5581988880009", loja_id=2)            # outra loja: outra trava


# ================================================================== 6. régua de veículos e o aviso ao vendedor da venda
def test_regua_de_veiculos_nova():
    modelos = regua.modelos_de_regua(lojas.carregar_loja(1))
    proxima = {p["nome"]: p for p in modelos["proxima"]["passos"]}
    assert proxima["avaliacao"]["deslocamento_dias"] == 15
    assert (proxima["conferir_transferencia"]["deslocamento_dias"], proxima["conferir_transferencia"]["acao"],
            proxima["conferir_transferencia"]["modelo"]) == (20, "avisar_vendedor", None)
    essencial = {p["nome"]: p for p in modelos["essencial"]["passos"]}
    assert essencial["avaliacao"]["deslocamento_dias"] == 15


def test_conferir_transferencia_avisa_o_vendedor_da_venda_e_nada_vai_ao_cliente(monkeypatch):
    from app import avisos, usuarios
    _ligar_pos_venda()
    for nome, papel, tg in (("Vendedor Um", "vendedor", "tg-um"), ("Vendedor Dois", "vendedor", "tg-dois"),
                            ("Gerente", "gestor", "tg-gestor")):
        _sql("INSERT INTO usuarios (loja_id, nome, papel, contato_telegram, ativo) VALUES (1, ?, ?, ?, 1)", (nome, papel, tg))
    enviados = []
    monkeypatch.setattr(avisos, "avisar_uma_vez", lambda loja_id, tipo, ref, chats, texto, *a, **k:
                        enviados.append((list(chats), texto)) or {"concluido": True})
    _venda()
    env = Enviador()
    pv.rodar_pos_venda(datetime(2026, 11, 23, 13, 0, tzinfo=timezone.utc), lojas=[1], envio_real=True, enviador=env)
    avisos_da_transferencia = [(c, t) for c, t in enviados if "conferir transferencia" in t]
    assert avisos_da_transferencia and avisos_da_transferencia[0][0] == ["tg-um"]
    assert "nada foi enviado ao cliente" in avisos_da_transferencia[0][1]
    assert _execucoes()["conferir_transferencia"][0] == "avisado"
    assert not any("transfer" in str(m) for m in env.modelos + env.textos)
    assert usuarios


def test_sem_vendedor_na_venda_o_aviso_vai_ao_gestor():
    _sql("INSERT INTO usuarios (loja_id, nome, papel, contato_telegram, ativo) VALUES (1, 'Gerente', 'gestor', 'tg-gestor', 1)")
    _sql("INSERT INTO usuarios (loja_id, nome, papel, contato_telegram, ativo) VALUES (1, 'Outro', 'vendedor', 'tg-outro', 1)")
    loja = lojas.carregar_loja(1)
    assert pv.destinos_do_aviso(loja, {"evento_tipo": "venda", "evento_id": 999999}) == ["tg-gestor"]


# ================================================================== 7. endereço da loja
CADASTRO = "Av. Domingos Ferreira, 1000, Boa Viagem"
RODADA_2 = ("Recebi as informações do seu Corolla. Para a avaliação, precisamos analisar o veículo presencialmente "
            "aqui na loja, na Av. Domingos Ferreira, 1000, Boa Vista.")      # rodada_2026-11-27_162835


def test_endereco_errado_da_rodada_2_vira_o_do_cadastro():
    from app.guarda_endereco import corrigir_endereco
    novo, trocou = corrigir_endereco(RODADA_2, CADASTRO, "Recife")
    assert trocou and novo.endswith("na Av. Domingos Ferreira, 1000, Boa Viagem.")
    assert "Boa Vista" not in novo


@pytest.mark.parametrize("certo", [
    "Você teria disponibilidade para passar aqui na Av. Domingos Ferreira, 1000, em Boa Viagem? Estamos abertos hoje até as 18:00.",
    "A loja fica na Av. Domingos Ferreira, 1000, Boa Viagem, Recife.",
    "Estamos na Av. Domingos Ferreira, 1000, Boa Viagem. Quer agendar?",
    "Fica na Av. Domingos Ferreira, 1000.",
    "Sem endereço aqui; Boa Vista é outro bairro.",
])
def test_endereco_certo_nao_muda_nada(certo):
    from app.guarda_endereco import corrigir_endereco
    assert corrigir_endereco(certo, CADASTRO, "Recife") == (certo, False)


@pytest.mark.parametrize("errado", ["Fica na Avenida Domingos Ferreira, 1200, Boa Viagem.",
                                    "Fica na Av. Domingos Ferreira, 1000 - Pina, Recife."])
def test_numero_ou_bairro_errado_vira_o_do_cadastro(errado):
    from app.guarda_endereco import corrigir_endereco
    novo, trocou = corrigir_endereco(errado, CADASTRO, "Recife")
    assert trocou and "Av. Domingos Ferreira, 1000, Boa Viagem" in novo


def test_guarda_roda_no_turno(monkeypatch):
    """No turno de verdade (IA falsa): a resposta com o bairro errado sai com o do cadastro."""
    import asyncio
    from langchain_core.messages import AIMessage
    from app.core import agent, turno
    lojas.salvar_config(1, {"endereco": CADASTRO, "cidade": "Recife"}, "teste")

    class LLM:
        def invoke(self, mensagens):
            return AIMessage(content="A loja fica na Av. Domingos Ferreira, 1000, Boa Vista. Te espero!")
    monkeypatch.setattr(agent, "llm", LLM())

    async def vez(*a):
        return a[2], "t"

    async def solta(*a, **k):
        return True
    monkeypatch.setattr("app.core.turno.aguardar_vez", vez)
    monkeypatch.setattr("app.redis_lock.liberar_lock", solta)
    r = asyncio.run(turno.executar_turno(1, "simulador", "rg1-endereco", "onde fica a loja?"))
    assert "Boa Viagem" in r.texto and "Boa Vista" not in r.texto

"""
Testes da Etapa 2, Bloco 5A: régua de pós-venda.
Régua-modelo de veículos (6 passos), botão "Vendido" e job do pós-venda.
Tudo offline: banco temporário, enviador falso, sem IA.
"""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from banco import conectar
from app import lojas, regua, vendas
from app.elegibilidade import avaliar
from app.interesse import registrar_situacao
from app.jobs import pos_venda as pv
from app.relogio import para_banco
from app.resultado_envio import ResultadoEnvio
from app.templates import registrar_status

AGORA = datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc)   # terça, 10:00 em Recife
ONTEM = date(2026, 11, 2)


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


def _ligar(loja_id=1, **extra):
    lojas.salvar_config(loja_id, {"modulos.pos_venda": True, **extra}, "teste")


def _carro(loja_id=1):
    c = conectar()
    cur = c.execute(
        "INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) "
        "VALUES (?, 'Honda', 'Civic', 2019, 40000, 'Prata', 'Automático', 98000, 'disponivel')",
        (loja_id,))
    c.commit()
    novo = cur.lastrowid
    c.close()
    return novo


def _lead(lead_id, nome, loja_id=1):
    c = conectar()
    c.execute("INSERT INTO leads (lead_id, loja_id, nome) VALUES (?, ?, ?)", (lead_id, loja_id, nome))
    c.commit()
    c.close()


def _mensagem(lead_id, canal, quando, loja_id=1):
    c = conectar()
    c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
              "VALUES (?, ?, ?, 'cliente', 'oi', ?)", (lead_id, loja_id, canal, para_banco(quando)))
    c.commit()
    c.close()


def _vender(lead_id="111", forma="avista", meses=None, dia=ONTEM, loja_id=1):
    return vendas.registrar_venda(loja_id, lead_id, _carro(loja_id), dia, forma,
                                  meses_financiamento=meses, vendedor="Carlos", agora=AGORA)


def _execucoes(lead_id="111", loja_id=1) -> dict:
    return {e["passo_nome"]: e for e in regua.execucoes_do_lead(loja_id, lead_id)}


def _agendados(lead_id="111", loja_id=1) -> set:
    return {n for n, e in _execucoes(lead_id, loja_id).items() if e["estado"] == "agendado"}


def _rodar(agora=AGORA, **kw):
    kw.setdefault("enviador", EnviadorFalso())
    kw.setdefault("envio_real", True)
    return pv.rodar_pos_venda(agora, **kw)


def _cliente_telegram(lead_id="111", nome="Ana Souza"):
    if nome:
        _lead(lead_id, nome)
    _mensagem(lead_id, "telegram", AGORA - timedelta(days=2))


def _handoff(motivo, lead_id="111"):
    c = conectar()
    c.execute("INSERT INTO handoffs (loja_id, lead_id, motivo, resumo, estado) "
              "VALUES (1, ?, ?, '', 'aguardando_humano')", (lead_id, motivo))
    c.commit()
    c.close()


# ---------------------------------------------------------------- régua-modelo
def test_regua_proxima_tem_seis_passos_com_prazos():
    proxima = regua.modelos_de_regua(lojas.carregar_loja(1))["proxima"]
    nomes = [p["nome"] for p in proxima["passos"]]
    assert nomes == ["agradecimento", "acompanhamento", "avaliacao", "revisao",
                     "troca_avista", "troca_financiado"]
    assert [p["deslocamento_dias"] for p in proxima["passos"]] == [1, 7, 30, 183, 365, -365]


def test_copia_usa_os_prazos_da_configuracao_da_loja():
    lojas.salvar_config(1, {"pos_venda.revisao_meses": 12}, "teste")
    passos = {p["nome"]: p for p in regua.garantir_regua(1)["passos"]}
    assert passos["revisao"]["deslocamento_dias"] == 365


def test_garantir_regua_copia_uma_vez_so():
    a = regua.garantir_regua(1)
    b = regua.garantir_regua(1)
    assert a["id"] == b["id"] and a["modelo_origem"] == "proxima"


def _segmento_falso(tmp_path, monkeypatch, passo):
    from app import segmentos
    pasta = tmp_path / "teste"
    pasta.mkdir()
    (pasta / "prompt.md").write_text("Teste.", encoding="utf-8")
    (pasta / "modelos.json").write_text(json.dumps({"modelos": [
        {"nome": "oi", "categoria": "utilidade", "texto": "Oi, {nome}! Tudo bem?"}]}), encoding="utf-8")
    (pasta / "reguas.json").write_text(json.dumps({
        "gatilhos": ["venda"], "reguas": {"x": {"passos": [passo]}}}), encoding="utf-8")
    monkeypatch.setattr(segmentos, "PASTA_SEGMENTOS", tmp_path)

    class LojaFalsa:
        segmento = "teste"

        def get(self, chave, padrao=None):
            return padrao
    return LojaFalsa()


def test_gatilho_fora_do_vocabulario_e_recusado(tmp_path, monkeypatch):
    loja = _segmento_falso(tmp_path, monkeypatch,
                           {"nome": "a", "gatilho": "aniversario", "dias": 1, "modelo": "oi"})
    with pytest.raises(regua.ReguaInvalida):
        regua.modelos_de_regua(loja)


def test_modelo_inexistente_e_recusado(tmp_path, monkeypatch):
    loja = _segmento_falso(tmp_path, monkeypatch,
                           {"nome": "a", "gatilho": "venda", "dias": 1, "modelo": "nao_existe"})
    with pytest.raises(regua.ReguaInvalida):
        regua.modelos_de_regua(loja)


def test_somar_meses_respeita_o_fim_do_mes():
    assert vendas.somar_meses(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert vendas.somar_meses(date(2026, 11, 2), 48) == date(2030, 11, 2)


# ---------------------------------------------------------------- agenda da venda
def test_venda_a_vista_agenda_passos_1_a_5():
    _ligar()
    _vender()
    assert _agendados() == {"agradecimento", "acompanhamento", "avaliacao", "revisao", "troca_avista"}
    assert "troca_financiado" not in _execucoes()


def test_venda_financiada_com_prazo_agenda_1_a_4_e_6():
    _ligar()
    _vender(forma="financiado", meses=48)
    assert _agendados() == {"agradecimento", "acompanhamento", "avaliacao", "revisao", "troca_financiado"}
    assert "troca_avista" not in _execucoes()
    # fim em 02/11/2030, menos 12 meses = 02/11/2029, 10:00 em Recife
    assert _execucoes()["troca_financiado"]["agendado_para"] == "2029-11-02 13:00:00"


def test_venda_financiada_sem_prazo_registra_o_motivo():
    _ligar()
    _vender(forma="financiado", meses=None)
    assert _agendados() == {"agradecimento", "acompanhamento", "avaliacao", "revisao"}
    e = _execucoes()["troca_financiado"]
    assert (e["estado"], e["motivo"]) == ("cancelado", "sem_data_fim_financiamento")


def test_financiamento_curto_nao_agenda_a_troca():
    _ligar()
    _vender(forma="financiado", meses=12)
    e = _execucoes()["troca_financiado"]
    assert (e["estado"], e["motivo"]) == ("cancelado", "antes_do_evento")


def test_venda_antiga_nao_manda_passo_que_ja_passou():
    _ligar()
    _vender(dia=date(2026, 9, 4))
    ex = _execucoes()
    for nome in ("agradecimento", "acompanhamento", "avaliacao"):
        assert (ex[nome]["estado"], ex[nome]["motivo"]) == ("cancelado", "data_passou")
    assert ex["revisao"]["estado"] == "agendado"


def test_modulo_desligado_nao_agenda():
    r = _vender()
    assert r["pos_venda_ligado"] is False and r["pos_venda"] == []
    assert _execucoes() == {}


# ---------------------------------------------------------------- botão Vendido
def test_venda_tira_o_lead_do_remarketing():
    lojas.salvar_config(1, {"modulos.remarketing": True, "remarketing.limite_mensal": 30}, "teste")
    _mensagem("111", "telegram", AGORA - timedelta(days=3))
    _vender()
    assert avaliar(1, "111", "telegram", AGORA).motivo == "ja_comprou"


def test_venda_marca_carro_vendido_e_resultado_comprou():
    r = _vender()
    c = conectar()
    status = c.execute("SELECT e.status FROM vendas v JOIN estoque e ON e.id = v.veiculo_id "
                       "WHERE v.id = ?", (r["venda_id"],)).fetchone()["status"]
    resultado = c.execute("SELECT resultado FROM resultados WHERE loja_id = 1 AND lead_id = '111'").fetchone()
    c.close()
    assert status == "vendido" and resultado["resultado"] == "comprou"
    assert r["carro"] == "Honda Civic 2019"


def test_carro_de_outra_loja_e_recusado():
    loja2 = lojas.criar_loja("Loja 2")
    with pytest.raises(vendas.VendaInvalida):
        vendas.registrar_venda(1, "111", _carro(loja2), ONTEM, "avista", agora=AGORA)


def test_venda_repetida_e_recusada():
    carro = _carro()
    vendas.registrar_venda(1, "111", carro, ONTEM, "avista", agora=AGORA)
    with pytest.raises(vendas.VendaInvalida):
        vendas.registrar_venda(1, "111", carro, ONTEM, "avista", agora=AGORA)

def test_data_no_futuro_e_recusada():
    with pytest.raises(vendas.VendaInvalida):
        _vender(dia=date(2026, 12, 1))


# ---------------------------------------------------------------- job
def test_envia_o_agradecimento_no_telegram():
    _ligar()
    _cliente_telegram()
    _vender()
    env = EnviadorFalso()
    r = _rodar(enviador=env)
    assert r["enviado"] == 1
    assert "Ana" in env.textos[0] and "Honda Civic 2019" in env.textos[0]
    assert _execucoes()["agradecimento"]["estado"] == "enviado"
    c = conectar()
    autor = c.execute("SELECT autor FROM mensagens WHERE loja_id = 1 AND direcao = 'leo'").fetchone()
    c.close()
    assert autor["autor"] == "pos_venda"


def test_simulacao_nao_grava_envio():
    _ligar()
    _cliente_telegram()
    _vender()
    env = EnviadorFalso()
    r = _rodar(enviador=env, envio_real=False)
    assert r["simulado"] == 1 and env.textos == []
    assert _execucoes()["agradecimento"]["estado"] == "agendado"


def test_sem_nome_no_telegram_cumprimenta_sem_nome():
    _ligar()
    _cliente_telegram(nome=None)
    _vender()
    env = EnviadorFalso()
    _rodar(enviador=env)
    assert env.textos[0].startswith("Oi! Aqui é o Léo")


def test_problema_de_pos_venda_cancela_os_passos_futuros():
    _ligar()
    _cliente_telegram()
    _vender()
    _handoff("PÓS-VENDA: barulho no motor")
    _rodar()
    assert _agendados() == set()
    assert {e["motivo"] for e in _execucoes().values()} == {"problema"}


def test_outro_handoff_so_adia():
    _ligar()
    _cliente_telegram()
    _vender()
    _handoff("cliente pediu desconto")
    r = _rodar()
    assert r["adiado"] == 1
    assert _execucoes()["agradecimento"]["estado"] == "agendado"


def test_nao_contatar_cancela():
    _ligar()
    _cliente_telegram()
    _vender()
    registrar_situacao(1, "111", "nao_contatar", "pediu")
    _rodar()
    e = _execucoes()["agradecimento"]
    assert (e["estado"], e["motivo"]) == ("cancelado", "nao_contatar")


def test_pediu_tempo_reagenda():
    _ligar()
    _cliente_telegram()
    _vender()
    registrar_situacao(1, "111", "pediu_tempo", dias=10, hoje=date(2026, 11, 3))
    r = _rodar()
    assert r["adiado"] == 1
    e = _execucoes()["agradecimento"]
    assert e["estado"] == "agendado" and e["agendado_para"] == "2026-11-13 13:00:00"


def _cliente_whatsapp():
    _lead("5581999990000", "Ana Souza")
    _mensagem("5581999990000", "whatsapp", AGORA - timedelta(days=2))


def test_whatsapp_janela_fechada_sem_aprovacao_bloqueia():
    _ligar()
    _cliente_whatsapp()
    _vender(lead_id="5581999990000")
    env = EnviadorFalso()
    _rodar(enviador=env)
    e = _execucoes("5581999990000")["agradecimento"]
    assert (e["estado"], e["motivo"]) == ("bloqueado", "modelo_nao_aprovado")
    assert env.modelos == []


def test_whatsapp_janela_fechada_com_aprovacao_manda_o_modelo():
    _ligar()
    _cliente_whatsapp()
    registrar_status(1, "pos_venda_agradecimento", "aprovado")
    _vender(lead_id="5581999990000")
    env = EnviadorFalso()
    _rodar(enviador=env)
    assert env.modelos == ["pos_venda_agradecimento"]
    assert _execucoes("5581999990000")["agradecimento"]["estado"] == "enviado"


def test_falha_no_envio_reagenda_em_6_horas():
    _ligar()
    _cliente_telegram()
    _vender()
    _rodar(enviador=EnviadorFalso(ok=False))
    e = _execucoes()["agradecimento"]
    assert (e["estado"], e["motivo"]) == ("agendado", "erro_no_envio")
    assert e["agendado_para"] == para_banco(AGORA + timedelta(hours=6))
    assert json.loads(e["contexto"])["tentativas"] == 1


def test_venda_de_uma_loja_nao_aparece_na_outra():
    loja2 = lojas.criar_loja("Loja 2")
    _ligar(loja2)
    _vender(loja_id=loja2)
    assert regua.execucoes_do_lead(1, "111") == []
    assert len(regua.execucoes_do_lead(loja2, "111")) == 5


def test_reconhece_motivo_de_pos_venda():
    assert pv.e_pos_venda("PÓS-VENDA: documento atrasado")
    assert pv.e_pos_venda("pos-venda: barulho")
    assert not pv.e_pos_venda("cliente pediu desconto")


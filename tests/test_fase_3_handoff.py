"""
Testes da FASE 3 (handoff + painel): rodam no `pytest` normal, offline.
Usam REDIS FALSO, LLM/grafo FALSO e um BANCO SQLITE TEMPORÁRIO por teste.

Grupos:
  A. Máquina de estados do handoff (app/handoff.py + tools/acionar_handoff.py)
  B. Trava para dois vendedores (HOJE FALHA: é um bug real, ver abaixo)
  C. Silêncio do Léo quando o humano assume (WhatsApp e Telegram)
  D. Persistência de mensagens (app/mensagens.py) e guarda gravando no banco
  E. Resultado do lead (app/resultados.py)
  F. CRUD de estoque (app/estoque.py) e baixa que tira o carro da oferta

Dependência de teste:  pip install "fakeredis[lua]"
"""

import asyncio
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field

import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import banco
from banco import criar_tabelas, popular_estoque_exemplo, conectar


# ======================================================================
# INFRAESTRUTURA
# ======================================================================

def importar_modulo(nome):
    """Importa webhook/telegram só quando precisa (importar cria o cliente do
    Gemini). Carrega o .env antes e usa chave falsa só se não houver nenhuma."""
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.setdefault("GOOGLE_API_KEY", "chave-falsa-so-para-importar")
    import importlib
    return importlib.import_module(nome)


@pytest.fixture
def banco_temporario(monkeypatch):
    """Banco SQLite descartável, com todas as tabelas."""
    fd, caminho = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(banco, "CAMINHO_BANCO", caminho)
    criar_tabelas()
    yield caminho
    if os.path.exists(caminho):
        os.remove(caminho)


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


class GrafoFalso:
    """Substitui o Léo. Registra cada chamada e devolve a resposta roteirizada."""

    def __init__(self, resposta="Claro! Já te ajudo."):
        self.resposta = resposta
        self.entradas = []

    def invoke(self, entrada, config=None):
        self.entradas.append(entrada["messages"][0].content)
        return {"messages": [HumanMessage(content=entrada["messages"][0].content),
                             AIMessage(content=self.resposta)]}


@dataclass
class Saidas:
    respostas: list = field(default_factory=list)


@pytest.fixture
def whatsapp(monkeypatch, redis_falso, banco_temporario):
    """Webhook do WhatsApp com envio capturado e grafo falso trocável."""
    wh = importar_modulo("app.api.webhook")
    saidas = Saidas()

    async def resposta(numero, texto, atraso=0):
        saidas.respostas.append((numero, texto))

    async def foto(numero, url):
        return True

    monkeypatch.setattr(wh, "enviar_resposta_humanizada", resposta)
    monkeypatch.setattr(wh, "enviar_foto_whatsapp", foto)
    grafo = GrafoFalso()
    monkeypatch.setattr(wh, "agente_grafo", grafo)
    return wh, grafo, saidas


def abrir_handoff(lead_id="5581", motivo="cliente pediu desconto", resumo="quer o Civic"):
    """Cria um handoff do jeito que o Léo cria: pela tool."""
    from tools import acionar_handoff
    return acionar_handoff.func(motivo=motivo, resumo=resumo, lead_id=lead_id)


def linhas_handoff(lead_id="5581"):
    con = conectar()
    linhas = con.execute("SELECT * FROM handoffs WHERE lead_id = ? ORDER BY id", (lead_id,)).fetchall()
    con.close()
    return [dict(l) for l in linhas]


# ======================================================================
# A) MÁQUINA DE ESTADOS DO HANDOFF
# ======================================================================

def test_lead_sem_handoff_esta_ativo(banco_temporario):
    from app.handoff import estado_do_handoff
    assert estado_do_handoff("5581") == "ativo"


def test_acionar_handoff_coloca_o_lead_na_fila(banco_temporario):
    from app.handoff import estado_do_handoff, listar_handoffs
    abrir_handoff("5581")
    assert estado_do_handoff("5581") == "aguardando_humano"
    fila = listar_handoffs()
    assert [h["lead_id"] for h in fila] == ["5581"]
    assert fila[0]["motivo"] == "cliente pediu desconto"


def test_acionar_duas_vezes_nao_duplica_a_fila(banco_temporario):
    """O upsert por lead: o 2º acionamento atualiza motivo/resumo, não cria linha."""
    abrir_handoff("5581", motivo="desconto", resumo="r1")
    abrir_handoff("5581", motivo="crédito", resumo="r2")
    linhas = linhas_handoff("5581")
    assert len(linhas) == 1
    assert linhas[0]["motivo"] == "crédito" and linhas[0]["resumo"] == "r2"


def test_assumir_grava_vendedor_e_carimbo(banco_temporario):
    from app.handoff import assumir_handoff, estado_do_handoff
    abrir_handoff("5581")
    msg = assumir_handoff("5581", "Ana")
    assert "Ana" in msg
    assert estado_do_handoff("5581") == "humano_assumiu"
    linha = linhas_handoff("5581")[0]
    assert linha["vendedor"] == "Ana"
    assert linha["assumido_em"] is not None


def test_devolver_ao_agente_reativa_o_leo(banco_temporario):
    from app.handoff import assumir_handoff, devolver_ao_agente, estado_do_handoff
    abrir_handoff("5581")
    assumir_handoff("5581", "Ana")
    devolver_ao_agente("5581")
    assert estado_do_handoff("5581") == "ativo"
    assert linhas_handoff("5581")[0]["encerrado_em"] is not None


def test_encerrar_handoff_tira_da_fila(banco_temporario):
    from app.handoff import encerrar_handoff, listar_handoffs, estado_do_handoff
    abrir_handoff("5581")
    encerrar_handoff("5581")
    assert listar_handoffs() == []
    assert estado_do_handoff("5581") == "ativo"


def test_acoes_sem_handoff_aberto_nao_quebram(banco_temporario):
    from app.handoff import assumir_handoff, devolver_ao_agente, encerrar_handoff
    assert "Nenhum handoff" in assumir_handoff("0000", "Ana")
    assert "Nenhum handoff" in devolver_ao_agente("0000")
    assert "Nenhum handoff" in encerrar_handoff("0000")
    assert linhas_handoff("0000") == []


def test_novo_handoff_depois_de_devolver_cria_nova_linha(banco_temporario):
    """Depois de devolvido, um novo pedido de humano abre OUTRO handoff
    (o histórico do anterior fica preservado)."""
    from app.handoff import assumir_handoff, devolver_ao_agente, estado_do_handoff
    abrir_handoff("5581", motivo="primeiro")
    assumir_handoff("5581", "Ana")
    devolver_ao_agente("5581")
    abrir_handoff("5581", motivo="segundo")
    assert estado_do_handoff("5581") == "aguardando_humano"
    assert [l["motivo"] for l in linhas_handoff("5581")] == ["primeiro", "segundo"]


def test_fila_mostra_o_mais_antigo_primeiro_e_so_abertos(banco_temporario):
    from app.handoff import listar_handoffs, encerrar_handoff
    for lead in ("1", "2", "3"):
        abrir_handoff(lead)
    con = conectar()
    for lead, hora in (("1", "2026-01-01 10:10:00"), ("2", "2026-01-01 10:00:00"),
                       ("3", "2026-01-01 10:05:00")):
        con.execute("UPDATE handoffs SET criado_em = ? WHERE lead_id = ?", (hora, lead))
    con.commit()
    con.close()
    assert [h["lead_id"] for h in listar_handoffs()] == ["2", "3", "1"]
    encerrar_handoff("3")
    assert [h["lead_id"] for h in listar_handoffs()] == ["2", "1"]
    assert len(listar_handoffs(apenas_abertos=False)) == 3


def test_handoffs_de_lojas_diferentes_nao_se_misturam(banco_temporario):
    """Multi-loja: o handoff da loja 2 não aparece nem silencia a loja 1."""
    from app.handoff import estado_do_handoff, listar_handoffs
    con = conectar()
    con.execute("INSERT INTO handoffs (lead_id, loja_id, motivo, resumo, estado) "
                "VALUES ('5581', 2, 'x', 'y', 'humano_assumiu')")
    con.commit()
    con.close()
    assert estado_do_handoff("5581", loja_id=1) == "ativo"
    assert estado_do_handoff("5581", loja_id=2) == "humano_assumiu"
    assert listar_handoffs(loja_id=1) == []
    assert len(listar_handoffs(loja_id=2)) == 1


# ======================================================================
# B) TRAVA PARA DOIS VENDEDORES  (BUG ATUAL: este teste FALHA hoje)
# ======================================================================

def test_segundo_vendedor_nao_sobrescreve_o_primeiro(banco_temporario):
    """Ana e Beto clicam em 'Assumir' quase juntos. Hoje o UPDATE não confere
    o estado e o Beto SOBRESCREVE a Ana sem aviso. Correção: o UPDATE precisa
    de `AND estado = 'aguardando_humano'`; se nenhuma linha mudou, devolver
    'já assumido por <vendedor>'."""
    from app.handoff import assumir_handoff
    abrir_handoff("5581")
    assumir_handoff("5581", "Ana")
    resposta_do_beto = assumir_handoff("5581", "Beto")
    assert linhas_handoff("5581")[0]["vendedor"] == "Ana", "O Beto sobrescreveu a Ana."
    assert "Ana" in resposta_do_beto, "O Beto deveria ser avisado de que a Ana já assumiu."


def test_mesmo_vendedor_assumir_de_novo_e_inofensivo(banco_temporario):
    """Duplo clique do MESMO vendedor não pode dar erro nem trocar o dono."""
    from app.handoff import assumir_handoff, estado_do_handoff
    abrir_handoff("5581")
    assumir_handoff("5581", "Ana")
    assumir_handoff("5581", "Ana")
    assert estado_do_handoff("5581") == "humano_assumiu"
    assert linhas_handoff("5581")[0]["vendedor"] == "Ana"


# ======================================================================
# C) SILÊNCIO DO LÉO QUANDO O HUMANO ASSUME
# ======================================================================

def test_whatsapp_leo_em_silencio_mas_mensagem_do_cliente_e_salva(whatsapp):
    from app.handoff import assumir_handoff
    from app.mensagens import historico_do_lead
    wh, grafo, saidas = whatsapp
    abrir_handoff("5581")
    assumir_handoff("5581", "Ana")

    asyncio.run(wh.processar_mensagem("5581", "e aí, consegue baixar o valor?"))

    assert grafo.entradas == [], "O Léo respondeu com um humano no comando."
    assert saidas.respostas == [], "Nada pode ser enviado ao cliente pelo Léo."
    hist = historico_do_lead("5581")
    assert [(m["direcao"], m["conteudo"]) for m in hist] == [("cliente", "e aí, consegue baixar o valor?")]


def test_whatsapp_leo_volta_a_responder_depois_de_devolvido(whatsapp):
    from app.handoff import assumir_handoff, devolver_ao_agente
    wh, grafo, saidas = whatsapp
    abrir_handoff("5581")
    assumir_handoff("5581", "Ana")
    asyncio.run(wh.processar_mensagem("5581", "primeira, com o humano"))
    devolver_ao_agente("5581")
    asyncio.run(wh.processar_mensagem("5581", "segunda, já com o Léo"))

    assert grafo.entradas == ["segunda, já com o Léo"]
    assert len(saidas.respostas) == 1


def test_whatsapp_aguardando_humano_leo_ainda_responde(whatsapp):
    """DECISÃO DE PRODUTO (abordagem A): o silêncio só vale depois que o humano
    ASSUME. Enquanto o lead está só na fila, o Léo continua atendendo.
    (Cuidado no prompt: ele não pode prometer prazo nem fechar condição.)"""
    wh, grafo, saidas = whatsapp
    abrir_handoff("5581")
    asyncio.run(wh.processar_mensagem("5581", "alguma novidade?"))
    assert grafo.entradas == ["alguma novidade?"]
    assert len(saidas.respostas) == 1


def test_silencio_vale_so_para_o_lead_com_humano(whatsapp):
    """Um lead em silêncio não pode calar os outros clientes da loja."""
    from app.handoff import assumir_handoff
    wh, grafo, saidas = whatsapp
    abrir_handoff("5581")
    assumir_handoff("5581", "Ana")
    asyncio.run(wh.processar_mensagem("5582", "oi, tem Civic?"))
    assert grafo.entradas == ["oi, tem Civic?"]


def test_silencio_libera_o_lock_do_lead(whatsapp):
    """O retorno antecipado (silêncio) cai no `finally`: o lock não pode
    ficar preso, senão o lead trava por 60 s depois que o Léo voltar."""
    from app.handoff import assumir_handoff, devolver_ao_agente
    wh, grafo, saidas = whatsapp
    abrir_handoff("5581")
    assumir_handoff("5581", "Ana")
    asyncio.run(wh.processar_mensagem("5581", "x"))
    devolver_ao_agente("5581")

    inicio = time.time()
    asyncio.run(wh.processar_mensagem("5581", "y"))
    assert time.time() - inicio < 5, "O lock ficou preso depois do silêncio."
    assert grafo.entradas == ["y"]


def test_telegram_leo_em_silencio_mas_mensagem_e_salva(monkeypatch, redis_falso, banco_temporario):
    from app.handoff import assumir_handoff
    from app.mensagens import historico_do_lead
    tb = importar_modulo("app.api.telegram_bot")
    grafo = GrafoFalso()
    monkeypatch.setattr(tb, "agente_grafo", grafo)
    abrir_handoff("777")
    assumir_handoff("777", "Ana")

    resposta, fotos = asyncio.run(tb.processar_texto("777", "pode baixar?"))

    assert (resposta, fotos) == (None, [])
    assert grafo.entradas == []
    assert [(m["direcao"], m["canal"]) for m in historico_do_lead("777")] == [("cliente", "telegram")]


def test_telegram_leo_responde_quando_nao_ha_humano(monkeypatch, redis_falso, banco_temporario):
    tb = importar_modulo("app.api.telegram_bot")
    grafo = GrafoFalso("Tenho sim!")
    monkeypatch.setattr(tb, "agente_grafo", grafo)
    resposta, fotos = asyncio.run(tb.processar_texto("777", "tem Civic?"))
    assert resposta == "Tenho sim!"
    assert grafo.entradas == ["tem Civic?"]


# ======================================================================
# D) PERSISTÊNCIA DE MENSAGENS
# ======================================================================

def test_conversa_normal_grava_cliente_e_leo_no_banco(whatsapp):
    from app.mensagens import historico_do_lead
    wh, grafo, saidas = whatsapp
    grafo.resposta = "Temos um Civic 2019!"
    asyncio.run(wh.processar_mensagem("5581", "tem Civic?"))
    hist = historico_do_lead("5581")
    assert [(m["direcao"], m["conteudo"], m["canal"]) for m in hist] == [
        ("cliente", "tem Civic?", "whatsapp"),
        ("leo", "Temos um Civic 2019!", "whatsapp"),
    ]


def test_guarda_grava_a_mensagem_segura_e_nao_o_preco_inventado(whatsapp):
    """Quando a guarda barra, o banco (e o painel do vendedor) guardam o que
    foi REALMENTE enviado ao cliente, e o vendedor recebe o handoff."""
    from app.guarda_politica import MENSAGEM_SEGURA
    from app.handoff import estado_do_handoff
    from app.mensagens import historico_do_lead
    wh, grafo, saidas = whatsapp
    grafo.resposta = "O Civic sai por R$ 77.000"   # preço sem origem em tool
    asyncio.run(wh.processar_mensagem("5581", "quanto é o Civic?"))

    assert saidas.respostas == [("5581", MENSAGEM_SEGURA)]
    hist = historico_do_lead("5581")
    assert hist[-1]["direcao"] == "leo" and hist[-1]["conteudo"] == MENSAGEM_SEGURA
    assert all("77.000" not in m["conteudo"] for m in hist)
    assert estado_do_handoff("5581") == "aguardando_humano"


def test_historico_vem_em_ordem_e_separado_por_lead_e_loja(banco_temporario):
    from app.mensagens import salvar_mensagem, historico_do_lead
    salvar_mensagem("A", "cliente", "um", canal="whatsapp")
    salvar_mensagem("A", "leo", "dois", canal="whatsapp")
    salvar_mensagem("B", "cliente", "outro lead", canal="whatsapp")
    salvar_mensagem("A", "cliente", "outra loja", canal="whatsapp", loja_id=2)
    assert [m["conteudo"] for m in historico_do_lead("A")] == ["um", "dois"]
    assert [m["conteudo"] for m in historico_do_lead("A", loja_id=2)] == ["outra loja"]


def test_salvar_mensagem_nunca_derruba_a_conversa(monkeypatch, tmp_path):
    """Banco inacessível: salvar_mensagem só registra no log, não levanta erro."""
    from app.mensagens import salvar_mensagem
    monkeypatch.setattr(banco, "CAMINHO_BANCO", str(tmp_path / "nao_existe" / "x.db"))
    salvar_mensagem("A", "cliente", "oi", canal="whatsapp")  # não pode levantar


def test_listar_leads_inclui_quem_conversou_sem_handoff(banco_temporario):
    """A tela de resultado precisa mostrar quem comprou SEM ter escalado."""
    from app.mensagens import salvar_mensagem, listar_leads
    salvar_mensagem("sem_handoff", "cliente", "oi", canal="whatsapp")
    salvar_mensagem("sem_handoff", "leo", "olá", canal="whatsapp")
    salvar_mensagem("outro", "cliente", "bom dia", canal="telegram")
    leads = {l["lead_id"]: l["total_mensagens"] for l in listar_leads()}
    assert leads == {"sem_handoff": 2, "outro": 1}


# ======================================================================
# E) RESULTADO DO LEAD
# ======================================================================

def test_lead_sem_resultado_devolve_none(banco_temporario):
    from app.resultados import resultado_do_lead
    assert resultado_do_lead("5581") is None


def test_registrar_resultado_e_consultar(banco_temporario):
    from app.resultados import registrar_resultado, resultado_do_lead
    registrar_resultado("5581", "comprou", motivo="fechou à vista", vendedor="Ana")
    r = resultado_do_lead("5581")
    assert (r["resultado"], r["motivo"], r["vendedor"]) == ("comprou", "fechou à vista", "Ana")


def test_remarcar_mantem_historico_e_vale_o_mais_recente(banco_temporario):
    from app.resultados import registrar_resultado, resultado_do_lead, listar_resultados
    registrar_resultado("5581", "compareceu", vendedor="Ana")
    registrar_resultado("5581", "perdeu", motivo="foi para a concorrência", vendedor="Ana")
    assert resultado_do_lead("5581")["resultado"] == "perdeu"
    assert [r["resultado"] for r in listar_resultados()] == ["perdeu", "compareceu"]


def test_resultados_nao_se_misturam_entre_lojas(banco_temporario):
    from app.resultados import registrar_resultado, resultado_do_lead, listar_resultados
    registrar_resultado("5581", "comprou", loja_id=2)
    assert resultado_do_lead("5581", loja_id=1) is None
    assert listar_resultados(loja_id=1) == []
    assert len(listar_resultados(loja_id=2)) == 1


def test_opcoes_de_resultado_sao_as_do_documento():
    from app.resultados import OPCOES_RESULTADO
    assert OPCOES_RESULTADO == ["compareceu", "comprou", "perdeu"]


# ======================================================================
# F) CRUD DE ESTOQUE
# ======================================================================

def test_adicionar_e_buscar_carro(banco_temporario):
    from app.estoque import adicionar_carro, buscar_carro
    novo = adicionar_carro("Fiat", "Argo", 2021, 30000, "Prata", "Manual", 62000.0)
    carro = buscar_carro(novo)
    assert (carro["modelo"], carro["preco"], carro["status"]) == ("Argo", 62000.0, "disponivel")


def test_atualizar_carro(banco_temporario):
    from app.estoque import adicionar_carro, atualizar_carro, buscar_carro
    novo = adicionar_carro("Fiat", "Argo", 2021, 30000, "Prata", "Manual", 62000.0)
    atualizar_carro(novo, "Fiat", "Argo", 2021, 31000, "Prata", "Manual", 60500.0,
                    "disponivel", "http://x/argo.jpg")
    carro = buscar_carro(novo)
    assert (carro["km"], carro["preco"], carro["fotos"]) == (31000, 60500.0, "http://x/argo.jpg")


def test_marcar_vendido_tira_o_carro_da_oferta_do_leo(banco_temporario):
    """A baixa no painel muda o que o Léo oferece NA HORA (seção 7 do doc)."""
    from app.estoque import adicionar_carro, marcar_status
    from tools import consultar_estoque
    novo = adicionar_carro("Fiat", "Argo", 2021, 30000, "Prata", "Manual", 62000.0)
    assert "Argo" in consultar_estoque.invoke({"modelo": "Argo"})
    marcar_status(novo, "vendido")
    assert "Argo" not in consultar_estoque.invoke({"modelo": "Argo"})
    marcar_status(novo, "disponivel")
    assert "Argo" in consultar_estoque.invoke({"modelo": "Argo"})


def test_listar_estoque_pode_esconder_vendidos(banco_temporario):
    from app.estoque import adicionar_carro, marcar_status, listar_estoque
    popular_estoque_exemplo()
    novo = adicionar_carro("Fiat", "Argo", 2021, 30000, "Prata", "Manual", 62000.0)
    marcar_status(novo, "vendido")
    todos = listar_estoque()
    sem_vendidos = listar_estoque(incluir_vendidos=False)
    assert any(c["id"] == novo for c in todos)
    assert all(c["id"] != novo for c in sem_vendidos)


def test_estoque_de_uma_loja_nao_vaza_para_outra(banco_temporario):
    from app.estoque import adicionar_carro, buscar_carro, listar_estoque, marcar_status
    novo = adicionar_carro("Fiat", "Argo", 2021, 30000, "Prata", "Manual", 62000.0, loja_id=2)
    assert buscar_carro(novo, loja_id=1) is None
    assert listar_estoque(loja_id=1) == []
    marcar_status(novo, "vendido", loja_id=1)          # loja errada: não pode afetar
    assert buscar_carro(novo, loja_id=2)["status"] == "disponivel"

    
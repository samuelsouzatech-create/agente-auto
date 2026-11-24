"""
SG2 (Maratona 4): o catálogo e um ramo de TESTE (imóveis fictícios). OFFLINE, IA falsa.

- O motor pergunta ao catálogo do ramo (fotos, preço do remarketing, item parecido).
- Uma loja do ramo de teste roda executar_turno, busca no catálogo, abre chamado ao humano e faz
  retomada, e NADA de segmentos/veiculos é carregado (provado num processo Python separado).
- Duas lojas de ramos diferentes ao mesmo tempo não se misturam.
- O ramo de teste nunca aparece como opção para loja real.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import banco
from app import lojas, segmentos
from app.catalogo import CATALOGO_VAZIO, Item, catalogo_da_loja
from app.lojas import criar_loja
from banco import conectar

RAIZ = Path(__file__).resolve().parents[1]
RAMO_TESTE = "_exemplo_imoveis"


def _loja_no_ar(nome, segmento=RAMO_TESTE):
    """Loja nova nasce "em teste" (P7): sem número de teste, ela fica quieta. Aqui: no ar."""
    from app.estado_loja import colocar_no_ar
    loja = criar_loja(nome, segmento=segmento)
    colocar_no_ar(loja)
    return loja


@pytest.fixture
def ocultos(monkeypatch):
    monkeypatch.setattr(segmentos, "RAMOS_OCULTOS_LIGADOS", True)


class LLMFalso:
    def __init__(self, respostas):
        self.respostas, self.prompts = list(respostas), []

    def invoke(self, mensagens):
        self.prompts.append(mensagens[0][1])
        return self.respostas.pop(0)


def _chamada(nome, args):
    return AIMessage(content="", tool_calls=[{"name": nome, "args": args, "id": f"c-{uuid.uuid4().hex[:8]}"}])


def _ler(sql, args=()):
    c = conectar()
    try:
        return [dict(l) for l in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _carro(loja_id, modelo="Civic", preco=98000, status="disponivel", fotos=""):
    c = conectar()
    linha = c.execute("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status, fotos) "
                      "VALUES (?, 'Honda', ?, 2019, 50000, 'Prata', 'Automático', ?, ?, ?) RETURNING id",
                      (loja_id, modelo, preco, status, fotos)).fetchone()
    c.commit()
    c.close()
    return linha["id"]


# ------------------------------------------------------------------ o ramo de teste fica escondido
def test_ramo_de_teste_nao_e_opcao_para_loja_real():
    assert RAMO_TESTE not in segmentos.segmentos_disponiveis()
    assert not segmentos.segmento_existe(RAMO_TESTE)
    with pytest.raises(lojas.ConfigInvalida):
        criar_loja("Imobiliária de mentira", segmento=RAMO_TESTE)


def test_ramo_de_teste_so_com_a_chave_dos_testes(ocultos):
    assert RAMO_TESTE in segmentos.segmentos_disponiveis()
    assert criar_loja("Imobiliária Teste", segmento=RAMO_TESTE) > 0


def test_operador_nao_lista_o_ramo_de_teste():
    from app import lojas_admin
    fonte = (RAIZ / "app" / "lojas_admin.py").read_text(encoding="utf-8")
    assert RAMO_TESTE not in fonte
    assert RAMO_TESTE not in getattr(lojas_admin, "SEGMENTOS", segmentos.segmentos_disponiveis())


# ------------------------------------------------------------------ catálogo
def test_catalogo_de_carro_e_o_estoque_e_nao_mistura_lojas():
    loja_b = criar_loja("Loja B SG2")
    a = _carro(1, "Civic")
    b = _carro(loja_b, "Corolla")
    cat = catalogo_da_loja(1)
    assert [i.nome for i in cat.buscar(1)] == ["Honda Civic 2019"]
    assert cat.detalhar(1, b) is None                       # o carro da B não aparece na A
    assert cat.detalhar(loja_b, b).nome == "Honda Corolla 2019"
    assert cat.disponivel(1, a) and not cat.disponivel(1, b)


def test_parecido_e_precos_pelo_catalogo():
    vendido = _carro(1, "Civic", 100000, status="vendido")
    perto = _carro(1, "Civic", 110000)
    _carro(1, "Fit", 60000)
    cat = catalogo_da_loja(1)
    item = cat.detalhar(1, vendido)
    assert item.situacao == "vendido" and cat.parecido(1, item).id == perto
    assert cat.precos(1, [vendido, perto]) == {10000000, 11000000}


def test_citados_no_texto():
    civic = _carro(1, "Civic")
    _carro(1, "Corolla", status="vendido")
    cat = catalogo_da_loja(1)
    assert [i.id for i in cat.citados_no_texto(1, "Civic 2019 impecável, chama no direct!")] == [civic]
    assert [i.situacao for i in cat.citados_no_texto(1, "Corolla saindo!")] == ["vendido"]
    assert cat.citados_no_texto(1, "Promoção de sábado") == []


def test_ramo_sem_catalogo_usa_o_vazio(tmp_path, monkeypatch):
    for nome in ("veiculos", "barbearia"):
        (tmp_path / nome).mkdir()
        (tmp_path / nome / "prompt.md").write_text(nome, encoding="utf-8")
    monkeypatch.setattr(segmentos, "PASTA_SEGMENTOS", tmp_path)
    loja = criar_loja("Barbearia SG2", segmento="barbearia")
    assert catalogo_da_loja(loja) is CATALOGO_VAZIO and catalogo_da_loja(loja).buscar(loja) == []


def test_ferramenta_de_fotos_pergunta_ao_catalogo(monkeypatch):
    from tools.enviar_fotos import enviar_fotos
    pedidos = []

    class Espiao:
        def buscar(self, loja_id, **filtros):
            pedidos.append(filtros)
            return [Item(id=7, nome="Item Sete", detalhe="azul")]

        def fotos(self, loja_id, item):
            return ["ref-1"]

    modulo = sys.modules["tools.enviar_fotos"]           # o módulo (tools.enviar_fotos é a ferramenta)
    monkeypatch.setattr(modulo, "catalogo_da_loja", lambda loja_id: Espiao())
    texto, artefato = enviar_fotos.func(modelo="Sete", loja_id=1)
    assert pedidos == [{"marca": "", "modelo": "Sete"}]
    assert artefato["urls"] == ["ref-1"] and "Item Sete" in texto


def test_motor_nao_le_a_tabela_estoque_nas_ferramentas_e_guardas():
    for rel in ("tools/enviar_fotos.py", "app/filtro_remarketing.py"):
        assert "FROM estoque" not in (RAIZ / rel).read_text(encoding="utf-8"), rel
    fonte = (RAIZ / "app" / "jobs" / "remarketing.py").read_text(encoding="utf-8")
    assert "JOIN estoque" not in fonte and "FROM estoque" not in fonte


# ------------------------------------------------------------------ a loja do ramo de teste
def _turno(loja_id, lead, texto, llm, monkeypatch):
    from app.core import agent
    from app.core.turno import executar_turno
    monkeypatch.setattr(agent, "llm", llm)
    return asyncio.run(executar_turno(loja_id, "telegram", lead, texto, grafo=agent.agente_grafo))


def test_loja_de_imoveis_busca_no_catalogo_e_abre_chamado(ocultos, monkeypatch):
    loja = _loja_no_ar("Imobiliária Ramo Teste")
    llm = LLMFalso([_chamada("consultar_imoveis", {"bairro": "Boa Viagem"}),
                    AIMessage(content="Temos um apartamento de 2 quartos em Boa Viagem. Quer visitar?")])
    r = _turno(loja, "im-1", "tem apartamento em boa viagem?", llm, monkeypatch)
    assert "Boa Viagem" in r.texto
    assert "consultar_imoveis" in llm.prompts[0] and "consultar_estoque" not in llm.prompts[0]
    assert "IMOBILIÁRIA" in llm.prompts[0]

    llm2 = LLMFalso([_chamada("acionar_handoff", {"motivo": "Quer visitar", "resumo": "Boa Viagem"}),
                     AIMessage(content="O pessoal da equipe vai falar com você por aqui.")])
    r2 = _turno(loja, "im-1", "quero falar com um corretor", llm2, monkeypatch)
    assert r2.handoff_aberto
    assert _ler("SELECT estado FROM handoffs WHERE loja_id = ? AND lead_id = 'im-1'", (loja,)) == \
        [{"estado": "aguardando_humano"}]


def test_guarda_propria_do_ramo_de_teste(ocultos, monkeypatch):
    loja = _loja_no_ar("Imobiliária Guarda")
    llm = LLMFalso([AIMessage(content="O apartamento está com documentação ok. Quer visitar?")])
    r = _turno(loja, "im-2", "a documentação tá certa?", llm, monkeypatch)
    assert "documentação ok" not in r.texto
    assert "o corretor confirma" in r.texto


def test_loja_de_imoveis_faz_retomada(ocultos, monkeypatch):
    from app.jobs import remarketing as rmk
    from app.resultado_envio import ResultadoEnvio
    from app.relogio import para_banco
    loja = _loja_no_ar("Imobiliária Retomada")
    lojas.salvar_config(loja, {"modulos.remarketing": True, "remarketing.limite_mensal": 50}, "teste")
    agora = datetime(2026, 11, 18, 14, 0, tzinfo=timezone.utc)          # quarta, 11:00 em Recife
    c = conectar()
    for direcao, horas, texto in (("cliente", 72, "tem casa em casa forte?"), ("leo", 71, "Temos sim!")):
        c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) "
                  "VALUES ('im-3', ?, 'telegram', ?, ?, ?)", (loja, direcao, texto, para_banco(agora - timedelta(hours=horas))))
    c.commit()
    c.close()

    class Enviador:
        textos = []

        async def texto(self, loja_id, canal, lead_id, texto):
            self.textos.append((loja_id, texto))
            return ResultadoEnvio(ok=True, id_externo="x1", detalhe="")

        async def modelo(self, loja_id, lead_id, modelo, valores):
            return ResultadoEnvio(ok=True, id_externo="x2", detalhe="")

    from app.custos import Uso
    totais = rmk.rodar_remarketing(agora, envio_real=True, pausa_s=0, lojas=[loja], enviador=Enviador(),
                                   redator=lambda *a: ("Oi! A casa em Casa Forte continua aqui, quer visitar?", Uso(10, 5, 0)))
    assert totais["enviado"] == 1, totais
    # O agente procura a retomada das últimas 72 h pelo relógio REAL: o envio passa a ser de 1 h atrás.
    from app.relogio import agora_utc
    c = conectar()
    c.execute("UPDATE remarketing_envios SET enviado_em = ? WHERE loja_id = ? AND lead_id = 'im-3'",
              (para_banco(agora_utc() - timedelta(hours=1)), loja))
    c.commit()
    c.close()
    llm = LLMFalso([AIMessage(content="Que bom! Posso marcar com o corretor.")])
    _turno(loja, "im-3", "quero sim", llm, monkeypatch)
    assert "RETOMADA QUE VOCÊ MANDOU" in llm.prompts[0]


def test_duas_lojas_de_ramos_diferentes_ao_mesmo_tempo(ocultos, monkeypatch):
    from app.core import agent
    from app.core.turno import executar_turno
    imob = _loja_no_ar("Imobiliária Paralela")
    _carro(1, "Civic")

    class LLMPorLoja:
        prompts = []

        def invoke(self, mensagens):
            prompt = mensagens[0][1]
            self.prompts.append(prompt)
            if isinstance(mensagens[-1], ToolMessage):
                return AIMessage(content=f"Achei: {mensagens[-1].content}")
            nome = "consultar_imoveis" if "IMOBILIÁRIA" in prompt else "consultar_estoque"
            return _chamada(nome, {})

    monkeypatch.setattr(agent, "llm", LLMPorLoja())

    async def juntos():
        return await asyncio.gather(
            executar_turno(imob, "telegram", "par-1", "o que tem?", grafo=agent.agente_grafo),
            executar_turno(1, "telegram", "par-2", "o que tem?", grafo=agent.agente_grafo),
            executar_turno(imob, "telegram", "par-3", "o que tem?", grafo=agent.agente_grafo),
            executar_turno(1, "telegram", "par-4", "o que tem?", grafo=agent.agente_grafo))
    r1, r2, r3, r4 = asyncio.run(juntos())
    for r in (r1, r3):
        assert "Boa Viagem" in r.texto and "Civic" not in r.texto
    for r in (r2, r4):
        assert "Civic" in r.texto and "Boa Viagem" not in r.texto
    assert _ler("SELECT DISTINCT loja_id FROM mensagens WHERE lead_id IN ('par-1', 'par-3')") == [{"loja_id": imob}]
    assert _ler("SELECT DISTINCT loja_id FROM mensagens WHERE lead_id IN ('par-2', 'par-4')") == [{"loja_id": 1}]


# ------------------------------------------------------------------ nada de veículos é carregado
ROTEIRO_SEPARADO = r'''
import asyncio, json, os, sys
sys.path.insert(0, sys.argv[1])
os.environ["GOOGLE_API_KEY"] = "chave-falsa"
import banco
banco.apontar_para(sys.argv[2])
from langchain_core.messages import AIMessage
from app import segmentos
segmentos.RAMOS_OCULTOS_LIGADOS = True
from app.lojas import criar_loja
from app.ator import definir_ator
from app.estado_loja import colocar_no_ar
from app.core import agent
from app.core.turno import executar_turno

class LLM:
    def __init__(self, r): self.r = list(r)
    def invoke(self, m): return self.r.pop(0)

definir_ator("Teste", "operador", "painel")
loja = criar_loja("Imobiliária Processo Separado", segmento="_exemplo_imoveis")
colocar_no_ar(loja)
agent.llm = LLM([AIMessage(content="", tool_calls=[{"name": "consultar_imoveis", "args": {}, "id": "c1"}]),
                 AIMessage(content="Temos 2 imóveis. O apartamento está com documentação ok."),
                 AIMessage(content="", tool_calls=[{"name": "acionar_handoff", "args": {"motivo": "m", "resumo": "r"}, "id": "c2"}]),
                 AIMessage(content="O pessoal da equipe vai falar com você por aqui.")])
r1 = asyncio.run(executar_turno(loja, "telegram", "sep-1", "o que tem?", grafo=agent.agente_grafo))
r2 = asyncio.run(executar_turno(loja, "telegram", "sep-1", "quero um corretor", grafo=agent.agente_grafo))
carregados = sorted(m for m in sys.modules if "veiculos" in m)
print(json.dumps({"r1": r1.texto, "handoff": r2.handoff_aberto, "carregados": carregados}))
'''


def test_loja_de_imoveis_nao_carrega_nada_de_veiculos(banco_limpo):
    """Num processo NOVO (nada carregado antes): turno, catálogo, guardas, chamado. No fim, nenhum
    módulo de segmentos/veiculos foi carregado."""
    banco.fechar_pools()
    saida = subprocess.run([sys.executable, "-c", ROTEIRO_SEPARADO, str(RAIZ), banco_limpo],
                           capture_output=True, text=True, timeout=180, cwd=str(RAIZ),
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"}, encoding="utf-8")
    assert saida.returncode == 0, saida.stderr[-3000:]
    resultado = json.loads(saida.stdout.strip().splitlines()[-1])
    assert resultado["carregados"] == [], resultado["carregados"]
    assert "o corretor confirma" in resultado["r1"]          # a guarda do ramo de teste rodou
    assert resultado["handoff"] is True

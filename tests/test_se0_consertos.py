"""
SE0 (Maratona Segurança): consertos da Maratona 4. OFFLINE, IA falsa, duas lojas.

1. "Mesmo cliente": só junta Instagram e WhatsApp se o contato do WhatsApp é NOVO na loja.
2. Exclusão de dados: venda e resultado ficam anônimos (os números não mudam); o resto sai.
3. Palavras dos comentários: lista padrão maior, sem acento e sem maiúscula.
5. "Transação só quando precisa" (banco.py, DK3): os casos difíceis.
(O item 4, UTF-8, está em tests/test_se0_utf8.py.)
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import banco
from app import canais, comentarios_instagram as ci, instagram_whatsapp as iw, lojas
from app.estado_loja import colocar_no_ar
from app.lojas import criar_loja
from app.relogio import para_banco
from banco import conectar

FONE = "5581999997777"
SEGREDO = "segredo-falso-se0"
ID_IG = "17841499990001"           # id do Instagram, com cara de único (para procurar no banco)
LEAD_IG = f"ig:{ID_IG}"


def _exec(sql, args=()):
    c = conectar()
    c.execute(sql, args)
    c.commit()
    c.close()


def _ler(sql, args=()):
    c = conectar()
    try:
        return [dict(l) for l in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _msg(loja, lead, canal, direcao, texto, quando):
    _exec("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo, criado_em) VALUES (?, ?, ?, ?, ?, ?)",
          (lead, loja, canal, direcao, texto, para_banco(quando)))


@pytest.fixture
def loja_b():
    loja = criar_loja("Loja B SE0")
    colocar_no_ar(loja)
    return loja


# ================================================================== 1. mesmo cliente
def test_contato_novo_no_whatsapp_junta():
    iw.gravar_telefone(1, "ig:se0-1", FONE)
    assert iw.vincular_mesmo_cliente(1, "whatsapp", FONE) == "ig:se0-1"
    assert _ler("SELECT lead_principal FROM clientes_vinculados WHERE loja_id = 1") == [{"lead_principal": "ig:se0-1"}]


def test_contato_antigo_no_whatsapp_nao_junta_e_vai_para_o_registro():
    antes = datetime.now(timezone.utc) - timedelta(days=3)
    _msg(1, FONE, "whatsapp", "cliente", "oi, quero revisar meu carro", antes)    # outra pessoa, de antes
    iw.gravar_telefone(1, "ig:se0-2", FONE)
    assert iw.vincular_mesmo_cliente(1, "whatsapp", FONE) is None
    assert iw.vincular_mesmo_cliente(1, "whatsapp", FONE) is None                  # a cada mensagem: não junta
    assert _ler("SELECT COUNT(*) AS n FROM clientes_vinculados") == [{"n": 0}]
    registro = _ler("SELECT loja_id, acao, alvo, pessoa FROM registro_acoes WHERE acao = 'mesmo_cliente_nao_juntou'")
    assert registro == [{"loja_id": 1, "acao": "mesmo_cliente_nao_juntou", "alvo": f"whatsapp:{FONE}",
                         "pessoa": "Sistema"}]                                       # anotado uma vez só
    from app.registro_leitura import rotulo
    assert "não juntei" in rotulo("mesmo_cliente_nao_juntou").lower()


def test_mensagem_depois_do_telefone_ainda_e_contato_novo():
    iw.gravar_telefone(1, "ig:se0-3", FONE)
    _msg(1, FONE, "whatsapp", "cliente", "oi, sou eu do insta", datetime.now(timezone.utc) + timedelta(seconds=1))
    assert iw.vincular_mesmo_cliente(1, "whatsapp", FONE) == "ig:se0-3"


def test_duas_lojas_o_contato_antigo_de_uma_nao_atrapalha_a_outra(loja_b):
    _msg(loja_b, FONE, "whatsapp", "cliente", "cliente antigo da B", datetime.now(timezone.utc) - timedelta(days=30))
    iw.gravar_telefone(1, "ig:se0-a", FONE)
    iw.gravar_telefone(loja_b, "ig:se0-b", FONE)
    assert iw.vincular_mesmo_cliente(1, "whatsapp", FONE) == "ig:se0-a"            # na A é novo: junta
    assert iw.vincular_mesmo_cliente(loja_b, "whatsapp", FONE) is None             # na B já existia: não
    assert {(l["loja_id"], l["lead_principal"]) for l in _ler(
        "SELECT loja_id, lead_principal FROM clientes_vinculados")} == {(1, "ig:se0-a")}
    assert [l["loja_id"] for l in _ler("SELECT loja_id FROM registro_acoes WHERE acao = 'mesmo_cliente_nao_juntou'")] == [loja_b]


# ================================================================== 2. exclusão de dados
def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).decode().rstrip("=")


def _assinado(conteudo: dict) -> str:
    dados = _b64(json.dumps(conteudo).encode())
    return _b64(hmac.new(SEGREDO.encode(), dados.encode(), hashlib.sha256).digest()) + "." + dados


def _pedir_exclusao(monkeypatch, user_id=ID_IG):
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", SEGREDO)
    from app.api.webhook import app
    r = TestClient(app).post("/dados/excluir", data={"signed_request": _assinado(
        {"algorithm": "HMAC-SHA256", "user_id": user_id})})
    assert r.status_code == 200
    return r.json()


def _carro(loja):
    c = conectar()
    linha = c.execute("INSERT INTO estoque (loja_id, marca, modelo, ano, km, cor, cambio, preco, status) "
                      "VALUES (?, 'Honda', 'Civic', 2019, 50000, 'Prata', 'Automático', 98000, 'vendido') "
                      "RETURNING id", (loja,)).fetchone()
    c.commit()
    c.close()
    return linha["id"]


def _cliente_completo(loja, lead=LEAD_IG, quando=None):
    """Um cliente do Instagram com tudo: conversa, ficha, telefone, interesse, chamado, aviso,
    visita, venda, resultado, custo, vínculo e linha no Registro."""
    quando = quando or datetime.now(timezone.utc) - timedelta(hours=3)
    carro = _carro(loja)
    _msg(loja, lead, "instagram", "cliente", "quero o civic, meu nome é Fulana", quando)
    _msg(loja, lead, "instagram", "leo", "Oi Fulana! O Civic está aqui.", quando + timedelta(minutes=1))
    _exec("INSERT INTO leads (lead_id, loja_id, nome, interesse, forma_pagamento) VALUES (?, ?, 'Fulana de Teste', 'Civic', 'avista')",
          (lead, loja))
    iw.gravar_telefone(loja, lead, FONE)
    _exec("INSERT INTO interesse_veiculo (loja_id, lead_id, veiculo_id) VALUES (?, ?, ?)", (loja, lead, carro))
    c = conectar()
    chamado = c.execute("INSERT INTO handoffs (lead_id, loja_id, motivo, resumo, estado, criado_em) "
                        "VALUES (?, ?, 'quer comprar', 'Fulana quer o Civic', 'aguardando_humano', ?) RETURNING id",
                        (lead, loja, para_banco(quando + timedelta(minutes=2)))).fetchone()["id"]
    c.commit()
    c.close()
    _exec("INSERT INTO avisos (loja_id, tipo, referencia, destino, texto, status) VALUES (?, 'handoff_novo', ?, 'chat-falso', "
          "'Fulana de Teste quer o Civic', 'enviado')", (loja, f"handoff:{chamado}"))
    _exec("INSERT INTO agendamentos (lead_id, loja_id, nome_cliente, tipo, data_hora) VALUES (?, ?, 'Fulana', 'visita', '2026-12-01 10:00')",
          (lead, loja))
    _exec("INSERT INTO vendas (loja_id, lead_id, veiculo_id, data_venda, forma_pagamento, vendedor) "
          "VALUES (?, ?, ?, ?, 'avista', 'Vendedor Teste')", (loja, lead, carro, date.today().isoformat()))
    _exec("INSERT INTO resultados (lead_id, loja_id, resultado, motivo, vendedor) VALUES (?, ?, 'comprou', 'Fulana pagou à vista', 'Vendedor Teste')",
          (lead, loja))
    _exec("INSERT INTO uso_custos (loja_id, lead_id, canal, execucao_id, custo_llm) VALUES (?, ?, 'instagram', 'exec-se0', 0.01)",
          (loja, lead))
    _exec("INSERT INTO registro_acoes (loja_id, pessoa, papel, acao, alvo, depois, origem) VALUES "
          "(?, 'Ana', 'cliente', 'assumir_conversa', ?, ?, 'painel')", (loja, f"instagram:{lead}", json.dumps({"telefone": FONE, "lead": lead})))
    return carro


def _numeros(loja):
    from app.api_painel.resultado import montar_resultado
    r = montar_resultado(loja, "mes")
    return {"vendas_registradas": r["vendas_registradas"], "funil_vendas": [f["total"] for f in r["funil"] if f["etapa"] == "vendas"],
            "resultados": _ler("SELECT resultado, vendedor, COUNT(*) AS n FROM resultados WHERE loja_id = ? "
                               "GROUP BY resultado, vendedor", (loja,)),
            "custo": _ler("SELECT SUM(custo_llm) AS c, COUNT(*) AS n FROM uso_custos WHERE loja_id = ?", (loja,)),
            "vendas": _ler("SELECT veiculo_id, data_venda, forma_pagamento, vendedor FROM vendas WHERE loja_id = ?", (loja,))}


def _onde_aparece(*procurados) -> list[str]:
    """Procura cada texto em TODAS as colunas de texto de TODAS as tabelas."""
    c = conectar()
    try:
        colunas = c.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = current_schema() "
                            "AND data_type IN ('text', 'character varying')").fetchall()
        achados = []
        for l in colunas:
            for p in procurados:
                n = c.execute(f"SELECT COUNT(*) AS n FROM {l['table_name']} WHERE strpos({l['column_name']}, ?) > 0", (p,)).fetchone()["n"]
                if n:
                    achados.append(f"{l['table_name']}.{l['column_name']}: {p}")
        return achados
    finally:
        c.close()


def test_numeros_do_resultado_continuam_iguais_depois_da_exclusao(monkeypatch):
    _cliente_completo(1)
    antes = _numeros(1)
    assert antes["vendas_registradas"] == 1
    _pedir_exclusao(monkeypatch)
    assert _numeros(1) == antes
    [venda] = _ler("SELECT lead_id FROM vendas WHERE loja_id = 1")
    [resultado] = _ler("SELECT lead_id, motivo FROM resultados WHERE loja_id = 1")
    assert venda["lead_id"].startswith("excluido:") and resultado == {"lead_id": venda["lead_id"], "motivo": None}


def test_nenhum_dado_pessoal_sobra(monkeypatch):
    _cliente_completo(1)
    assert _onde_aparece(ID_IG, FONE, "Fulana")                  # antes: está em tudo
    _pedir_exclusao(monkeypatch)
    assert _onde_aparece(ID_IG, FONE, "Fulana") == []
    for tabela in ("mensagens", "leads", "interesse_veiculo", "handoffs", "avisos", "agendamentos", "clientes_vinculados"):
        assert _ler(f"SELECT COUNT(*) AS n FROM {tabela} WHERE loja_id = 1") == [{"n": 0}], tabela


def test_memoria_da_conversa_apagada(monkeypatch):
    apagadas = []

    class Memoria:
        def delete_thread(self, thread):
            apagadas.append(thread)
    from app.core import agent
    monkeypatch.setattr(agent, "memoria", Memoria())
    _cliente_completo(1)
    _pedir_exclusao(monkeypatch)
    from app.chaves import thread_id
    assert thread_id(1, "instagram", LEAD_IG) in apagadas


def test_vinculo_com_o_whatsapp_sai_e_a_conversa_do_whatsapp_fica(monkeypatch):
    _cliente_completo(1)
    assert iw.vincular_mesmo_cliente(1, "whatsapp", FONE) == LEAD_IG
    _msg(1, FONE, "whatsapp", "cliente", "oi do zap", datetime.now(timezone.utc))
    _pedir_exclusao(monkeypatch)
    assert _ler("SELECT COUNT(*) AS n FROM clientes_vinculados") == [{"n": 0}]
    assert _ler("SELECT COUNT(*) AS n FROM leads WHERE telefone = ?", (FONE,)) == [{"n": 0}]
    assert _ler("SELECT conteudo FROM mensagens WHERE lead_id = ?", (FONE,)) == [{"conteudo": "oi do zap"}]   # decisão p/ o analista
    assert _onde_aparece(ID_IG) == []


def test_outra_loja_fica_intacta(loja_b, monkeypatch):
    _cliente_completo(1)
    _cliente_completo(loja_b)                       # o mesmo id em outra loja (não acontece na Meta, mas a regra vale)
    antes_b = _numeros(loja_b)
    feito = dados_excluir_so_na_loja(1)
    assert feito > 0
    assert _numeros(loja_b) == antes_b
    assert _ler("SELECT COUNT(*) AS n FROM mensagens WHERE loja_id = ? AND lead_id = ?", (loja_b, LEAD_IG)) == [{"n": 2}]
    assert _ler("SELECT nome, telefone FROM leads WHERE loja_id = ?", (loja_b,)) == [{"nome": "Fulana de Teste", "telefone": FONE}]
    assert _ler("SELECT COUNT(*) AS n FROM vendas WHERE loja_id = ? AND lead_id = ?", (loja_b, LEAD_IG)) == [{"n": 1}]
    assert _ler("SELECT COUNT(*) AS n FROM mensagens WHERE loja_id = 1") == [{"n": 0}]


def dados_excluir_so_na_loja(loja):
    from app.api import dados
    return dados.apagar_cliente(loja, LEAD_IG)


# ================================================================== 3. palavras dos comentários
def test_palavras_padrao_novas_e_dentro_do_limite():
    loja = lojas.carregar_loja(1)
    palavras = loja.get("instagram.palavras_comentario")
    assert palavras == ["quero", "valor", "preço", "quanto", "info", "tem", "ainda tem", "disponível",
                        "interesse", "financia", "parcela", "troca", "zap", "whatsapp"]
    assert len(palavras) <= 30
    lojas.salvar_config(1, {"instagram.palavras_comentario": palavras}, "teste")    # a validação aceita
    assert loja.get("instagram.limite_private_replies_h") == 20                      # o limite continua


@pytest.mark.parametrize("texto, recebe", [
    ("Ainda tem?", True), ("QUANTO", True), ("disponivel", True), ("Disponível?", True),
    ("qual o PREÇO", True), ("aceita troca?", True), ("me chama no Zap", True), ("mais informações", True),
    ("faz financiamento?", True), ("lindo carro", False), ("que sistema bonito", False), ("top demais", False),
])
def test_palavra_sem_acento_e_sem_maiuscula(texto, recebe):
    assert ci._palavra_combina(lojas.carregar_loja(1), texto) is recebe


def test_comentario_com_a_lista_padrao_recebe_a_mensagem(monkeypatch):
    from tests.test_ig2_comentarios import MetaFalsa, CONTA_A, _comentario
    monkeypatch.setenv("INSTAGRAM_TOKEN_A", "token-falso-a")
    canais.cadastrar_canal(1, "instagram", CONTA_A, "INSTAGRAM_TOKEN_A")
    lojas.salvar_config(1, {"modulos.instagram": True, "instagram.responder_comentarios": True}, "teste")
    falsa = MetaFalsa()
    monkeypatch.setattr(ci, "FABRICA_DO_CANAL", falsa.canal)
    agora = datetime.fromtimestamp(1764000500, tz=timezone.utc)
    for n, (texto, esperado) in enumerate((("Ainda tem?", "respondido"), ("lindo carro", "sem_palavra"))):
        c = _comentario(**{"Qual o valor?": texto, "18000000000000001": f"1800000000000009{n}"})
        assert asyncio.run(ci.tratar_comentario(1, c, agora=agora)) == esperado
    assert len(falsa.privadas) == 1


# ================================================================== 5. transação só quando precisa
ABREM = [
    # CTE com escrita
    "WITH novo AS (INSERT INTO t (a) VALUES (1) RETURNING id) SELECT id FROM novo",
    "with x as (update lojas set nome = nome returning id) select * from x",
    "WITH a AS (DELETE FROM t RETURNING *) SELECT * FROM a",
    "WITH RECURSIVE a AS (SELECT 1) , b AS (MERGE INTO t USING a ON true WHEN MATCHED THEN DELETE) SELECT 1",
    # SELECT que chama função que (pode) gravar
    "SELECT registrar_algo(1)", "SELECT minha_funcao()", "select public.gravar('x')",
    "SELECT set_config('leo.loja', '1', true)", "SELECT pg_advisory_xact_lock(1)", "SELECT nextval('s')",
    "SELECT setval('s', 1)",
    # COPY, LOCK e outros que não são leitura
    "COPY lojas TO STDOUT", "COPY (SELECT 1) TO STDOUT", "LOCK TABLE lojas IN SHARE MODE",
    "SET LOCAL leo.loja = '1'", "SET leo.loja = '1'", "VALUES (1)", "CALL fazer()", "DO $$ BEGIN END $$",
    "TABLE lojas", "EXPLAIN ANALYZE SELECT 1", "EXPLAIN ANALYZE DELETE FROM t",
    # comentário antes do comando (na dúvida, abre)
    "-- conta\nSELECT 1", "/* x */ SELECT 1",
    # minúsculas e quebra de linha
    "select *\nfrom lojas\nfor update", "select id into nova from lojas", "\n\n  insert into t values (1)",
    "SELECT * FROM lojas FOR\n  NO KEY UPDATE",
]
NAO_ABREM = [
    "SELECT * FROM lojas WHERE id = %s", "  select 1", "\nselect\ncount(*)\nfrom lojas",
    "WITH a AS (SELECT 1) SELECT * FROM a", "EXPLAIN SELECT 1", "SHOW server_version",
    "SELECT COALESCE(MAX(id), 0) FROM mensagens WHERE loja_id = %s",
    "SELECT lower(sem_acento(nome)) FROM lojas", "SELECT * FROM t WHERE x IN (1, 2) AND EXISTS (SELECT 1)",
    "SELECT 'texto com minha_funcao(1) dentro de aspas' AS a",
]


@pytest.mark.parametrize("comando", ABREM)
def test_casos_dificeis_abrem_transacao(comando):
    assert not banco.leitura_simples(comando), comando


@pytest.mark.parametrize("comando", NAO_ABREM)
def test_leitura_de_verdade_nao_abre(comando):
    assert banco.leitura_simples(comando), comando


def test_funcao_que_grava_chamada_por_select_e_desfeita_sem_commit():
    """O furo que o SE0 fechou: SELECT f() com f gravando rodava FORA da transação (gravava na
    hora, sem volta). Agora abre a transação, e fechar sem commit desfaz."""
    _exec("CREATE OR REPLACE FUNCTION se0_grava(t text) RETURNS int LANGUAGE sql AS "
          "$$ INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo) VALUES (t, 1, 'simulador', 'cliente', 'x') RETURNING 1 $$")
    try:
        c = conectar()
        try:
            c.execute("SELECT se0_grava('se0-func')").fetchone()
            assert c.in_transaction
        finally:
            c.close()                               # sem commit
        assert _ler("SELECT COUNT(*) AS n FROM mensagens WHERE lead_id = 'se0-func'") == [{"n": 0}]
    finally:
        _exec("DROP FUNCTION IF EXISTS se0_grava(text)")


def test_cte_com_escrita_de_verdade_e_desfeita_sem_commit():
    c = conectar()
    try:
        c.execute("WITH n AS (INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo) "
                  "VALUES ('se0-cte', 1, 'simulador', 'cliente', 'x') RETURNING id) SELECT id FROM n").fetchone()
        assert c.in_transaction
    finally:
        c.close()
    assert _ler("SELECT COUNT(*) AS n FROM mensagens WHERE lead_id = 'se0-cte'") == [{"n": 0}]

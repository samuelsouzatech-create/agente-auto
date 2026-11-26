"""
SE3 (Maratona Segurança): tranca por loja DENTRO do banco (Row Level Security, migração 23).

O app dos testes conecta com o usuário leo_app_teste (não é dono das tabelas, NOBYPASSRLS), como o
leo_app no Docker. Prova:
- toda tabela com loja_id tem a tranca ligada;
- conexão sem marca não vê nada; a marca de loja só vê a loja; o modo sistema vê tudo;
- uma rota do painel logada na loja A, com uma consulta que "esquece" o filtro de loja, não vê a B;
- a conexão devolvida ao pool volta SEM marca (nunca vaza para o próximo dono);
- a marca vale para todas as consultas da conexão, dentro e fora de transação (DK3).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

import banco
from app.estado_loja import colocar_no_ar
from app.lojas import criar_loja
from banco import conectar

RAIZ = Path(__file__).resolve().parent.parent


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


@pytest.fixture
def duas_lojas():
    b = criar_loja("Loja B Tranca")
    colocar_no_ar(b)
    for loja, lead in ((1, "5581911110001"), (b, "5581922220002")):
        _exec("INSERT INTO mensagens (lead_id, loja_id, canal, direcao, conteudo) VALUES (?, ?, 'whatsapp', 'cliente', ?)",
              (lead, loja, f"segredo da loja {loja}"))
    return 1, b


@pytest.fixture
def sem_declaracao():
    """Como a API do painel: o processo NÃO declarou o modo sistema."""
    banco.esquecer_declaracao()
    yield
    banco.declarar_sistema("testes (conftest)")


# ------------------------------------------------------------------ a tranca existe
def test_toda_tabela_com_loja_id_tem_a_tranca():
    c = conectar()
    try:
        com_loja = {l["table_name"] for l in c.execute(
            "SELECT c.table_name FROM information_schema.columns c JOIN information_schema.tables t "
            "ON t.table_name = c.table_name AND t.table_schema = c.table_schema "
            "WHERE c.table_schema = current_schema() AND c.column_name = 'loja_id' AND t.table_type = 'BASE TABLE'")}
        trancadas = {l["relname"] for l in c.execute(
            "SELECT relname FROM pg_class WHERE relrowsecurity AND relnamespace = 'public'::regnamespace")}
        com_regra = {l["tablename"] for l in c.execute(
            "SELECT tablename FROM pg_policies WHERE schemaname = 'public' AND policyname = 'leo_por_loja'")}
    finally:
        c.close()
    assert len(com_loja) > 30
    assert com_loja - trancadas == set(), "tabela com loja_id sem a tranca (faça uma migração que ligue)"
    assert com_loja - com_regra == set()


def test_o_app_dos_testes_passa_pela_tranca():
    assert banco.tranca_ligada()          # o usuário não é dono nem superusuário
    assert _ler("SELECT current_user AS u") == [{"u": "leo_app_teste"}]


def test_migracao_23_registrada():
    assert banco.versao_schema() >= 23
    assert _ler("SELECT nome FROM migracoes_aplicadas WHERE versao = 23") == [{"nome": "tranca_por_loja"}]


# ------------------------------------------------------------------ marcas
def test_conexao_sem_marca_nao_ve_nada(duas_lojas, sem_declaracao):
    assert _ler("SELECT COUNT(*) AS n FROM mensagens") == [{"n": 0}]
    assert _ler("SELECT COUNT(*) AS n FROM estado_lojas") == [{"n": 0}]
    with pytest.raises(banco.Erro):                       # e não grava
        _exec("INSERT INTO mensagens (lead_id, loja_id, canal, direcao) VALUES ('x', 1, 'whatsapp', 'cliente')")


def test_marca_de_loja_so_ve_a_loja(duas_lojas, sem_declaracao):
    a, b = duas_lojas
    with banco.como_loja(a):
        assert [l["loja_id"] for l in _ler("SELECT loja_id FROM mensagens")] == [a]
        with pytest.raises(banco.Erro):                   # não grava na outra loja
            _exec("INSERT INTO mensagens (lead_id, loja_id, canal, direcao) VALUES ('x', ?, 'whatsapp', 'cliente')", (b,))
        _exec("UPDATE mensagens SET conteudo = 'mexido'")         # UPDATE sem filtro: só a A
    with banco.como_loja(b):
        assert _ler("SELECT conteudo FROM mensagens") == [{"conteudo": f"segredo da loja {b}"}]
        assert _ler("SELECT COUNT(*) AS n FROM registro_acoes WHERE loja_id IS NULL") == [{"n": 0}]


def test_modo_sistema_ve_tudo(duas_lojas, sem_declaracao):
    with banco.como_sistema("teste"):
        assert {l["loja_id"] for l in _ler("SELECT loja_id FROM mensagens")} == set(duas_lojas)
    assert _ler("SELECT COUNT(*) AS n FROM mensagens") == [{"n": 0}]       # e volta ao que era


def test_processo_declarado_sistema_ve_tudo(duas_lojas):
    assert {l["loja_id"] for l in _ler("SELECT loja_id FROM mensagens")} == set(duas_lojas)


def test_marca_vale_dentro_e_fora_de_transacao(duas_lojas, sem_declaracao):
    a, b = duas_lojas
    with banco.como_loja(a):
        c = conectar()
        try:
            assert len(c.execute("SELECT * FROM mensagens").fetchall()) == 1          # fora de transação (DK3)
            c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao) VALUES ('t1', ?, 'whatsapp', 'cliente')", (a,))
            assert c.in_transaction
            assert {l["loja_id"] for l in c.execute("SELECT loja_id FROM mensagens").fetchall()} == {a}
            c.commit()
            assert {l["loja_id"] for l in c.execute("SELECT loja_id FROM mensagens").fetchall()} == {a}   # depois do commit
            c.execute("INSERT INTO mensagens (lead_id, loja_id, canal, direcao) VALUES ('t2', ?, 'whatsapp', 'cliente')", (a,))
            c.rollback()
            assert {l["loja_id"] for l in c.execute("SELECT loja_id FROM mensagens").fetchall()} == {a}   # depois do rollback
            assert banco.marca_da_conexao(c) == ("loja", str(a))
        finally:
            c.close()


def test_somente_leitura_tambem_tem_a_marca(duas_lojas, sem_declaracao):
    a, _ = duas_lojas
    with banco.como_loja(a):
        c = conectar(somente_leitura=True)
        try:
            assert {l["loja_id"] for l in c.execute("SELECT loja_id FROM mensagens").fetchall()} == {a}
        finally:
            c.close()


# ------------------------------------------------------------------ o pool não vaza a marca
def test_conexao_devolvida_ao_pool_volta_sem_marca(duas_lojas, sem_declaracao):
    a, _ = duas_lojas
    banco.fechar_pools()
    with banco.como_loja(a):
        c = conectar()
        bruta = c._bruta
        assert banco.marca_da_conexao(c) == ("loja", str(a))
        c.close()
    pool = banco._pool(banco.url_do_banco())
    cruas = [pool.getconn() for _ in range(pool.get_stats()["pool_size"])]    # TODAS, direto do pool
    try:
        assert any(crua is bruta for crua in cruas)                           # inclusive a que tinha a marca
        for crua in cruas:
            linha = crua.execute("SELECT current_setting('leo.modo', true), current_setting('leo.loja', true)").fetchone()
            assert (linha[0] or "", linha[1] or "") == ("", "")
            crua.rollback()
    finally:
        for crua in cruas:
            pool.putconn(crua)
    c = conectar()                                     # e o próximo dono, sem marca, não vê nada
    try:
        assert c.execute("SELECT COUNT(*) FROM mensagens").fetchone()[0] == 0
    finally:
        c.close()


def test_sistema_seguido_de_sem_marca_nao_herda(duas_lojas, sem_declaracao):
    banco.fechar_pools()
    with banco.como_sistema("teste"):
        assert _ler("SELECT COUNT(*) AS n FROM mensagens") == [{"n": 2}]
    assert _ler("SELECT COUNT(*) AS n FROM mensagens") == [{"n": 0}]


# ------------------------------------------------------------------ a API do painel
def _app_com_rota_esquecida():
    """A API do painel de verdade + uma rota que 'esquece' o filtro de loja na consulta."""
    from app.api_painel.dependencias import loja_da_sessao
    from app.api_painel.main import criar_app
    app = criar_app()

    @app.get("/api/v1/teste-se3/todas-as-mensagens")
    def todas(loja: int = Depends(loja_da_sessao)):
        c = conectar()
        try:
            linhas = c.execute("SELECT loja_id, conteudo FROM mensagens ORDER BY id").fetchall()   # SEM filtro de loja
            sem_loja = c.execute("SELECT COUNT(*) FROM registro_acoes WHERE loja_id IS NULL").fetchone()[0]
            modo = banco.marca_da_conexao(c)
        finally:
            c.close()
        return {"lojas": sorted({l["loja_id"] for l in linhas}), "conteudos": [l["conteudo"] for l in linhas],
                "sem_loja": sem_loja, "modo": list(modo), "da_sessao": loja}
    return app


def _logar(cliente, loja, email):
    from app.ator import como
    from app import autenticacao
    with como("Teste", "operador", "painel", None):
        autenticacao.criar_usuario_com_login(loja, "Pessoa Teste", "dono", email, "senha-forte-de-teste-1")
    r = cliente.post("/api/v1/auth/login", json={"email": email, "senha": "senha-forte-de-teste-1"})
    assert r.status_code == 200, r.text


def test_rota_do_painel_que_esquece_o_filtro_nao_ve_a_outra_loja(duas_lojas):
    a, b = duas_lojas
    _exec("INSERT INTO registro_acoes (loja_id, pessoa, papel, acao, origem) VALUES (NULL, 'x', 'sistema', 'evento_sem_loja', 'job')")
    cliente = TestClient(_app_com_rota_esquecida(), base_url="https://testserver")   # o cookie é Secure
    _logar(cliente, a, "dona@loja-a.invalid")
    r = cliente.get("/api/v1/teste-se3/todas-as-mensagens")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["lojas"] == [a] and corpo["da_sessao"] == a
    assert f"segredo da loja {b}" not in corpo["conteudos"]
    assert corpo["sem_loja"] == 0                          # nem o que é "de ninguém"
    assert corpo["modo"] == ["loja", str(a)]               # nunca o modo sistema
    outro = TestClient(_app_com_rota_esquecida(), base_url="https://testserver")
    _logar(outro, b, "dona@loja-b.invalid")
    assert outro.get("/api/v1/teste-se3/todas-as-mensagens").json()["lojas"] == [b]


def test_rota_do_painel_sem_login_nao_ve_nada(duas_lojas):
    from app.api_painel.main import criar_app
    app = criar_app()

    @app.get("/api/v1/teste-se3/sem-login")
    def sem_login():
        c = conectar()
        try:
            return {"n": c.execute("SELECT COUNT(*) FROM mensagens").fetchone()[0], "modo": list(banco.marca_da_conexao(c))}
        finally:
            c.close()
    assert TestClient(app).get("/api/v1/teste-se3/sem-login").json() == {"n": 0, "modo": ["", ""]}   # mesmo com o processo em modo sistema


def test_rotas_do_painel_de_verdade_continuam_funcionando(duas_lojas):
    a, b = duas_lojas
    from app.api_painel.main import criar_app
    cliente = TestClient(criar_app(), base_url="https://testserver")
    _logar(cliente, a, "dona2@loja-a.invalid")
    r = cliente.get("/api/v1/leads")
    assert r.status_code == 200
    assert "5581922220002" not in r.text


# ------------------------------------------------------------------ onde o modo sistema é declarado
LUGARES_DO_MODO_SISTEMA = {
    "app/api/webhook.py", "app/jobs/runner.py", "app/jobs/remarketing.py", "app/jobs/pos_venda.py",
    "app/jobs/reativacao.py", "app/api/telegram_bot.py", "app/vigia.py", "app/api_painel/exportar.py",
    "operador.py", "app.py", "ingestao_rag.py",
}


def test_cada_programa_que_liga_sozinho_declara_o_modo_sistema():
    scripts = {p.relative_to(RAIZ).as_posix() for p in (RAIZ / "scripts").glob("*.py")
               if re.search(r"^(import banco|from banco|from app|import app)", p.read_text(encoding="utf-8"), re.M)}
    assert len(scripts) > 5
    for arquivo in LUGARES_DO_MODO_SISTEMA | scripts:
        texto = (RAIZ / arquivo).read_text(encoding="utf-8")
        assert "declarar_sistema(" in texto, f"{arquivo} não declara o modo sistema"


def test_api_do_painel_so_usa_o_modo_sistema_antes_do_login():
    """Na API do painel o modo sistema só aparece nos pontos antes de haver loja (lista fechada)."""
    usos = []
    for arquivo in sorted((RAIZ / "app" / "api_painel").rglob("*.py")):
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            m = re.search(r'como_sistema\("([^"]+)"\)', linha)
            if m:
                usos.append((arquivo.name, m.group(1)))
            assert "declarar_sistema(" not in linha or arquivo.name == "exportar.py", arquivo.name
    assert usos == [
        ("dependencias.py", "painel: achar a sessão pelo token"),
        ("rotas_auth.py", "painel: login (achar a pessoa pelo e-mail)"),
        ("rotas_auth.py", "painel: esqueci a senha (achar a pessoa pelo e-mail)"),
        ("rotas_auth.py", "painel: criar senha (achar a pessoa pelo link)"),
        ("rotas_auth.py", "painel: criar senha (anotar link errado)"),
        ("rotas_link.py", "painel: link do vendedor (achar o link pelo token)"),
    ]


def test_compose_app_usa_o_usuario_do_app_e_o_migrar_usa_o_dono():
    texto = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")
    assert "postgresql://${BANCO_APP_USUARIO:-leo_app}:${BANCO_APP_SENHA" in texto
    migrar = texto.split("\n  migrar:\n")[1].split("\n  webhook:")[0]
    assert "BANCO_URL: postgresql://leo:${POSTGRES_SENHA" in migrar
